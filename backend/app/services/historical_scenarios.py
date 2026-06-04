"""Historical scenario replay — what the user's ACTUAL holdings would have done
through real market crises (not a synthetic shock).

For each episode we slice the holdings' real adjusted-close history over the
episode dates, weight by current market-value weights (renormalised over the
tickers that actually traded then — reported as ``coverage``), and compute the
portfolio's realised return, max drawdown, the S&P 500 over the same window, and
how long it took to claw back to the pre-episode level. Far more credible — and
visceral — than an abstract −30%.

All deterministic + free (yfinance via the shared cache). Raises the shared
422/500 envelope codes for the no-portfolio / no-data cases.
"""

from __future__ import annotations

import math
from typing import Optional

from ..core.responses import APIError, server_error
from .quant_backtest import _resolve_active_holdings

# (label, start, end). Dates bracket the peak→trough of each crisis.
_EPISODES: list[tuple[str, str, str]] = [
    ("COVID-19 crash", "2020-02-19", "2020-03-23"),
    ("2022 bear market", "2022-01-03", "2022-10-12"),
    ("2018 Q4 selloff", "2018-09-20", "2018-12-24"),
    ("Global Financial Crisis", "2007-10-09", "2009-03-09"),
]

_BENCH = "SPY"
# Cover the oldest episode (2007) plus headroom for the recovery search.
_HISTORY_DAYS = 6800


def _finite(v) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _mv_weights(holdings: dict, tickers: list[str], price_frame) -> dict[str, float]:
    """Latest-row market-value weights (shares × last close), normalised."""
    mvs: dict[str, float] = {}
    for tk in tickers:
        if tk not in price_frame.columns:
            continue
        closes = price_frame[tk].dropna()
        if closes.empty:
            continue
        shares = float((holdings.get(tk) or {}).get("shares") or 0.0)
        last = float(closes.iloc[-1])
        if shares > 0 and last > 0:
            mvs[tk] = shares * last
    total = sum(mvs.values())
    if total <= 0:
        raise APIError(
            status=422,
            code="no_priced_holdings",
            message="Could not price any holding (shares=0 or no quote).",
        )
    return {tk: v / total for tk, v in mvs.items()}


def _episode(price_frame, weights: dict[str, float], start: str, end: str) -> Optional[dict]:
    """Replay one episode on the priced holdings. None if no holding has data
    spanning the window."""
    import pandas as pd

    win = price_frame.loc[start:end]
    if win.empty or len(win) < 2:
        return None

    # Tickers that actually traded across this window (data at both ends).
    avail = [
        t
        for t in weights
        if t in win.columns and win[t].notna().iloc[0] and win[t].notna().iloc[-1]
    ]
    if not avail:
        return None
    w_total = sum(weights[t] for t in avail)
    if w_total <= 0:
        return None
    w = {t: weights[t] / w_total for t in avail}

    # Portfolio index over the window (normalised to 1 at the start).
    norm = win[avail].ffill().bfill()
    idx = (norm / norm.iloc[0]).mul(pd.Series(w)).sum(axis=1)
    if idx.empty:
        return None

    port_return = float(idx.iloc[-1] - 1.0)
    max_dd = float((idx / idx.cummax() - 1.0).min())

    market_return = None
    if _BENCH in win.columns:
        spy = win[_BENCH].dropna()
        if len(spy) >= 2:
            market_return = float(spy.iloc[-1] / spy.iloc[0] - 1.0)

    return {
        "portfolio_return": _finite(port_return),
        "market_return": _finite(market_return),
        "max_drawdown": _finite(max_dd),
        "coverage": _finite(w_total),
        "recovery_days": _recovery_days(price_frame, avail, w, start),
    }


def _recovery_days(price_frame, avail: list[str], w: dict[str, float], start: str) -> Optional[int]:
    """Trading days from the episode start until the portfolio first claws back
    to its pre-episode level. None if it hadn't recovered within our data."""
    import pandas as pd

    series = price_frame[avail].loc[start:]
    if series.empty:
        return None
    norm = series.ffill().bfill()
    idx = (norm / norm.iloc[0]).mul(pd.Series(w)).sum(axis=1)
    if idx.empty:
        return None
    start_level = float(idx.iloc[0])
    trough_pos = int(idx.values.argmin())
    after = idx.iloc[trough_pos:]
    regained = after[after >= start_level]
    if regained.empty:
        return None  # not recovered within available data
    recover_pos = idx.index.get_loc(regained.index[0])
    return int(recover_pos)  # trading days from episode start


def run_historical_scenarios(user) -> dict:
    """Replay all episodes on the caller's active portfolio."""
    holdings = _resolve_active_holdings(user)
    tickers = sorted(holdings.keys())

    from . import market_data

    fetch = sorted(set(tickers) | {_BENCH})
    try:
        price_frame = market_data.get_price_history(fetch, days=_HISTORY_DAYS)
    except Exception as exc:
        raise server_error("Market data fetch failed.", reason=type(exc).__name__) from exc
    if price_frame.empty:
        raise APIError(status=422, code="no_market_data", message="Could not fetch prices.")

    weights = _mv_weights(holdings, tickers, price_frame)

    scenarios = []
    for label, start, end in _EPISODES:
        try:
            ep = _episode(price_frame, weights, start, end)
        except Exception:  # noqa: BLE001 - one bad episode shouldn't sink the rest
            ep = None
        if ep is None:
            continue
        scenarios.append({"label": label, "start": start, "end": end, **ep})

    return {"scenarios": scenarios}
