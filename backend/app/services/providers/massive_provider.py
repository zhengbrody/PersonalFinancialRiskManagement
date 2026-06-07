"""Massive Stocks (Basic, free tier) provider — market-price/history FALLBACK.

Deliberately NOT a production primary source. yfinance stays the default free
market-data source; this adapter only fills gaps (a yfinance symbol that came
back empty/NaN/errored). FMP keeps fundamentals/analyst/peers — Massive never
touches those.

Free Basic is rate-limited to ~5 calls/min, so this module:
* caches aggressively in-process (price ~20m, history ~12h, reference ~24h),
* only implements LOW-FREQUENCY reads (EOD price, daily bars ≤2y, reference) —
  no WebSocket / snapshot / intraday-second aggregates,
* surfaces 429 as an explicit ``massive_rate_limited`` warning and never retries
  (retrying a free-tier rate limit just digs the hole deeper),
* is fully fail-soft: missing key / 429 / 5xx / unknown ticker / bad JSON all
  return ``ProviderResult(data=None, warnings=[...])`` so the page never 500s.

The HTTP contract (base URL, endpoint paths, JSON field names) is intentionally
overridable via env + tolerant parsing, because the exact Massive Basic schema
must be confirmed against the live API/key before it returns live data. Until
then every leg fail-softs to ``None`` and yfinance remains the source — zero
regression.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Optional

from ...schemas.providers import CompanyProfile, PriceBar, ProviderResult

_log = logging.getLogger(__name__)

# ── config (all overridable; sensible defaults) ─────────────────────
_DEFAULT_BASE_URL = "https://api.massivestocks.com"
_TIMEOUT = 6.0

# Endpoint path templates — overridable so the mapping can be corrected against
# the real Massive Basic docs without a code change. Use ``or`` (not getenv's
# default arg) so an EMPTY env value (compose passes `${VAR:-}` = "") still
# falls back to the default instead of becoming a broken empty path.
_EOD_PATH = os.getenv("MASSIVE_EOD_PATH") or "/v1/eod/{ticker}"
_HISTORY_PATH = os.getenv("MASSIVE_HISTORY_PATH") or "/v1/history/{ticker}"
_REFERENCE_PATH = os.getenv("MASSIVE_REFERENCE_PATH") or "/v1/reference/{ticker}"

# TTLs (seconds) — keep the 5 calls/min budget intact.
_TTL_PRICE = 20 * 60
_TTL_HISTORY = 12 * 60 * 60
_TTL_REFERENCE = 24 * 60 * 60

_MAX_HISTORY_DAYS = 365 * 2  # Basic: cap at 2 years of daily bars.

_cache: dict[str, tuple[float, ProviderResult]] = {}


def reset_cache() -> None:
    _cache.clear()


def _key() -> str:
    return (os.getenv("MASSIVE_API_KEY") or "").strip()


def _base_url() -> str:
    return (os.getenv("MASSIVE_BASE_URL") or _DEFAULT_BASE_URL).rstrip("/")


def is_configured() -> bool:
    return bool(_key())


def _num(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f and f not in (float("inf"), float("-inf")) else None


def _pick(d: Optional[dict], *names: str) -> Any:
    if not isinstance(d, dict):
        return None
    for n in names:
        if n in d and d[n] is not None:
            return d[n]
    return None


def _get(path: str, params: Optional[dict] = None) -> Any:
    """One GET against Massive. Raises ``_RateLimited`` on 429 so the caller can
    warn specifically; any other failure raises and is caught upstream → None."""
    import requests

    url = _base_url() + path
    headers = {"Authorization": f"Bearer {_key()}", "Accept": "application/json"}
    resp = requests.get(url, params=params or {}, headers=headers, timeout=_TIMEOUT)
    if resp.status_code == 429:
        raise _RateLimited()
    resp.raise_for_status()
    return resp.json()


class _RateLimited(Exception):
    """Massive returned HTTP 429 (free-tier 5 calls/min exceeded)."""


def _cached(domain: str, ticker: str, ttl: int, producer) -> ProviderResult:
    """Run ``producer`` behind the TTL cache + the fail-soft contract."""
    if not _key():
        return ProviderResult(data=None, source="massive", warnings=["massive_key_missing"])

    ck = f"{domain}:{ticker}"
    now = time.time()
    hit = _cache.get(ck)
    if hit is not None and now - hit[0] < ttl:
        return hit[1]

    try:
        result = producer()
    except _RateLimited:
        _log.warning("massive.rate_limited domain=%s ticker=%s", domain, ticker)
        return ProviderResult(data=None, source="massive", warnings=["massive_rate_limited"])
    except Exception as exc:  # noqa: BLE001 - any upstream failure → fail-soft
        _log.warning("massive.error domain=%s ticker=%s err=%s", domain, ticker, type(exc).__name__)
        return ProviderResult(
            data=None, source="massive", warnings=[f"massive_error:{type(exc).__name__}"]
        )

    _cache[ck] = (now, result)
    return result


# ── public reads (low-frequency only) ───────────────────────────────


def get_latest_price(ticker: str) -> ProviderResult[PriceBar]:
    """Most recent end-of-day close + date for one ticker (fallback)."""
    tk = (ticker or "").strip().upper()
    if not tk:
        return ProviderResult(data=None, source="massive", warnings=["bad_ticker"])

    def _produce() -> ProviderResult:
        raw = _get(_EOD_PATH.format(ticker=tk), {"symbol": tk})
        row = raw[0] if isinstance(raw, list) and raw else raw
        close = _num(_pick(row, "close", "c", "price", "adjClose", "adjusted_close"))
        date = _pick(row, "date", "d", "t", "timestamp")
        if close is None:
            return ProviderResult(data=None, source="massive", warnings=["no_price"])
        bar = PriceBar(date=str(date) if date else "", close=close)
        return ProviderResult(data=bar, source="massive", as_of=bar.date or None, coverage=1.0)

    return _cached("price", tk, _TTL_PRICE, _produce)


def get_daily_history(ticker: str, *, days: int = 365) -> ProviderResult[list[PriceBar]]:
    """Daily close bars for one ticker, oldest→newest, capped at 2 years."""
    tk = (ticker or "").strip().upper()
    if not tk:
        return ProviderResult(data=None, source="massive", warnings=["bad_ticker"])
    days = min(max(int(days), 1), _MAX_HISTORY_DAYS)

    def _produce() -> ProviderResult:
        raw = _get(_HISTORY_PATH.format(ticker=tk), {"symbol": tk, "days": days})
        rows = raw if isinstance(raw, list) else (raw.get("results") or raw.get("data") or [])
        bars: list[PriceBar] = []
        for r in rows:
            close = _num(_pick(r, "close", "c", "price", "adjClose", "adjusted_close"))
            date = _pick(r, "date", "d", "t", "timestamp")
            if close is not None and date:
                bars.append(PriceBar(date=str(date), close=close))
        if not bars:
            return ProviderResult(data=None, source="massive", warnings=["no_history"])
        bars.sort(key=lambda b: b.date)  # oldest → newest
        return ProviderResult(data=bars, source="massive", as_of=bars[-1].date, coverage=1.0)

    return _cached("history", tk, _TTL_HISTORY, _produce)


def get_reference(ticker: str) -> ProviderResult[CompanyProfile]:
    """Lightweight reference metadata (name/exchange/currency) if the endpoint
    exists. Never authoritative — FMP/yfinance own fundamentals."""
    tk = (ticker or "").strip().upper()
    if not tk:
        return ProviderResult(data=None, source="massive", warnings=["bad_ticker"])

    def _produce() -> ProviderResult:
        raw = _get(_REFERENCE_PATH.format(ticker=tk), {"symbol": tk})
        row = raw[0] if isinstance(raw, list) and raw else raw
        if not isinstance(row, dict):
            return ProviderResult(data=None, source="massive", warnings=["no_reference"])
        prof = CompanyProfile(
            ticker=tk,
            name=_pick(row, "name", "companyName"),
            exchange=_pick(row, "exchange", "exchangeShortName"),
            currency=_pick(row, "currency"),
        )
        return ProviderResult(data=prof, source="massive", coverage=1.0)

    return _cached("reference", tk, _TTL_REFERENCE, _produce)
