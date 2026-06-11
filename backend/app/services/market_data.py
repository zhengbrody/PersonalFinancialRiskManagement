"""Backend-side market data orchestrator.

Wraps the existing ``CachedDataProvider`` (file-cached yfinance) so the
FastAPI layer never reaches the network directly. Two public helpers:

* ``get_latest_prices(tickers)`` — last available close per ticker.
  Used by the public ``GET /api/v1/market/prices`` endpoint.

* ``get_price_history(tickers, days)`` — full price DataFrame for a
  trailing window. Used internally by ``/api/v1/risk/score_from_active``
  to compute both ``market_value`` and the returns matrix in one shot.

Both calls go through the same per-ticker cache (default 24h TTL,
configurable on the underlying provider). That means the second user
to ask for SPY's price within a day pays no network cost.

This module is the only place that talks to ``data_provider``
internals; routes and schemas don't import yfinance / pandas
directly. That keeps the seam between "external market data" and
"app business logic" sharp.
"""

from __future__ import annotations

import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import timedelta
from typing import Iterable, Optional

import pandas as pd

_logger = logging.getLogger(__name__)

# Intraday quote cache: the daily-close path is 24h-file-cached (right for the
# risk math, stale for a live quote). For the /market/prices DISPLAY price we
# overlay a ~15-min-delayed intraday last price from free yfinance, with a tiny
# in-process TTL so a volatile-session refresh storm doesn't get us rate-limited.
_QUOTE_TTL_SECONDS = 90
_quote_cache: dict[str, tuple[float, dict[str, tuple[float, str]]]] = {}


def reset_quote_cache() -> None:
    """Test hook."""
    _quote_cache.clear()


def _intraday_quotes(tickers: list[str]) -> dict[str, tuple[float, str]]:
    """Best-effort intraday last price per ticker → ``{ticker: (price, as_of)}``.

    One batched 1-minute download; fail-soft to ``{}`` (off-hours, rate limit,
    delisted) so callers fall back to the daily close. Cached ~90s."""
    if not tickers:
        return {}
    key = ",".join(sorted(tickers))
    hit = _quote_cache.get(key)
    if hit is not None and hit[0] > time.monotonic():
        return hit[1]

    out: dict[str, tuple[float, str]] = {}
    try:
        import yfinance as yf

        raw = yf.download(
            tickers,
            period="1d",
            interval="1m",
            progress=False,
            threads=True,
            auto_adjust=False,
        )
        if raw is not None and not raw.empty and "Close" in raw.columns:
            close = raw["Close"]
            if isinstance(close, pd.Series):  # single ticker
                s = close.dropna()
                if not s.empty:
                    out[tickers[0]] = (
                        float(s.iloc[-1]),
                        pd.Timestamp(s.index[-1]).strftime("%Y-%m-%d"),
                    )
            else:  # multi-ticker → columns are tickers
                for col in close.columns:
                    s = close[col].dropna()
                    if not s.empty:
                        out[str(col)] = (
                            float(s.iloc[-1]),
                            pd.Timestamp(s.index[-1]).strftime("%Y-%m-%d"),
                        )
    except Exception as exc:  # pragma: no cover - network/shape variability
        _logger.warning("market_data.intraday_failed err=%s", type(exc).__name__)
        out = {}

    _quote_cache[key] = (time.monotonic() + _QUOTE_TTL_SECONDS, out)
    return out


# Ticker validation — uppercase letters / digits, a few common punctuation
# chars that show up in real symbols (BRK.B, ^TNX, CL=F, BTC-USD). Anything
# else is almost certainly bad input.
_TICKER_RE = re.compile(r"^[A-Z0-9.\^=\-]{1,20}$")

# Cap per-request work so a buggy client can't ask for 10_000 tickers.
MAX_TICKERS_PER_CALL = 50


# How many yfinance-missing tickers we'll try to backfill from Massive in one
# call. Massive Basic is 5 calls/min; each fallback ticker is one history call
# (then cached), so we cap and LOG the overflow rather than silently truncating.
_MAX_MASSIVE_FALLBACK = 5


@dataclass(frozen=True)
class LatestPrice:
    """One ticker's most recent observation."""

    ticker: str
    price: float
    as_of: str  # ISO date YYYY-MM-DD of the bar
    source: str = "yfinance"  # "yfinance" | "massive" — price provenance


