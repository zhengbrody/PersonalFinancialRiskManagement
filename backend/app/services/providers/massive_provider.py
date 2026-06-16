"""Massive Stocks provider — primary market price/history when configured.

Massive is the registry's primary source for US stock prices, daily OHLC,
volume/ADV, and ticker metadata. yfinance remains the no-key fallback so the
product stays usable when Massive is missing, rate-limited, or unavailable. FMP
keeps fundamentals/analyst/peers — Massive never touches those.

Free Basic is rate-limited to ~5 calls/min, so this module:
* caches aggressively in-process (price ~20m, history ~12h, reference ~24h),
* only implements LOW-FREQUENCY reads (EOD price, daily bars ≤2y, reference) —
  no WebSocket / snapshot / intraday-second aggregates,
* surfaces 429 as an explicit ``massive_rate_limited`` warning and never retries
  (retrying a free-tier rate limit just digs the hole deeper),
* is fully fail-soft: missing key / 429 / 5xx / unknown ticker / bad JSON all
  return ``ProviderResult(data=None, warnings=[...])`` so the page never 500s.

The HTTP contract (base URL, endpoint paths, JSON field names) is intentionally
overridable via env + tolerant parsing. Every leg fail-softs to ``None`` so
yfinance can fill the gap — zero regression.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Optional

from ...schemas.providers import CompanyProfile, PriceBar, ProviderResult

_log = logging.getLogger(__name__)

# ── config (all overridable; sensible defaults) ─────────────────────
# Massive's REST API is Polygon-style: base https://api.massive.com, auth via
# ?apiKey=, aggregate bars under /v2/aggs/ticker/..., results in a `results`
# array of {t(epoch ms), o, h, l, c, v} bars. Verified live against the Basic
# free key (prev + range both 200).
_DEFAULT_BASE_URL = "https://api.massive.com"
_TIMEOUT = 6.0

# Endpoint path templates — overridable via env (use ``or`` not getenv's default
# arg so compose's empty `${VAR:-}` still falls back to the default). The history
# template carries {from}/{to} date placeholders filled per-request.
_EOD_PATH = os.getenv("MASSIVE_EOD_PATH") or "/v2/aggs/ticker/{ticker}/prev"
_HISTORY_PATH = (
    os.getenv("MASSIVE_HISTORY_PATH") or "/v2/aggs/ticker/{ticker}/range/1/day/{from}/{to}"
)
_REFERENCE_PATH = os.getenv("MASSIVE_REFERENCE_PATH") or "/v3/reference/tickers/{ticker}"

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


def _epoch_ms_to_date(v: Any) -> Optional[str]:
    """Massive bar timestamps are Unix MILLISECONDS (`t`). Convert to an ISO
    YYYY-MM-DD (UTC). Pass through an already-ISO string unchanged."""
    if v is None:
        return None
    if isinstance(v, str):
        return v[:10] if v else None
    try:
        from datetime import datetime, timezone

        return datetime.fromtimestamp(float(v) / 1000.0, tz=timezone.utc).strftime("%Y-%m-%d")
    except (TypeError, ValueError, OSError):
        return None


def _results(raw: Any) -> list:
    """Massive wraps rows in ``{status, results: [...]}``; tolerate a bare list."""
    if isinstance(raw, dict):
        return raw.get("results") or raw.get("data") or []
    return raw if isinstance(raw, list) else []


def _get(path: str, params: Optional[dict] = None) -> Any:
    """One GET against Massive. Auth is a ``?apiKey=`` query param (Polygon-style),
    NOT a Bearer header. Raises ``_RateLimited`` on 429 so the caller can warn
    specifically; any other failure raises and is caught upstream → None."""
    import requests

    url = _base_url() + path
    q = dict(params or {})
    q["apiKey"] = _key()
    resp = requests.get(url, params=q, headers={"Accept": "application/json"}, timeout=_TIMEOUT)
    if resp.status_code == 429:
        raise _RateLimited()
    resp.raise_for_status()
    return resp.json()


class _RateLimited(Exception):
    """Massive returned HTTP 429 (free-tier 5 calls/min exceeded)."""


def _cached(domain: str, ticker: str, ttl: int, producer) -> ProviderResult:
    """Run ``producer`` behind the TTL cache + the fail-soft contract."""
    from .. import metrics

    if not _key():
        metrics.record_provider("massive", "no_key")
        return ProviderResult(data=None, source="massive", warnings=["massive_key_missing"])

    ck = f"{domain}:{ticker}"
    now = time.time()
    hit = _cache.get(ck)
    if hit is not None and now - hit[0] < ttl:
        metrics.record_provider("massive", "cache_hit")
        return hit[1]

    try:
        result = producer()
    except _RateLimited:
        _log.warning("massive.rate_limited domain=%s ticker=%s", domain, ticker)
        metrics.record_provider("massive", "rate_limited")
        return ProviderResult(data=None, source="massive", warnings=["massive_rate_limited"])
    except Exception as exc:  # noqa: BLE001 - any upstream failure → fail-soft
        _log.warning("massive.error domain=%s ticker=%s err=%s", domain, ticker, type(exc).__name__)
        metrics.record_provider("massive", "error")
        return ProviderResult(
            data=None, source="massive", warnings=[f"massive_error:{type(exc).__name__}"]
        )

    metrics.record_provider("massive", "ok" if result.data is not None else "empty")
    _cache[ck] = (now, result)
    return result


# ── public reads (low-frequency only) ───────────────────────────────


def get_latest_price(ticker: str) -> ProviderResult[PriceBar]:
    """Most recent end-of-day close + date for one ticker."""
    tk = (ticker or "").strip().upper()
    if not tk:
        return ProviderResult(data=None, source="massive", warnings=["bad_ticker"])

    def _produce() -> ProviderResult:
        raw = _get(_EOD_PATH.format(ticker=tk), {"adjusted": "true"})
        rows = _results(raw)
        row = rows[0] if rows else (raw if isinstance(raw, dict) else None)
        close = _num(_pick(row, "c", "close", "price"))
        date = _epoch_ms_to_date(_pick(row, "t", "date", "timestamp"))
        if close is None:
            return ProviderResult(data=None, source="massive", warnings=["no_price"])
        bar = PriceBar(date=date or "", close=close)
        return ProviderResult(data=bar, source="massive", as_of=bar.date or None, coverage=1.0)

    return _cached("price", tk, _TTL_PRICE, _produce)


def get_daily_history(ticker: str, *, days: int = 365) -> ProviderResult[list[PriceBar]]:
    """Daily close bars for one ticker, oldest→newest, capped at 2 years."""
    tk = (ticker or "").strip().upper()
    if not tk:
        return ProviderResult(data=None, source="massive", warnings=["bad_ticker"])
    days = min(max(int(days), 1), _MAX_HISTORY_DAYS)

    def _produce() -> ProviderResult:
        from datetime import date as _date
        from datetime import timedelta

        end = _date.today()
        start = end - timedelta(days=days)
        path = _HISTORY_PATH.format(ticker=tk, **{"from": start.isoformat(), "to": end.isoformat()})
        raw = _get(path, {"adjusted": "true", "sort": "asc", "limit": 50000})
        bars: list[PriceBar] = []
        for r in _results(raw):
            close = _num(_pick(r, "c", "close", "price"))
            date = _epoch_ms_to_date(_pick(r, "t", "date", "timestamp"))
            if close is not None and date:
                bars.append(PriceBar(date=date, close=close))
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
        raw = _get(_REFERENCE_PATH.format(ticker=tk))
        # v3 reference returns a SINGLE results object (not an array).
        res = raw.get("results") if isinstance(raw, dict) else raw
        row = res[0] if isinstance(res, list) and res else res
        if not isinstance(row, dict):
            return ProviderResult(data=None, source="massive", warnings=["no_reference"])
        prof = CompanyProfile(
            ticker=tk,
            name=_pick(row, "name", "companyName"),
            exchange=_pick(row, "primary_exchange", "exchange", "exchangeShortName"),
            currency=_pick(row, "currency_name", "currency"),
        )
        return ProviderResult(data=prof, source="massive", coverage=1.0)

    return _cached("reference", tk, _TTL_REFERENCE, _produce)
