"""Portfolio-level math: Sharpe, margin, frontier, compliance, drawdown.

All functions are pure. The orchestrating RiskEngine class in risk_engine.py
delegates to these.
"""
from __future__ import annotations

from typing import Dict, List, Optional

import numpy as np
import pandas as pd
from scipy.optimize import minimize

from .constants import DEFAULT_RISK_LIMITS, TRADING_DAYS


def sharpe_ratio(annual_ret: float, annual_vol: float, risk_free: float) -> float:
    """Annualized Sharpe. Returns 0 when vol is non-positive (defensive)."""
    return (annual_ret - risk_free) / annual_vol if annual_vol > 0 else 0.0


def margin_call_distance(
    total_long: float,
    margin_loan: float,
    maintenance_ratio: float = 0.25,
) -> dict:
    """Margin-call buffer math.

    Returns a dict with leverage, distance-to-call %, the portfolio value
    that would trigger the call, and a "num 10 % limit downs to wipe out"
    rough indicator. No I/O, no rounding to ints — caller decides.
    """
    if margin_loan <= 0:
        return {
            "has_margin": False,
            "leverage": 1.0,
            "distance_to_call_pct": float("inf"),
            "margin_call_portfolio_value": 0.0,
            "current_equity_ratio": 1.0,
            "maintenance_ratio": maintenance_ratio,
            "buffer_dollars": total_long,
        }
    net_equity = total_long - margin_loan
    leverage = total_long / net_equity if net_equity > 0 else float("inf")
    equity_ratio = net_equity / total_long if total_long > 0 else 0.0
    call_value = margin_loan / (1 - maintenance_ratio)
    distance_pct = (total_long - call_value) / total_long if total_long > 0 else 0.0
    buffer_dollars = total_long - call_value
    return {
        "has_margin": True,
        "leverage": leverage,
        "distance_to_call_pct": distance_pct,
        "margin_call_portfolio_value": call_value,
        "current_equity_ratio": equity_ratio,
        "maintenance_ratio": maintenance_ratio,
        "buffer_dollars": buffer_dollars,
        "num_limit_downs": distance_pct / 0.10 if distance_pct > 0 else 0,
    }


def efficient_frontier(
    returns: pd.DataFrame,
    risk_free: float,
    n_points: int = 50,
) -> dict:
    """Markowitz mean-variance frontier with min-var and max-Sharpe pinned.

    Pure scipy.optimize. Slow (~1 s for 10 assets, 50 points) — caller
    is expected to cache.
    """
    mean_ret = returns.mean().values * TRADING_DAYS
    cov_ann = returns.cov().values * TRADING_DAYS
    n = len(mean_ret)
    tickers = list(returns.columns)
    bounds = tuple((0.0, 1.0) for _ in range(n))
    constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1.0}]

    def port_vol(w):
        return float(np.sqrt(w @ cov_ann @ w))

    def neg_sharpe(w):
        ret = w @ mean_ret
        vol = port_vol(w)
        return -(ret - risk_free) / vol if vol > 1e-10 else 1e10

    w0 = np.ones(n) / n
    res_minvar = minimize(
        port_vol, w0, bounds=bounds, constraints=constraints,
        method="SLSQP", options={"maxiter": 1000},
    )
    w_minvar = res_minvar.x
    res_maxsharpe = minimize(
        neg_sharpe, w0, bounds=bounds, constraints=constraints,
        method="SLSQP", options={"maxiter": 1000},
    )
    w_maxsharpe = res_maxsharpe.x

    min_ret = float(w_minvar @ mean_ret)
    max_ret = float(np.max(mean_ret) * 1.1)
    target_rets = np.linspace(min_ret, max_ret, n_points)
    frontier_vols, frontier_rets, frontier_weights = [], [], []
    for target in target_rets:
        cons = [
            {"type": "eq", "fun": lambda w: np.sum(w) - 1.0},
            {"type": "eq", "fun": lambda w, t=target: w @ mean_ret - t},
        ]
        res = minimize(
            port_vol, w0, bounds=bounds, constraints=cons,
            method="SLSQP", options={"maxiter": 500},
        )
        if res.success:
            frontier_vols.append(port_vol(res.x))
            frontier_rets.append(float(res.x @ mean_ret))
            frontier_weights.append(res.x.tolist())

    return {
        "frontier_vols": frontier_vols,
        "frontier_rets": frontier_rets,
        "frontier_weights": frontier_weights,
        "max_sharpe_weights": dict(zip(tickers, w_maxsharpe.tolist())),
        "max_sharpe_ret": float(w_maxsharpe @ mean_ret),
        "max_sharpe_vol": port_vol(w_maxsharpe),
        "max_sharpe_ratio": float(-neg_sharpe(w_maxsharpe)),
        "min_var_weights": dict(zip(tickers, w_minvar.tolist())),
        "min_var_ret": float(w_minvar @ mean_ret),
        "min_var_vol": port_vol(w_minvar),
        "tickers": tickers,
    }


