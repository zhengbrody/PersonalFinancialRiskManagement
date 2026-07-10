"""Anonymous portfolio risk check — deterministic, stateless, limited scope.

Deliberately independent of the authed active-portfolio path: no auth, no
Supabase, no engine session. Computes ONLY the public result set
(concentration, annual volatility, 1-day historical VaR/CVaR, simple
beta-scaled stress rows, provenance). No AI, no recommendations.

Privacy: the user payload is NEVER persisted or cached — market data flows
through the existing per-ticker price cache (keyed by ticker only), and the
computation happens entirely in-request. Logs carry counts, never tickers.
"""

from __future__ import annotations

import logging
import math
from typing import Iterable

import numpy as np

_log = logging.getLogger(__name__)

_STRESS_SHOCKS = (-0.05, -0.10, -0.20)
_HISTORY_DAYS = 365
_BENCHMARK = "SPY"


class NoPricedHoldings(Exception):
    """None of the submitted tickers could be priced."""


def _finite(value) -> float | None:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def run_check(holdings: Iterable) -> dict:
    """holdings: validated PublicHolding models (ticker, shares)."""
    from . import market_data

    rows = list(holdings)
    tickers = [h.ticker for h in rows]
    shares = {h.ticker: float(h.shares) for h in rows}

    provenance: dict = {}
    fetch = sorted(set(tickers) | {_BENCHMARK})
    frame = market_data.get_price_history(fetch, days=_HISTORY_DAYS, provenance=provenance)

    priced = [t for t in tickers if t in frame.columns and not frame[t].dropna().empty]
    missing = [t for t in tickers if t not in priced]
    if not priced:
        raise NoPricedHoldings("None of these tickers could be priced from market data.")

    closes = frame[priced].ffill().dropna(how="all")
    latest = closes.iloc[-1]
    market_values = {t: shares[t] * float(latest[t]) for t in priced if _finite(latest[t])}
    total = sum(market_values.values())
    if total <= 0:
        raise NoPricedHoldings("Priced holdings have no positive market value.")
    weights = {t: mv / total for t, mv in market_values.items()}

    # Concentration.
    top_ticker = max(weights, key=weights.get)
    hhi = sum(w * w for w in weights.values())
    concentration = {
        "top_ticker": top_ticker,
        "top_weight": round(weights[top_ticker], 4),
        "hhi": round(hhi, 4),
        "effective_holdings": round(1.0 / hhi, 2) if hhi > 0 else None,
        "weights": {t: round(w, 4) for t, w in weights.items()},
    }

    # Portfolio daily returns (fixed current weights over the joint window).
    returns = closes.pct_change().dropna(how="any")
    metrics: dict = {"total_value": round(total, 2)}
    var_95 = cvar_95 = None
    if len(returns) >= 30:
        w = np.array([weights[t] for t in returns.columns])
        port = returns.to_numpy() @ w
        ann_vol = _finite(np.std(port, ddof=1) * math.sqrt(252))
        q05 = float(np.quantile(port, 0.05))
        var_95 = _finite(-q05)
        tail = port[port <= q05]
        cvar_95 = _finite(-float(np.mean(tail))) if tail.size else None
        metrics.update(
            {
                "annual_volatility": round(ann_vol, 4) if ann_vol is not None else None,
                "var_95_1d": round(var_95, 4) if var_95 is not None else None,
                "cvar_95_1d": round(cvar_95, 4) if cvar_95 is not None else None,
            }
        )

    # Beta vs the market benchmark (for the simple stress rows).
    beta = None
    if _BENCHMARK in frame.columns and len(returns) >= 30:
        bench = frame[_BENCHMARK].ffill().pct_change().reindex(returns.index).dropna()
        if len(bench) >= 30:
            w = np.array([weights[t] for t in returns.columns])
            port_series = (returns.loc[bench.index].to_numpy() @ w).ravel()
            bvar = float(np.var(bench.to_numpy(), ddof=1))
            if bvar > 0:
                beta = _finite(float(np.cov(port_series, bench.to_numpy(), ddof=1)[0, 1]) / bvar)
    metrics["beta_to_market"] = round(beta, 2) if beta is not None else None

    stress = []
    for shock in _STRESS_SHOCKS:
        impact = beta * shock if beta is not None else None
        stress.append(
            {
                "market_shock_pct": shock,
                "est_portfolio_impact_pct": round(impact, 4) if impact is not None else None,
                "est_portfolio_impact_usd": (
                    round(total * impact, 2) if impact is not None else None
                ),
            }
        )

    by_ticker = (provenance.get("by_ticker") or {}) if isinstance(provenance, dict) else {}
    result = {
        "concentration": concentration,
        "metrics": metrics,
        "stress": stress,
        "provenance": {
            "as_of": str(closes.index[-1].date()) if len(closes) else None,
            "observations": int(len(returns)),
            "priced": priced,
            "missing": missing,
            "sources": {t: by_ticker.get(t, "yfinance") for t in priced},
        },
    }
    _log.info("public_risk_check.ok holdings=%d priced=%d", len(rows), len(priced))
    return result