def massive_fallback_tickers(by_ticker: dict) -> list[str]:
    """The (sorted) tickers a provenance ``by_ticker`` map served from Massive —
    the single source for the 'massive_fallback_used' field shared by the
    /market/prices, score, and report responses."""
    return sorted(t for t, s in by_ticker.items() if s == "massive")


def _normalise_tickers(tickers: Iterable[str]) -> list[str]:
    """Uppercase, dedupe, validate, sort.

    Sorting makes the underlying cache key stable across callers, and
    dedup keeps a careless ``?tickers=SPY,SPY,SPY`` from triggering
    three network calls under cache miss.
    """
    seen: set[str] = set()
    out: list[str] = []
    for raw in tickers:
        t = str(raw or "").strip().upper()
        if not t or not _TICKER_RE.match(t):
            raise ValueError(f"Invalid ticker: {raw!r}")
        if t in seen:
            continue
        seen.add(t)
        out.append(t)
    if not out:
        raise ValueError("At least one ticker is required.")
    if len(out) > MAX_TICKERS_PER_CALL:
        raise ValueError(f"Too many tickers ({len(out)}); cap is {MAX_TICKERS_PER_CALL}.")
    out.sort()
    return out


def _build_cache_provider():
    """Lazy import so a notebook can import this module without yfinance."""
    from data_provider import CachedDataProvider

    return CachedDataProvider()


def _fetch_one_history(cache_provider, ticker: str, start: str, end: str) -> Optional[pd.DataFrame]:
    """Fetch one ticker's price history through the cache. Returns
    None when yfinance has nothing for the symbol (delisted, typo)."""
    from . import metrics

    try:
        df = cache_provider.fetch_with_cache(ticker, start, end, data_type="prices")
        metrics.record_provider("yfinance", "ok" if df is not None and not df.empty else "empty")
        return df
    except Exception as exc:
        _logger.warning("market_data.fetch_failed ticker=%s err=%s", ticker, exc)
        metrics.record_provider("yfinance", "error")
        return None


def _bars_to_series(bars) -> Optional[pd.Series]:
    """Massive ``PriceBar`` list → a date-indexed close Series (best-effort)."""
    pairs = {}
    for b in bars or []:
        try:
            pairs[pd.Timestamp(b.date)] = float(b.close)
        except Exception:  # noqa: BLE001 - skip an unparseable bar, keep the rest
            continue
    if not pairs:
        return None
    return pd.Series(pairs).sort_index()


def _massive_fallback(missing: list[str], days: int, frames: dict, src_map: dict) -> None:
    """Backfill yfinance-missing tickers from Massive (fallback only). Mutates
    ``frames``/``src_map`` in place. Fail-soft: a dead Massive just leaves the
    ticker missing. Capped at ``_MAX_MASSIVE_FALLBACK`` calls; overflow logged."""
    try:
        from .providers import massive_provider as massive
    except Exception:  # noqa: BLE001 - provider import must never break pricing
        return
    if not missing or not massive.is_configured():
        return
    if len(missing) > _MAX_MASSIVE_FALLBACK:
        _logger.warning(
            "market_data.massive_fallback_capped requested=%d cap=%d dropped=%s",
            len(missing),
            _MAX_MASSIVE_FALLBACK,
            missing[_MAX_MASSIVE_FALLBACK:],
        )
    for t in missing[:_MAX_MASSIVE_FALLBACK]:
        try:
            res = massive.get_daily_history(t, days=days)
        except Exception as exc:  # noqa: BLE001 - provider should fail-soft; double-guard anyway
            _logger.warning(
                "market_data.massive_fallback_error ticker=%s err=%s", t, type(exc).__name__
            )
            continue
        if res.ok and res.data:
            series = _bars_to_series(res.data)
            if series is not None and not series.empty:
                frames[t] = series
                src_map[t] = "massive"