def check_compliance(
    proposed_weights: Dict[str, float],
    sector_map: Dict[str, str],
    limits: Optional[Dict[str, float]] = None,
) -> List[dict]:
    """Return a list of limit violations. Floating-point tolerance applied
    so 0.6000000000000001 doesn't trip a 0.6 limit (callers can't act on it).
    """
    rules = limits or DEFAULT_RISK_LIMITS
    tol = 1e-6
    violations: List[dict] = []

    max_stock = rules.get("max_single_stock_weight", 0.15)
    for tk, w in proposed_weights.items():
        if w > max_stock + tol:
            violations.append({
                "rule": "max_single_stock_weight",
                "limit": max_stock,
                "actual": w,
                "ticker": tk,
                "severity": "hard",
            })

    max_sector = rules.get("max_sector_weight", 0.30)
    sector_weights: Dict[str, float] = {}
    for tk, w in proposed_weights.items():
        s = sector_map.get(tk, "Other")
        sector_weights[s] = sector_weights.get(s, 0.0) + w
    for sector, w in sector_weights.items():
        if w > max_sector + tol:
            violations.append({
                "rule": "max_sector_weight",
                "limit": max_sector,
                "actual": w,
                "sector": sector,
                "severity": "hard",
            })

    return violations


def adjust_for_compliance(
    proposed_weights: Dict[str, float],
    sector_map: Dict[str, str],
    limits: Optional[Dict[str, float]] = None,
) -> Dict[str, float]:
    """Project weights onto the feasible set defined by limits.

    Algorithm: alternating projection (clip per-stock, scale per-sector,
    redistribute slack to non-capped weights, repeat until stable).

    By design we do NOT renormalize the result back to sum=1.0 — if the
    feasible region is tighter than 1.0, the residual is implicit cash.
    Re-normalizing would re-violate the caps we just enforced.
    """
    rules = limits or DEFAULT_RISK_LIMITS
    max_stock = rules.get("max_single_stock_weight", 0.15)
    max_sector = rules.get("max_sector_weight", 0.30)
    tol = 1e-9

    adjusted = dict(proposed_weights)

    for _ in range(20):
        changed = False

        capped, uncapped = [], []
        for tk, w in adjusted.items():
            if w > max_stock + tol:
                adjusted[tk] = max_stock
                capped.append(tk)
                changed = True
            else:
                uncapped.append(tk)

        s = sum(adjusted.values())
        slack = 1.0 - s
        if slack > tol and uncapped:
            uncap_sum = sum(adjusted[tk] for tk in uncapped)
            if uncap_sum > 0:
                for tk in uncapped:
                    addable = max_stock - adjusted[tk]
                    if addable <= 0:
                        continue
                    share = slack * (adjusted[tk] / uncap_sum)
                    grant = min(share, addable)
                    adjusted[tk] += grant
                    changed = True

        sector_w: Dict[str, float] = {}
        sector_tickers: Dict[str, list] = {}
        for tk, w in adjusted.items():
            sec = sector_map.get(tk, "Other")
            sector_w[sec] = sector_w.get(sec, 0.0) + w
            sector_tickers.setdefault(sec, []).append(tk)
        for sec, sw in sector_w.items():
            if sw > max_sector + tol:
                scale = max_sector / sw
                for tk in sector_tickers[sec]:
                    adjusted[tk] *= scale
                changed = True

        violations = check_compliance(adjusted, sector_map, limits)
        if not violations and not changed:
            break

    for tk in list(adjusted):
        adjusted[tk] = max(0.0, min(adjusted[tk], max_stock))

    return adjusted


def rolling_correlation_with_portfolio(
    returns: pd.DataFrame,
    weights: np.ndarray,
    window: int = 60,
) -> pd.DataFrame:
    """Rolling correlation of each asset against the portfolio time series."""
    port_ret = returns.dot(weights)
    return pd.DataFrame(
        {col: returns[col].rolling(window).corr(port_ret) for col in returns.columns}
    )


def drawdown_statistics(dd_series: pd.Series) -> dict:
    """Episode-level drawdown stats from a (negative) drawdown series.

    Episodes are runs where dd < -0.005. Returns count, mean/median/max
    duration in days, fraction of time underwater, and current-episode
    duration if mid-episode.
    """
    is_dd = dd_series < -0.005
    episodes = []
    in_episode = False
    ep_start_idx = None
    for i, val in enumerate(is_dd.values):
        if val and not in_episode:
            in_episode = True
            ep_start_idx = i
        elif not val and in_episode:
            in_episode = False
            episodes.append(i - ep_start_idx)
    current_duration = None
    if in_episode and ep_start_idx is not None:
        current_duration = len(is_dd) - ep_start_idx
    return {
        "num_episodes": len(episodes),
        "avg_episode_days": round(float(np.mean(episodes)), 1) if episodes else 0,
        "max_episode_days": max(episodes) if episodes else 0,
        "median_episode_days": round(float(np.median(episodes)), 1) if episodes else 0,
        "pct_time_underwater": round(float(is_dd.mean()) * 100, 1),
        "is_currently_underwater": bool(in_episode),
        "current_episode_days": current_duration,
        "episode_durations": episodes,
    }
