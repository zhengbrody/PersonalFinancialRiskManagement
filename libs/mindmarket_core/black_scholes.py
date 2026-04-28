"""Black-Scholes pricing + analytical Greeks + Newton-Raphson IV solver.

Pure functions, scipy.stats only. No yfinance, no Streamlit.
options_engine.py delegates all of these so behavior is unchanged.
"""
from __future__ import annotations

from typing import Dict, Optional

import numpy as np
from scipy.optimize import brentq
from scipy.stats import norm

from .constants import DAYS_PER_YEAR


def _d1(S: float, K: float, T: float, r: float, sigma: float) -> float:
    """Black-Scholes d1."""
    return (np.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))


def _d2(S: float, K: float, T: float, r: float, sigma: float) -> float:
    """Black-Scholes d2 = d1 - sigma * sqrt(T)."""
    return _d1(S, K, T, r, sigma) - sigma * np.sqrt(T)


def bs_price(
    S: float,
    K: float,
    T: float,
    r: float,
    sigma: float,
    option_type: str = "call",
) -> float:
    """Black-Scholes European option price.

    Parameters
    ----------
    S : Spot price (positive).
    K : Strike (positive).
    T : Time to expiry in years (>= 0).
    r : Continuous risk-free rate.
    sigma : Annualized vol (>= 0).
    option_type : 'call' or 'put'.

    Edge cases
    ----------
    - T == 0 returns intrinsic.
    - sigma == 0 returns discounted intrinsic via the forward.
    """
    option_type = option_type.lower().strip()
    if option_type not in ("call", "put"):
        raise ValueError(f"option_type must be 'call' or 'put', got '{option_type}'")
    if S <= 0 or K <= 0:
        raise ValueError("S and K must be positive")
    if T < 0:
        raise ValueError("T (time to expiry) cannot be negative")
    if sigma < 0:
        raise ValueError("sigma (volatility) cannot be negative")

    if T == 0.0:
        if option_type == "call":
            return max(S - K, 0.0)
        return max(K - S, 0.0)

    if sigma == 0.0:
        forward = S * np.exp(r * T)
        df = np.exp(-r * T)
        if option_type == "call":
            return max(forward - K, 0.0) * df
        return max(K - forward, 0.0) * df

    d1 = _d1(S, K, T, r, sigma)
    d2 = d1 - sigma * np.sqrt(T)

    if option_type == "call":
        price = S * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)
    else:
        price = K * np.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)

    return max(price, 0.0)


def bs_greeks(
    S: float,
    K: float,
    T: float,
    r: float,
    sigma: float,
    option_type: str = "call",
) -> Dict[str, float]:
    """Analytical Greeks: delta, gamma, theta (per calendar day),
    vega (per 1% vol move), rho (per 1% rate move).

    Edge case: T <= 0 or sigma <= 0 returns intrinsic delta + zeros.
    """
    option_type = option_type.lower().strip()
    if option_type not in ("call", "put"):
        raise ValueError(f"option_type must be 'call' or 'put', got '{option_type}'")

    if T <= 0.0 or sigma <= 0.0:
        if option_type == "call":
            delta = 1.0 if S > K else (0.5 if S == K else 0.0)
        else:
            delta = -1.0 if S < K else (-0.5 if S == K else 0.0)
        return {"delta": delta, "gamma": 0.0, "theta": 0.0, "vega": 0.0, "rho": 0.0}

    sqrt_T = np.sqrt(T)
    d1 = _d1(S, K, T, r, sigma)
    d2 = d1 - sigma * sqrt_T
    pdf_d1 = norm.pdf(d1)
    df = np.exp(-r * T)

    if option_type == "call":
        delta = norm.cdf(d1)
    else:
        delta = norm.cdf(d1) - 1.0

    gamma = pdf_d1 / (S * sigma * sqrt_T)

    common_theta = -(S * pdf_d1 * sigma) / (2.0 * sqrt_T)
    if option_type == "call":
        theta_annual = common_theta - r * K * df * norm.cdf(d2)
    else:
        theta_annual = common_theta + r * K * df * norm.cdf(-d2)
    theta = theta_annual / DAYS_PER_YEAR

    vega = S * pdf_d1 * sqrt_T / 100.0

    if option_type == "call":
        rho = K * T * df * norm.cdf(d2) / 100.0
    else:
        rho = -K * T * df * norm.cdf(-d2) / 100.0

    return {
        "delta": float(delta),
        "gamma": float(gamma),
        "theta": float(theta),
        "vega": float(vega),
        "rho": float(rho),
    }


def implied_volatility(
    market_price: float,
    S: float,
    K: float,
    T: float,
    r: float,
    option_type: str = "call",
    tol: float = 1e-8,
    max_iter: int = 100,
) -> Optional[float]:
    """Solve for IV via Newton-Raphson with Brent fallback. Returns None
    if the market price is impossible (below intrinsic, above bounds)
    or if both solvers fail to converge.
    """
    option_type = option_type.lower().strip()

    if market_price <= 0.0 or T <= 0.0:
        return None

    intrinsic = max(S - K, 0.0) if option_type == "call" else max(K - S, 0.0)
    if market_price < intrinsic - 1e-10:
        return None

    if option_type == "call" and market_price >= S:
        return None
    if option_type == "put" and market_price >= K * np.exp(-r * T):
        return None

    sigma = 0.3
    for _ in range(max_iter):
        price = bs_price(S, K, T, r, sigma, option_type)
        diff = price - market_price

        sqrt_T = np.sqrt(T)
        d1 = _d1(S, K, T, r, sigma)
        vega_raw = S * norm.pdf(d1) * sqrt_T

        if abs(diff) < tol:
            return float(sigma)

        if vega_raw < 1e-12:
            break

        sigma -= diff / vega_raw
        if sigma <= 0.0:
            sigma = 1e-4

    def objective(sig):
        return bs_price(S, K, T, r, sig, option_type) - market_price

    try:
        lo = 1e-4
        for hi in [5.0, 10.0, 50.0]:
            if objective(lo) * objective(hi) < 0:
                break
        else:
            return None
        sigma = brentq(objective, lo, hi, xtol=tol, maxiter=200)
        return float(sigma)
    except (ValueError, RuntimeError):
        return None


def time_to_expiry_years(expiry_iso: str) -> float:
    """Convert an ISO date string (YYYY-MM-DD) to T in years from now.
    Returns 0 if the expiry has passed.
    """
    from datetime import datetime

    exp_date = datetime.strptime(expiry_iso, "%Y-%m-%d")
    T = (exp_date - datetime.now()).total_seconds() / (365.25 * 24 * 3600)
    return max(T, 0.0)
