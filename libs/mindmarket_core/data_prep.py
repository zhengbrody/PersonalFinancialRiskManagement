"""Pure data-quality transformations.

These were `@staticmethod`s on `DataProvider` in data_provider.py — extracted
here so Lambda services can validate price data without importing yfinance
or the full DataProvider class.

Logging is callers' responsibility; we expose a `logger` parameter where it
helps, otherwise return values include enough context to log upstream.
"""
from __future__ import annotations

from typing import List, Tuple

import pandas as pd


# Common non-USD ticker suffix → currency name (informational, not authoritative)
_FOREIGN_SUFFIX_TO_CURRENCY = {
    ".L": "GBP (London)",
    ".T": "JPY (Tokyo)",
    ".TO": "CAD (Toronto)",
    ".HK": "HKD (Hong Kong)",
    ".SS": "CNY (Shanghai)",
    ".SZ": "CNY (Shenzhen)",
    ".AX": "AUD (Australia)",
    ".PA": "EUR (Paris)",
    ".DE": "EUR (Germany)",
}


def detect_currency_mixing(tickers: List[str]) -> Tuple[bool, str]:
    """Spot non-USD tickers in the basket. Mixing currencies in a single
    weight vector means VaR will be wrong (USD vol vs. local-currency vol).

    Returns `(has_mixing, warning_message)`. Caller decides whether to warn,
    block, or just proceed.
    """
    detected: dict[str, str] = {}
    for ticker in tickers:
        is_foreign = False
        for suffix, currency in _FOREIGN_SUFFIX_TO_CURRENCY.items():
            if ticker.endswith(suffix):
                detected[ticker] = currency
                is_foreign = True
                break
        if not is_foreign:
            detected[ticker] = "USD"

    unique = set(detected.values())
    if len(unique) > 1:
        joined = ", ".join(f"{t}({c})" for t, c in detected.items())
        return True, f"Mixed currencies detected: {joined}. VaR may be inaccurate."
    return False, ""


def winsorize_returns(
    returns: pd.Series,
    lower_pct: float = 0.01,
    upper_pct: float = 0.99,
) -> pd.Series:
    """Clip a return series to its 1st and 99th percentiles by default.

    Skips winsorization on series with fewer than 10 observations (would
    over-clip). Returns the cleaned series; caller can compare to the
    input to count clipped observations.
    """
    if len(returns) < 10:
        return returns

    valid = returns.dropna()
    if len(valid) == 0:
        return returns

    lower = valid.quantile(lower_pct)
    upper = valid.quantile(upper_pct)
    return returns.clip(lower=lower, upper=upper)


def detect_gaps(
    data: pd.Series,
    max_gap_days: int = 5,
) -> List[Tuple[pd.Timestamp, pd.Timestamp, int]]:
    """Find runs of NaN longer than `max_gap_days`. Returns
    `[(start, end, length), ...]` for each gap.

    Returns empty list if the series doesn't have an inferable frequency
    (we can't reason about "missing days" without one).
    """
    if data.index.freq is None:
        try:
            inferred_freq = pd.infer_freq(data.index[:20])
            if inferred_freq is None:
                return []
        except Exception:
            return []

    missing_mask = data.isnull()
    gaps: List[Tuple[pd.Timestamp, pd.Timestamp, int]] = []
    in_gap = False
    gap_start = None
    gap_length = 0

    for date, is_missing in missing_mask.items():
        if is_missing:
            if not in_gap:
                gap_start = date
                gap_length = 1
                in_gap = True
            else:
                gap_length += 1
        else:
            if in_gap and gap_length > max_gap_days:
                gaps.append((gap_start, date, gap_length))
            in_gap = False
            gap_length = 0

    return gaps


def smart_fill_gaps(data: pd.Series, method: str = "auto") -> pd.Series:
    """Fill NaN gaps. ``auto`` interpolates short gaps (<= 3 obs) and
    forward-fills longer ones — usually the right tradeoff for daily
    OHLCV data where short missings are bad ticks but long missings
    are real (delisting, halt, weekend run).
    """
    if data.isnull().sum() == 0:
        return data

    if method == "ffill":
        return data.ffill()
    if method == "interpolate":
        return data.interpolate(method="linear", limit_direction="both")
    if method == "auto":
        filled = data.copy()
        filled = filled.ffill()
        missing_runs = (
            filled.isnull().astype(int)
            .groupby(filled.notnull().astype(int).cumsum())
            .cumsum()
        )
        small_gaps = missing_runs <= 3
        filled[small_gaps] = data[small_gaps].interpolate(method="linear")
        return filled.ffill().bfill()

    raise ValueError(f"Unknown fill method: {method}")
