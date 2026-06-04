"""Benchmark reference stats — annualized return / volatility / Sharpe / max
drawdown for the S&P 500 (SPY) and a classic 60/40 (SPY/AGG) blend, over the
same trailing window the score/report use.

This is the "vs what?" context that turns a lone portfolio number into an
analysis. Free (yfinance via the shared price cache), fail-soft, short TTL.
"""

from __future__ import annotations

import math
import time
from typing import Optional

_CACHE_TTL_SECONDS = 6 * 60 * 60
_cache: dict[str, tuple[float, dict]] = {}

_TRADING_DAYS = 252


def reset_cache() -> None:
    _cache.clear()


def _finite(v) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _stats(name: str, daily_returns, risk_free: float) -> Optional[dict]:
    """Annualized stats from a daily-returns Series. None if too short."""
    r = daily_returns.dropna()
    if len(r) < 30:
        return None
    annual_return = float(r.mean() * _TRADING_DAYS)
    annual_vol = float(r.std(ddof=1) * math.sqrt(_TRADING_DAYS))
    sharpe = (annual_return - risk_free) / annual_vol if annual_vol > 0 else None
    curve = (1.0 + r).cumprod()
    max_dd = float((curve / curve.cummax() - 1.0).min())
    return {
        "name": name,
        "annual_return": _finite(annual_return),
        "annual_volatility": _finite(annual_vol),
        "sharpe_ratio": _finite(sharpe),
        "max_drawdown": _finite(max_dd),
    }


def get_benchmarks(*, days: int = 365, risk_free: float = 0.045) -> dict:
    """``{as_of, benchmarks: [{name, annual_return, annual_volatility,
    sharpe_ratio, max_drawdown}]}`` for SPY + a 60/40 blend. Cached, fail-soft
    to an empty list."""
    key = f"bm:{days}:{risk_free}"
    hit = _cache.get(key)
    if hit is not None and hit[0] > time.monotonic():
        return hit[1]

    out: dict = {"as_of": None, "benchmarks": []}
    try:
        from . import market_data

        frame = market_data.get_price_history(["SPY", "AGG"], days=days)
        if not frame.empty:
            out["as_of"] = str(frame.index[-1].date()) if hasattr(frame.index[-1], "date") else None
            rets = frame.pct_change()
            if "SPY" in rets.columns:
                spy = _stats("S&P 500 (SPY)", rets["SPY"], risk_free)
                if spy:
                    out["benchmarks"].append(spy)
            if "SPY" in rets.columns and "AGG" in rets.columns:
                blend = 0.6 * rets["SPY"] + 0.4 * rets["AGG"]
                b6040 = _stats("Balanced 60/40", blend, risk_free)
                if b6040:
                    out["benchmarks"].append(b6040)
    except Exception:  # noqa: BLE001 - never block a page on the benchmark context
        out = {"as_of": None, "benchmarks": []}

    _cache[key] = (time.monotonic() + _CACHE_TTL_SECONDS, out)
    return out
