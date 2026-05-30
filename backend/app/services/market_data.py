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
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import timedelta
from typing import Iterable, Optional

import pandas as pd

_logger = logging.getLogger(__name__)

# Ticker validation — uppercase letters / digits, a few common punctuation
# chars that show up in real symbols (BRK.B, ^TNX, CL=F, BTC-USD). Anything
# else is almost certainly bad input.
_TICKER_RE = re.compile(r"^[A-Z0-9.\^=\-]{1,20}$")

# Cap per-request work so a buggy client can't ask for 10_000 tickers.
MAX_TICKERS_PER_CALL = 50


@dataclass(frozen=True)
class LatestPrice:
    """One ticker's most recent observation."""

    ticker: str
    price: float
    as_of: str  # ISO date YYYY-MM-DD of the bar


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
    try:
        return cache_provider.fetch_with_cache(ticker, start, end, data_type="prices")
    except Exception as exc:
        _logger.warning("market_data.fetch_failed ticker=%s err=%s", ticker, exc)
        return None


def get_price_history(
    tickers: Iterable[str],
    *,
    days: int = 365,
    cache_provider=None,
) -> pd.DataFrame:
    """Return a date-indexed DataFrame of adjusted close, one column
    per ticker.

    Tickers that yfinance can't price are silently dropped. The
    caller can inspect ``frame.columns`` to see which symbols
    survived. We do NOT raise here on partial coverage — most
    risk-engine math handles missing columns gracefully.
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
) -> list[LatestPrice]:
    """Return the most recent close + its date for each ticker.

    Backed by the same history fetch (30-day window — enough to find
    the latest bar even across weekends + holidays) so a hot
    /market/prices request piggy-backs on the same file cache as
    /score_from_active.
    """
    frame = get_price_history(tickers, days=30, cache_provider=cache_provider)
    if frame.empty:
        return []
    out: list[LatestPrice] = []
    for ticker in frame.columns:
        series = frame[ticker].dropna()
        if series.empty:
            continue
        last_idx = series.index[-1]
        out.append(
            LatestPrice(
                ticker=str(ticker),
                price=float(series.iloc[-1]),
                as_of=pd.Timestamp(last_idx).strftime("%Y-%m-%d"),
            )
        )
    return out