def get_price_history(
    tickers: Iterable[str],
    *,
    days: int = 365,
    cache_provider=None,
    provenance: Optional[dict] = None,
) -> pd.DataFrame:
    """Return a date-indexed DataFrame of adjusted close, one column
    per ticker.

    yfinance is the source; tickers it can't price are backfilled from Massive
    (fallback only) when ``MASSIVE_API_KEY`` is set. Pass a ``provenance`` dict
    to receive ``{"by_ticker": {tk: "yfinance"|"massive"}, "missing": [...]}``
    (the param is additive — existing callers are unaffected). We do NOT raise
    on partial coverage — most risk-engine math handles missing columns.
    """
    tk = _normalise_tickers(tickers)
    end = pd.Timestamp.today().normalize()
    start = end - timedelta(days=max(days, 30))
    start_s = start.strftime("%Y-%m-%d")
    end_s = end.strftime("%Y-%m-%d")

    provider = cache_provider or _build_cache_provider()

    frames: dict[str, pd.Series] = {}
    with ThreadPoolExecutor(max_workers=min(8, len(tk))) as pool:
        futures = {pool.submit(_fetch_one_history, provider, t, start_s, end_s): t for t in tk}
        for fut in as_completed(futures):
            t = futures[fut]
            df = fut.result()
            if df is None or df.empty:
                continue
            series = _extract_close_series(df)
            if series is not None and not series.empty:
                frames[t] = series

    # Provenance + Massive fallback for whatever yfinance couldn't price.
    src_map = {t: "yfinance" for t in frames}
    missing = [t for t in tk if t not in frames]
    _massive_fallback(missing, max(days, 30), frames, src_map)
    if provenance is not None:
        provenance["by_ticker"] = src_map
        provenance["missing"] = [t for t in tk if t not in frames]

    if not frames:
        return pd.DataFrame()
    return pd.DataFrame(frames).sort_index()


def _extract_close_series(df: pd.DataFrame) -> Optional[pd.Series]:
    """Pull the adjusted-close Series out of whatever shape yfinance
    handed back.

    Three shapes seen in the wild (yfinance keeps changing this):
      1. Single-index columns: ``Close``, ``High``, ``Low``, ``Open``.
         → ``df["Close"]`` returns a Series. Easy path.
      2. **MultiIndex columns** (current default for yf 0.2.x even on a
         single-ticker download): ``('Close', 'AA')``, ``('High', 'AA')``.
         → ``df["Close"]`` returns a DataFrame with one sub-column,
         NOT a Series; we extract that sub-column.
      3. Single unnamed column (very old or already-flattened cache
         entries): take the first column.
    """
    cols = df.columns
    # Path 1 or 2 — top-level "Close" present.
    if "Close" in cols:
        close = df["Close"]
        if isinstance(close, pd.DataFrame):
            # MultiIndex: ('Close', '<ticker>'). The sub-DataFrame has
            # exactly one column; collapse to that Series.
            if close.shape[1] == 0:
                return None
            return close.iloc[:, 0].dropna()
        return close.dropna()
    # Path 3 — pre-flattened.
    if df.shape[1] > 0:
        return df.iloc[:, 0].dropna()
    return None


def get_latest_prices(
    tickers: Iterable[str],
    *,
    cache_provider=None,
    provenance: Optional[dict] = None,
) -> list[LatestPrice]:
    """Return the most recent close + its date for each ticker.

    A ~15-min-delayed intraday last price is overlaid on top of the daily close
    (the 30-day file-cached window) so the DISPLAYED quote tracks the session;
    if the intraday fetch is unavailable (off-hours, rate-limited) we fall back
    to the daily close, so this never fails. Risk math still uses daily closes
    via ``get_price_history`` — only this display endpoint goes intraday.

    Each ``LatestPrice`` carries its ``source`` ("yfinance" | "massive"). A
    Massive-sourced (fallback) ticker keeps its EOD close — no intraday overlay,
    since Massive Basic has no live intraday. Pass ``provenance`` to also receive
    the by-ticker/missing summary.
    """
    inner_prov: dict = {}
    frame = get_price_history(
        tickers, days=30, cache_provider=cache_provider, provenance=inner_prov
    )
    src_by_ticker: dict = inner_prov.get("by_ticker", {})
    if provenance is not None:
        provenance.update(inner_prov)  # carries by_ticker + missing
    if frame.empty:
        return []

    # Intraday overlay only for yfinance tickers (Massive has no live intraday).
    yf_cols = [str(t) for t in frame.columns if src_by_ticker.get(str(t), "yfinance") == "yfinance"]
    intraday = _intraday_quotes(yf_cols)

    out: list[LatestPrice] = []
    for ticker in frame.columns:
        tk = str(ticker)
        source = src_by_ticker.get(tk, "yfinance")
        fresh = intraday.get(tk)
        if fresh is not None:
            out.append(LatestPrice(ticker=tk, price=fresh[0], as_of=fresh[1], source=source))
            continue
        series = frame[ticker].dropna()
        if series.empty:
            continue
        out.append(
            LatestPrice(
                ticker=tk,
                price=float(series.iloc[-1]),
                as_of=pd.Timestamp(series.index[-1]).strftime("%Y-%m-%d"),
                source=source,
            )
        )
    return out
