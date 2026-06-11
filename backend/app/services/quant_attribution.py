"""Performance attribution for the active portfolio.

Wraps the legacy ``performance_attribution.get_attribution_summary`` (free
numpy/scipy). Reuses the backtest service's active-holdings resolver +
market-value weights, and fetches the benchmark + factor ETFs alongside the
holdings so Brinson + factor regression actually have a benchmark to run
against. Heavy matrices (daily/monthly PnL) are dropped at the boundary.
"""

from __future__ import annotations

from ..core.responses import APIError, server_error, unprocessable
from .quant_backtest import _finite, _resolve_active_holdings

# Benchmark + the factor ETFs the legacy factor regression looks for.
_FACTORS = ["SPY", "QQQ", "GLD", "TLT", "IWM", "VTV"]
_BENCHMARK = "SPY"


def _mv_weights(holdings: dict, tickers: list[str], price_frame) -> dict[str, float]:
    """Market-value weights (shares × latest close, normalised to 1) read from
    the price frame we ALREADY fetched — so attribution needs only one price
    pull. Mirrors quant_backtest._static_weights' rule (drop unpriced tickers,
    raise 422 if nothing is usable), without a second 10-day fetch."""
    mvs: dict[str, float] = {}
    for tk in tickers:
        if tk not in price_frame.columns:
            continue
        closes = price_frame[tk].dropna()
        if closes.empty:
            continue
        shares = float((holdings.get(tk) or {}).get("shares") or 0.0)
        last_close = float(closes.iloc[-1])
        if shares > 0 and last_close > 0:
            mvs[tk] = shares * last_close
    total = sum(mvs.values())
    if total <= 0:
        raise APIError(
            status=422,
            code="no_priced_holdings",
            message="Could not price any holding (shares=0 or no quote).",
        )
    return {tk: v / total for tk, v in mvs.items()}


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

    from . import market_data

    # One fetch covers both the weights (latest close) and the returns matrix.
    all_tickers = sorted(set(tickers) | set(_FACTORS))
    try:
        price_frame = market_data.get_price_history(all_tickers, days=history_days)
    except Exception as exc:
        raise server_error("Market data fetch failed.", reason=type(exc).__name__) from exc
    if price_frame.empty:
        raise APIError(status=422, code="no_market_data", message="Could not fetch prices.")

    weights = _mv_weights(holdings, tickers, price_frame)  # raises 422 if unpriced

    try:
        import pandas as pd

        from performance_attribution import get_attribution_summary

        returns = price_frame.pct_change().dropna(how="all")
        w = pd.Series(weights, dtype=float)
        summary = get_attribution_summary(w, returns, benchmark_ticker=_BENCHMARK)
    except Exception as exc:
        raise server_error("Attribution computation failed.", reason=type(exc).__name__) from exc

    out = _serialize(summary)
    # Provenance: last price date + return observations behind the attribution.
    try:
        out["as_of"] = pd.Timestamp(price_frame.index[-1]).strftime("%Y-%m-%d")
        out["observations"] = int(len(returns))
    except Exception:  # noqa: BLE001 - provenance must never sink the payload
        pass
    return out
