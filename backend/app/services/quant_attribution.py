"""Performance attribution for the active portfolio.

Wraps the legacy ``performance_attribution.get_attribution_summary`` (free
numpy/scipy). Reuses the backtest service's active-holdings resolver +
market-value weights, and fetches the benchmark + factor ETFs alongside the
holdings so Brinson + factor regression actually have a benchmark to run
against. Heavy matrices (daily/monthly PnL) are dropped at the boundary.
"""

from __future__ import annotations

import logging
from typing import Optional

from ..core.responses import APIError, server_error, unprocessable
from .quant_backtest import _resolve_active_holdings, _static_weights

_log = logging.getLogger(__name__)

# Benchmark + the factor ETFs the legacy factor regression looks for.
_FACTORS = ["SPY", "QQQ", "GLD", "TLT", "IWM", "VTV"]
_BENCHMARK = "SPY"


def _finite(v) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    import math

    return f if math.isfinite(f) else None


def _serialize(summary: dict) -> dict:
    brinson = summary.get("brinson") or None
    factor = summary.get("factor") or None

    brinson_out = None
    if isinstance(brinson, dict):
        sector_rows = []
        sd = brinson.get("sector_detail")
        try:
            records = sd.to_dict("records") if sd is not None and not sd.empty else []
        except Exception:  # noqa: BLE001 - not a DataFrame
            records = []
        for r in records:
            sector_rows.append(
                {
                    "sector": str(r.get("sector", "")),
                    "weight_diff": _finite(r.get("weight_diff")),
                    "allocation_effect": _finite(r.get("allocation_effect")),
                    "selection_effect": _finite(r.get("selection_effect")),
                    "total_effect": _finite(r.get("total_effect")),
                }
            )
        brinson_out = {
            "total_active_return": _finite(brinson.get("total_active_return")),
            "allocation_effect": _finite(brinson.get("allocation_effect")),
            "selection_effect": _finite(brinson.get("selection_effect")),
            "interaction_effect": _finite(brinson.get("interaction_effect")),
            "sector_detail": sector_rows,
        }

    factor_out = None
    if isinstance(factor, dict):
        betas = factor.get("factor_betas") or {}
        contribs = factor.get("factor_contributions") or {}
        factor_out = {
            "alpha": _finite(factor.get("alpha")),
            "r_squared": _finite(factor.get("r_squared")),
            "residual_return": _finite(factor.get("residual_return")),
            "factor_betas": {str(k): _finite(v) for k, v in betas.items()},
            "factor_contributions": {str(k): _finite(v) for k, v in contribs.items()},
        }

    return {
        "tracking_error": _finite(summary.get("tracking_error")),
        "information_ratio": _finite(summary.get("information_ratio")),
        "hit_ratio": _finite(summary.get("hit_ratio")),
        "active_return_annual": _finite(summary.get("active_return_annual")),
        "brinson": brinson_out,
        "factor": factor_out,
    }


def run_attribution(user, *, history_days: int = 730) -> dict:
    """Resolve the active portfolio, fetch holdings + benchmark/factor returns,
    and return a serialized attribution summary. Raises the shared 422/500
    envelope codes."""
    holdings = _resolve_active_holdings(user)
    tickers = sorted(holdings.keys())
    if len(tickers) < 2:
        raise unprocessable("Need at least 2 holdings to attribute performance.")

    weights = _static_weights(holdings, tickers)  # mv weights, raises 422 if unpriced

    from . import market_data

    all_tickers = sorted(set(tickers) | set(_FACTORS))
    try:
        price_frame = market_data.get_price_history(all_tickers, days=history_days)
    except Exception as exc:
        raise server_error("Market data fetch failed.", reason=type(exc).__name__) from exc
    if price_frame.empty:
        raise APIError(status=422, code="no_market_data", message="Could not fetch prices.")

    try:
        import pandas as pd

        from performance_attribution import get_attribution_summary

        returns = price_frame.pct_change().dropna(how="all")
        w = pd.Series(weights, dtype=float)
        summary = get_attribution_summary(w, returns, benchmark_ticker=_BENCHMARK)
    except Exception as exc:
        raise server_error("Attribution computation failed.", reason=type(exc).__name__) from exc

    return _serialize(summary)
