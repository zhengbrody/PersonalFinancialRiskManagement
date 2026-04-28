"""Pure VaR / EWMA / Monte-Carlo math.

Every function takes numpy/pandas in and returns numpy/pandas out.
None of them touch I/O, logging, or st.session_state.

Adapted from risk_engine.RiskEngine without behavioral changes — the
existing class delegates here so Streamlit output is byte-identical.
"""
from __future__ import annotations

from typing import Iterable

import numpy as np
import pandas as pd

from .constants import EWMA_LAMBDA, TRADING_DAYS


def ewma_covariance(
    returns: pd.DataFrame,
    lam: float = EWMA_LAMBDA,
) -> np.ndarray:
    """RiskMetrics-style EWMA covariance estimate (daily scale).

    Returns an `n_assets x n_assets` covariance matrix. Caller must scale
    to annual via `* TRADING_DAYS` if that's the unit they want.

    Edge case: fewer than 2 observations returns an identity matrix to
    keep downstream Cholesky from blowing up.
    """
    data = returns.values
    T, n = data.shape
    if T < 2:
        return np.eye(n)
    cov = np.cov(data.T)
    if cov.ndim < 2:
        cov = cov.reshape(1, 1)
    for t in range(1, T):
        r = data[t].reshape(-1, 1)
        cov = lam * cov + (1 - lam) * (r @ r.T)
    return cov


def monte_carlo_returns(
    returns: pd.DataFrame,
    weights: np.ndarray,
    cov_daily: np.ndarray,
    n_simulations: int = 10_000,
    horizon_days: int = 21,
    seed: int = 42,
) -> np.ndarray:
    """Vectorized Monte-Carlo of compounded portfolio returns.

    Returns a 1D array of length `n_simulations` with each entry the
    cumulative return over `horizon_days` business days. Use:

        var_95 = -np.percentile(out, 5)
        cvar_95 = -out[out <= np.percentile(out, 5)].mean()

    If `cov_daily` isn't positive-definite (rounding errors near singular
    matrices), we add a tiny ridge before Cholesky. Daily returns are
    clipped to [-99 %, +1000 %] to prevent overflow on pathological draws.
    """
    mean_daily = returns.mean().values
    n_assets = len(mean_daily)

    try:
        L = np.linalg.cholesky(cov_daily)
    except np.linalg.LinAlgError:
        cov_daily = cov_daily + np.eye(n_assets) * 1e-8
        L = np.linalg.cholesky(cov_daily)

    rng = np.random.default_rng(seed)
    Z = rng.standard_normal(size=(n_simulations, horizon_days, n_assets))
    daily_rets = mean_daily[None, None, :] + (Z @ L.T)
    portfolio_daily = daily_rets @ weights
    portfolio_daily = np.clip(portfolio_daily, -0.99, 10.0)
    return np.prod(1 + portfolio_daily, axis=1) - 1


def percentile_var_cvar(
    portfolio_returns: np.ndarray,
    confidence: float = 0.95,
) -> tuple[float, float]:
    """Returns `(VaR, CVaR)` as positive losses (i.e. 0.05 == 5 % loss)."""
    pct = (1.0 - confidence) * 100.0
    var = -float(np.percentile(portfolio_returns, pct))
    tail = portfolio_returns[portfolio_returns <= np.percentile(portfolio_returns, pct)]
    cvar = -float(tail.mean()) if tail.size > 0 else var
    return var, cvar


def component_var(
    cov_daily: np.ndarray,
    weights: np.ndarray,
    columns: Iterable[str],
) -> pd.Series:
    """Marginal-VaR style decomposition: each asset's % share of portfolio variance."""
    port_var = float(weights @ cov_daily @ weights)
    if port_var <= 0:
        return pd.Series(np.zeros(len(weights)), index=list(columns))
    cov_w = cov_daily @ weights
    pct = (weights * cov_w) / port_var
    pct = np.nan_to_num(pct, nan=0.0, posinf=0.0, neginf=0.0)
    return pd.Series(pct, index=list(columns))


def annualize_volatility(daily_cov: np.ndarray, weights: np.ndarray) -> float:
    """Convert a daily covariance + weight vector into annualized volatility."""
    daily_var = float(weights @ daily_cov @ weights)
    return float(np.sqrt(max(daily_var, 0.0) * TRADING_DAYS))
