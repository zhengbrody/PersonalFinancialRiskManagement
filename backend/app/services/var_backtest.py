"""VaR backtest — does the model's Value-at-Risk actually hold up?

We build the active portfolio's daily return series over the trailing window,
take a Gaussian (parametric) 1-day VaR, and COUNT how many days the realised
loss actually breached it vs how many a normal model predicts (~5% / ~1%).
Markets have fatter tails than a normal, so real breaches usually exceed the
prediction — surfacing that is the credibility move ("your VaR was breached N
times; a normal model expected ~E"). We also return the empirical return
distribution (histogram) so the page can show the shape + where VaR sits.

Deterministic + free. Raises the shared 422/500 envelope codes.
"""

from __future__ import annotations

import math
from typing import Optional

from ..core.responses import APIError, server_error, unprocessable
from .quant_backtest import _resolve_active_holdings

# z-scores for one-tailed Gaussian VaR.
_Z95 = 1.645
_Z99 = 2.326
_HISTORY_DAYS = 550  # ~1.5y of trading days
_BINS = 25


def _finite(v) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _mv_weights(holdings: dict, tickers: list[str], price_frame) -> dict[str, float]:
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


def run_var_backtest(user) -> dict:
    holdings = _resolve_active_holdings(user)
    tickers = sorted(holdings.keys())

    from . import market_data

    try:
        price_frame = market_data.get_price_history(tickers, days=_HISTORY_DAYS)
    except Exception as exc:
        raise server_error("Market data fetch failed.", reason=type(exc).__name__) from exc
    if price_frame.empty:
        raise APIError(status=422, code="no_market_data", message="Could not fetch prices.")

    import numpy as np
    import pandas as pd

    weights = _mv_weights(holdings, tickers, price_frame)
    avail = [t for t in weights if t in price_frame.columns]
    w = pd.Series({t: weights[t] for t in avail})
    w = w / w.sum()

    rets = price_frame[avail].pct_change().dropna(how="any")
    port = rets.mul(w, axis=1).sum(axis=1)
    port = port.replace([np.inf, -np.inf], np.nan).dropna()
    n = int(len(port))
    if n < 60:
        raise unprocessable("Need more price history to backtest VaR (≥60 days).")

    mu = float(port.mean())
    sigma = float(port.std(ddof=1))
    # Gaussian 1-day VaR as a positive loss fraction.
    var_95 = max(0.0, -(mu - _Z95 * sigma))
    var_99 = max(0.0, -(mu - _Z99 * sigma))

    losses = -port  # positive = loss
    breaches_95 = int((losses > var_95).sum())
    breaches_99 = int((losses > var_99).sum())

    # Empirical (historical) VaR for comparison.
    hist_var_95 = float(-np.quantile(port.values, 0.05))
    hist_var_99 = float(-np.quantile(port.values, 0.01))

    counts, edges = np.histogram(port.values, bins=_BINS)
    histogram = [
        {"x": _finite((edges[i] + edges[i + 1]) / 2.0), "count": int(counts[i])}
        for i in range(len(counts))
    ]

    return {
        "n_days": n,
        "mean_daily": _finite(mu),
        "vol_daily": _finite(sigma),
        "var_95": _finite(var_95),
        "var_99": _finite(var_99),
        "hist_var_95": _finite(hist_var_95),
        "hist_var_99": _finite(hist_var_99),
        "breaches_95": breaches_95,
        "expected_95": _finite(0.05 * n),
        "breaches_99": breaches_99,
        "expected_99": _finite(0.01 * n),
        "worst_day": _finite(float(losses.max())),
        "histogram": histogram,
    }
