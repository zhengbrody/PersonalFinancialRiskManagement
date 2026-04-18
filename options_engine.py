"""
options_engine.py
Institutional-Grade Options Pricing & Greeks Engine v1.0
──────────────────────────────────────────────────────────
Black-Scholes pricing · Analytical Greeks · Implied volatility (Newton-Raphson)
Option chain enrichment via yfinance · Volatility surface construction
Strategy builder (10+ strategies) · Portfolio Greeks aggregation

Dependencies: numpy, scipy, yfinance (all in requirements.txt)
"""

import numpy as np
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Union
from scipy.stats import norm
from scipy.optimize import brentq
import warnings

from logging_config import get_logger

logger = get_logger(__name__)


# ══════════════════════════════════════════════════════════════
#  Constants
# ══════════════════════════════════════════════════════════════
CONTRACT_MULTIPLIER = 100  # standard equity option contract size
_SQRT_2PI = np.sqrt(2.0 * np.pi)
_DAYS_PER_YEAR = 365.0
_TRADING_DAYS_PER_YEAR = 252.0


# ══════════════════════════════════════════════════════════════
#  Section 1 — Black-Scholes Model
# ══════════════════════════════════════════════════════════════

def _d1(S: float, K: float, T: float, r: float, sigma: float) -> float:
    """Compute d1 in the Black-Scholes formula.

    Parameters
    ----------
    S : float  — Current underlying price.
    K : float  — Strike price.
    T : float  — Time to expiration in years.
    r : float  — Risk-free interest rate (annualized, continuous).
    sigma : float — Volatility (annualized).

    Returns
    -------
    float — d1 value.
    """
    return (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))


def _d2(S: float, K: float, T: float, r: float, sigma: float) -> float:
    """Compute d2 = d1 - sigma * sqrt(T)."""
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
    S : float — Spot price of the underlying.
    K : float — Strike price.
    T : float — Time to expiration in years (must be >= 0).
    r : float — Continuously compounded risk-free rate.
    sigma : float — Annualized volatility of the underlying.
    option_type : str — ``'call'`` or ``'put'``.

    Returns
    -------
    float — Theoretical option price.

    Edge cases
    ----------
    - T == 0: returns intrinsic value.
    - sigma == 0: returns discounted intrinsic value.
    - Very deep ITM / OTM handled gracefully via norm.cdf clipping.
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

    # --- At expiration: return intrinsic value ---
    if T == 0.0:
        if option_type == "call":
            return max(S - K, 0.0)
        else:
            return max(K - S, 0.0)

    # --- Zero vol: deterministic payoff ---
    if sigma == 0.0:
        forward = S * np.exp(r * T)
        df = np.exp(-r * T)
        if option_type == "call":
            return max(forward - K, 0.0) * df
        else:
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
    """Compute all first-order Greeks plus Gamma analytically.

    Parameters
    ----------
    S, K, T, r, sigma, option_type — same as ``bs_price``.

    Returns
    -------
    dict — Keys: ``delta``, ``gamma``, ``theta``, ``vega``, ``rho``.

    Notes
    -----
    - Theta is expressed in *per-calendar-day* (divide annual by 365).
    - Vega is per 1-percentage-point move in vol (i.e. divide by 100).
    - Rho is per 1-percentage-point move in rate (divide by 100).
    """
    option_type = option_type.lower().strip()
    if option_type not in ("call", "put"):
        raise ValueError(f"option_type must be 'call' or 'put', got '{option_type}'")

    # --- Edge case: at expiry ---
    if T <= 0.0 or sigma <= 0.0:
        intrinsic_call = max(S - K, 0.0)
        intrinsic_put = max(K - S, 0.0)
        if option_type == "call":
            delta = 1.0 if S > K else (0.5 if S == K else 0.0)
        else:
            delta = -1.0 if S < K else (-0.5 if S == K else 0.0)
        return {
            "delta": delta,
            "gamma": 0.0,
            "theta": 0.0,
            "vega": 0.0,
            "rho": 0.0,
        }

    sqrt_T = np.sqrt(T)
    d1 = _d1(S, K, T, r, sigma)
    d2 = d1 - sigma * sqrt_T
    pdf_d1 = norm.pdf(d1)
    df = np.exp(-r * T)

    # --- Delta ---
    if option_type == "call":
        delta = norm.cdf(d1)
    else:
        delta = norm.cdf(d1) - 1.0

    # --- Gamma (same for call and put) ---
    gamma = pdf_d1 / (S * sigma * sqrt_T)

    # --- Theta (per calendar day) ---
    common_theta = -(S * pdf_d1 * sigma) / (2.0 * sqrt_T)
    if option_type == "call":
        theta_annual = common_theta - r * K * df * norm.cdf(d2)
    else:
        theta_annual = common_theta + r * K * df * norm.cdf(-d2)
    theta = theta_annual / _DAYS_PER_YEAR

    # --- Vega (per 1% move in vol) ---
    vega = S * pdf_d1 * sqrt_T / 100.0

    # --- Rho (per 1% move in rate) ---
    if option_type == "call":
        rho = K * T * df * norm.cdf(d2) / 100.0
    else:
        rho = -K * T * df * norm.cdf(-d2) / 100.0

    return {
        "delta": delta,
        "gamma": gamma,
        "theta": theta,
        "vega": vega,
        "rho": rho,
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
    """Solve for implied volatility using Newton-Raphson with Brent fallback.

    Parameters
    ----------
    market_price : float — Observed market price of the option.
    S, K, T, r, option_type — same as ``bs_price``.
    tol : float — Convergence tolerance.
    max_iter : int — Maximum Newton-Raphson iterations.

    Returns
    -------
    float or None — Implied volatility, or None if no solution found.
    """
    option_type = option_type.lower().strip()

    # Sanity checks
    if market_price <= 0.0:
        return None
    if T <= 0.0:
        return None

    # Check against intrinsic to avoid impossible prices
    intrinsic = max(S - K, 0.0) if option_type == "call" else max(K - S, 0.0)
    if market_price < intrinsic - 1e-10:
        return None  # below intrinsic — no valid IV

    # Upper bound check: price cannot exceed S (call) or K*exp(-rT) (put)
    if option_type == "call" and market_price >= S:
        return None
    if option_type == "put" and market_price >= K * np.exp(-r * T):
        return None

    # --- Newton-Raphson ---
    sigma = 0.3  # initial guess
    for i in range(max_iter):
        price = bs_price(S, K, T, r, sigma, option_type)
        diff = price - market_price

        # Vega (un-normalized, raw d(price)/d(sigma))
        sqrt_T = np.sqrt(T)
        d1 = _d1(S, K, T, r, sigma)
        vega_raw = S * norm.pdf(d1) * sqrt_T

        if abs(diff) < tol:
            return sigma

        if vega_raw < 1e-12:
            break  # vega too small — Newton step unreliable

        sigma -= diff / vega_raw
        if sigma <= 0.0:
            sigma = 1e-4  # clamp to positive

    # --- Brent fallback on [0.001, 10.0] ---
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
        return sigma
    except (ValueError, RuntimeError):
        return None


# ══════════════════════════════════════════════════════════════
#  Section 2 — Option Chain Data Provider (yfinance)
# ══════════════════════════════════════════════════════════════

def get_option_chain(ticker: str) -> Dict:
    """Fetch all available option expirations and their chains via yfinance.

    Parameters
    ----------
    ticker : str — Equity ticker symbol (e.g. ``'AAPL'``).

    Returns
    -------
    dict — ``{expirations: list[str], chains: {expiry: {calls: DataFrame, puts: DataFrame}}}``
    """
    import yfinance as yf

    tk = yf.Ticker(ticker)
    expirations = tk.options  # tuple of date strings

    if not expirations:
        logger.warning(f"No option expirations found for {ticker}")
        return {"expirations": [], "chains": {}}

    chains: Dict = {}
    for exp in expirations:
        try:
            chain = tk.option_chain(exp)
            chains[exp] = {
                "calls": chain.calls,
                "puts": chain.puts,
            }
        except Exception as e:
            logger.error(f"Failed to fetch chain for {ticker} exp={exp}: {e}")
            continue

    return {"expirations": list(expirations), "chains": chains}


def _get_spot_price(ticker: str) -> float:
    """Get the current spot price for a ticker via yfinance."""
    import yfinance as yf

    tk = yf.Ticker(ticker)
    hist = tk.history(period="1d")
    if hist.empty:
        raise ValueError(f"Cannot retrieve spot price for {ticker}")
    return float(hist["Close"].iloc[-1])


def get_chain_with_greeks(
    ticker: str,
    expiration: str,
    risk_free_rate: float = 0.05,
) -> Dict[str, "pd.DataFrame"]:
    """Fetch an option chain for a single expiration and enrich with Greeks + IV.

    Parameters
    ----------
    ticker : str — Ticker symbol.
    expiration : str — Expiration date string (from ``get_option_chain``).
    risk_free_rate : float — Annualized risk-free rate (default 5%).

    Returns
    -------
    dict — ``{calls: DataFrame, puts: DataFrame}`` with added columns:
           ``iv``, ``delta``, ``gamma``, ``theta``, ``vega``, ``rho``, ``bs_price``.
    """
    import yfinance as yf
    import pandas as pd
    from datetime import datetime

    tk = yf.Ticker(ticker)
    chain = tk.option_chain(expiration)
    S = _get_spot_price(ticker)

    # Time to expiry in years
    exp_date = datetime.strptime(expiration, "%Y-%m-%d")
    now = datetime.now()
    T = max((exp_date - now).total_seconds() / (365.25 * 24 * 3600), 1e-6)

    result = {}
    for otype, df in [("call", chain.calls), ("put", chain.puts)]:
        df = df.copy()
        greeks_cols = {
            "iv": [],
            "bs_price": [],
            "delta": [],
            "gamma": [],
            "theta": [],
            "vega": [],
            "rho": [],
        }

        for _, row in df.iterrows():
            K = float(row["strike"])
            bid = float(row.get("bid", 0.0) or 0.0)
            ask = float(row.get("ask", 0.0) or 0.0)
            mid = (bid + ask) / 2.0 if bid > 0 and ask > 0 else float(row.get("lastPrice", 0.0))

            # Prefer exchange-reported IV (more reliable than our solver on stale prices)
            market_iv = float(row.get("impliedVolatility", 0.0) or 0.0)
            if market_iv > 0.0 and not np.isnan(market_iv):
                iv = market_iv
            else:
                iv = implied_volatility(mid, S, K, T, risk_free_rate, otype)
                if iv is None or np.isnan(iv):
                    iv = np.nan

            if iv > 0:
                price = bs_price(S, K, T, risk_free_rate, iv, otype)
                g = bs_greeks(S, K, T, risk_free_rate, iv, otype)
            else:
                price = 0.0
                g = {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0, "rho": 0.0}

            greeks_cols["iv"].append(iv)
            greeks_cols["bs_price"].append(price)
            greeks_cols["delta"].append(g["delta"])
            greeks_cols["gamma"].append(g["gamma"])
            greeks_cols["theta"].append(g["theta"])
            greeks_cols["vega"].append(g["vega"])
            greeks_cols["rho"].append(g["rho"])

        for col, vals in greeks_cols.items():
            df[col] = vals

        result[otype + "s"] = df

    return result


def get_iv_surface(
    ticker: str,
    risk_free_rate: float = 0.05,
    max_expirations: int = 8,
) -> "pd.DataFrame":
    """Build an implied-volatility surface (strike x expiry x IV) for 3D plotting.

    Parameters
    ----------
    ticker : str — Ticker symbol.
    risk_free_rate : float — Risk-free rate.
    max_expirations : int — Maximum number of expirations to include (nearest first).

    Returns
    -------
    pd.DataFrame — Columns: ``strike``, ``expiration``, ``T``, ``iv``, ``option_type``.
    """
    import yfinance as yf
    import pandas as pd
    from datetime import datetime

    tk = yf.Ticker(ticker)
    expirations = tk.options
    if not expirations:
        return pd.DataFrame(columns=["strike", "expiration", "T", "iv", "option_type"])

    S = _get_spot_price(ticker)
    expirations = expirations[:max_expirations]
    now = datetime.now()

    rows: List[Dict] = []
    for exp in expirations:
        exp_date = datetime.strptime(exp, "%Y-%m-%d")
        T = max((exp_date - now).total_seconds() / (365.25 * 24 * 3600), 1e-6)

        try:
            chain = tk.option_chain(exp)
        except Exception:
            continue

        for otype, df in [("call", chain.calls), ("put", chain.puts)]:
            for _, row in df.iterrows():
                K = float(row["strike"])
                # Filter strikes to +/- 30% of spot for cleaner surface
                if K < S * 0.7 or K > S * 1.3:
                    continue
                bid = float(row.get("bid", 0.0) or 0.0)
                ask = float(row.get("ask", 0.0) or 0.0)
                mid = (bid + ask) / 2.0 if bid > 0 and ask > 0 else float(row.get("lastPrice", 0.0))
                # Prefer exchange-reported IV
                market_iv = float(row.get("impliedVolatility", 0.0) or 0.0)
                if market_iv > 0.0 and not np.isnan(market_iv) and market_iv <= 5.0:
                    iv = market_iv
                else:
                    iv = implied_volatility(mid, S, K, T, risk_free_rate, otype)
                    if iv is None or iv <= 0 or iv > 5.0:
                        iv = np.nan
                if iv and not np.isnan(iv):
                    rows.append({
                        "strike": K,
                        "expiration": exp,
                        "T": round(T, 4),
                        "iv": round(iv, 6),
                        "option_type": otype,
                    })

    return pd.DataFrame(rows)


# ══════════════════════════════════════════════════════════════
#  Section 3 — Strategy Analysis
# ══════════════════════════════════════════════════════════════

@dataclass
class OptionLeg:
    """A single leg in a multi-leg option strategy.

    Attributes
    ----------
    strike : float — Strike price.
    expiry : str — Expiration date string.
    option_type : str — ``'call'`` or ``'put'``.
    quantity : int — Number of contracts (always positive).
    action : str — ``'buy'`` or ``'sell'``.
    premium : float — Per-share premium paid (positive) or received (negative).
    sigma : float — Volatility used for Greeks (IV or assumed).
    """
    strike: float
    expiry: str
    option_type: str  # 'call' or 'put'
    quantity: int  # positive
    action: str  # 'buy' or 'sell'
    premium: float = 0.0  # per-share premium (positive = paid, negative = received)
    sigma: float = 0.30  # for Greeks computation


@dataclass
class StockLeg:
    """A stock position embedded in a strategy (e.g., covered call).

    Attributes
    ----------
    quantity : int — Number of shares (positive = long, negative = short).
    entry_price : float — Purchase / short-sale price.
    """
    quantity: int
    entry_price: float


@dataclass
class OptionStrategy:
    """A complete option strategy composed of option legs and optional stock legs.

    Attributes
    ----------
    name : str — Human-readable strategy name.
    ticker : str — Underlying ticker.
    spot : float — Current spot price of the underlying.
    risk_free_rate : float — Risk-free rate for Greeks computation.
    option_legs : list[OptionLeg] — Option legs.
    stock_legs : list[StockLeg] — Stock legs (for covered call, protective put, etc.).
    """
    name: str
    ticker: str
    spot: float
    risk_free_rate: float = 0.05
    option_legs: List[OptionLeg] = field(default_factory=list)
    stock_legs: List[StockLeg] = field(default_factory=list)

    def net_premium(self) -> float:
        """Net premium: negative = net credit, positive = net debit (per-share basis)."""
        total = 0.0
        for leg in self.option_legs:
            sign = 1.0 if leg.action == "buy" else -1.0
            total += sign * leg.premium * leg.quantity
        return total

    def net_premium_total(self) -> float:
        """Net premium in dollar terms (including contract multiplier)."""
        return self.net_premium() * CONTRACT_MULTIPLIER


def _time_to_expiry_years(expiry: str) -> float:
    """Parse expiry string and return T in years from now."""
    from datetime import datetime
    exp_date = datetime.strptime(expiry, "%Y-%m-%d")
    T = (exp_date - datetime.now()).total_seconds() / (365.25 * 24 * 3600)
    return max(T, 0.0)


def compute_pnl_at_expiry(
    strategy: OptionStrategy,
    price_range: Optional[np.ndarray] = None,
    num_points: int = 200,
) -> Tuple[np.ndarray, np.ndarray]:
    """Compute the P&L at expiration across a range of underlying prices.

    Parameters
    ----------
    strategy : OptionStrategy — The strategy to evaluate.
    price_range : np.ndarray or None — Array of underlying prices. If None,
        a sensible range around the spot is generated automatically.
    num_points : int — Number of price points if auto-generating range.

    Returns
    -------
    (prices, pnl) : tuple of np.ndarray — Prices and corresponding total P&L
        (in dollars, including contract multiplier for options).
    """
    S = strategy.spot

    if price_range is None:
        # Determine range from strikes
        strikes = [leg.strike for leg in strategy.option_legs]
        lo = min(strikes + [S]) * 0.7
        hi = max(strikes + [S]) * 1.3
        price_range = np.linspace(lo, hi, num_points)

    pnl = np.zeros_like(price_range, dtype=float)

    # Stock legs
    for sl in strategy.stock_legs:
        pnl += sl.quantity * (price_range - sl.entry_price)

    # Option legs
    for leg in strategy.option_legs:
        sign = 1.0 if leg.action == "buy" else -1.0

        if leg.option_type == "call":
            intrinsic = np.maximum(price_range - leg.strike, 0.0)
        else:
            intrinsic = np.maximum(leg.strike - price_range, 0.0)

        leg_pnl = sign * (intrinsic - leg.premium) * leg.quantity * CONTRACT_MULTIPLIER
        # Note: premium already has correct sign embedded: we paid it (buy) or
        # received it (sell). The sign*premium handles direction.
        # Actually, re-derive carefully:
        #   Buy: payoff = intrinsic - premium_paid  (premium_paid > 0)
        #   Sell: payoff = premium_received - intrinsic  (premium_received > 0)
        # Using sign and premium as positive value:
        leg_pnl = sign * intrinsic * leg.quantity * CONTRACT_MULTIPLIER \
                   - sign * leg.premium * leg.quantity * CONTRACT_MULTIPLIER
        # But sign*premium_paid for buy = +premium (cost)
        # sign*premium_received for sell = -premium (income, but premium stored positive)
        # Simplify: premium is always stored as positive price paid/received.
        # Buy:  PnL = (intrinsic - premium) * qty * 100
        # Sell: PnL = (premium - intrinsic) * qty * 100
        leg_pnl = sign * (intrinsic - leg.premium) * leg.quantity * CONTRACT_MULTIPLIER
        pnl += leg_pnl

    return price_range, pnl


def compute_strategy_greeks(strategy: OptionStrategy) -> Dict[str, float]:
    """Aggregate Greeks across all legs of a strategy.

    Parameters
    ----------
    strategy : OptionStrategy — Strategy with option and stock legs.

    Returns
    -------
    dict — ``{delta, gamma, theta, vega, rho}`` (portfolio-level, dollar-adjusted).
        Delta and other Greeks are already multiplied by quantity * contract multiplier.
    """
    totals = {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0, "rho": 0.0}

    # Stock legs
    for sl in strategy.stock_legs:
        totals["delta"] += sl.quantity  # 1 delta per share

    # Option legs
    for leg in strategy.option_legs:
        T = _time_to_expiry_years(leg.expiry)
        g = bs_greeks(strategy.spot, leg.strike, T, strategy.risk_free_rate,
                      leg.sigma, leg.option_type)
        sign = 1.0 if leg.action == "buy" else -1.0
        multiplier = sign * leg.quantity * CONTRACT_MULTIPLIER
        for key in totals:
            totals[key] += g[key] * multiplier

    return totals


def strategy_metrics(
    strategy: OptionStrategy,
    price_range: Optional[np.ndarray] = None,
) -> Dict[str, Union[float, List[float]]]:
    """Compute max profit, max loss, and breakeven points for a strategy.

    Parameters
    ----------
    strategy : OptionStrategy — The strategy.
    price_range : np.ndarray or None — Override price range for analysis.

    Returns
    -------
    dict — ``{max_profit, max_loss, breakevens}``.
    """
    prices, pnl = compute_pnl_at_expiry(strategy, price_range, num_points=2000)

    max_profit = float(np.max(pnl))
    max_loss = float(np.min(pnl))

    # Detect unlimited profit/loss via slope at the RIGHT boundary.
    # Left boundary (price→0) is always bounded for equity options,
    # so only the right boundary (price→∞) can be truly unlimited.
    dp = float(prices[1] - prices[0]) if len(prices) > 1 else 1.0
    _SLOPE_THRESH = 0.01
    if dp > 0 and len(pnl) > 1:
        slope_right = (pnl[-1] - pnl[-2]) / dp
    else:
        slope_right = 0.0

    if pnl[-1] > 0 and slope_right > _SLOPE_THRESH:
        max_profit = float("inf")
    if pnl[-1] < 0 and slope_right < -_SLOPE_THRESH:
        max_loss = float("-inf")

    # Breakeven: find zero crossings
    breakevens: List[float] = []
    for i in range(len(pnl) - 1):
        if pnl[i] * pnl[i + 1] < 0:
            # Linear interpolation for the zero crossing
            frac = abs(pnl[i]) / (abs(pnl[i]) + abs(pnl[i + 1]))
            be = prices[i] + frac * (prices[i + 1] - prices[i])
            breakevens.append(round(float(be), 2))

    return {
        "max_profit": max_profit,
        "max_loss": max_loss,
        "breakevens": breakevens,
    }


# ──────────────────────────────────────────────────────────────
#  Strategy Factory
# ──────────────────────────────────────────────────────────────

def build_strategy(
    strategy_name: str,
    ticker: str,
    S: float,
    expiry: str = "2026-06-19",
    r: float = 0.05,
    sigma: float = 0.30,
    **kwargs,
) -> OptionStrategy:
    """Factory to construct common option strategies.

    Parameters
    ----------
    strategy_name : str — One of: ``long_call``, ``long_put``, ``covered_call``,
        ``protective_put``, ``bull_call_spread``, ``bear_put_spread``,
        ``iron_condor``, ``straddle``, ``strangle``, ``wheel``.
    ticker : str — Underlying ticker.
    S : float — Current spot price.
    expiry : str — Expiration date ``YYYY-MM-DD``.
    r : float — Risk-free rate.
    sigma : float — Assumed volatility for pricing legs.
    **kwargs — Strategy-specific parameters (see notes below).

    Keyword Arguments
    -----------------
    strike : float — ATM strike (default = S rounded to nearest integer).
    strike_call : float — Call strike for spreads / strangles.
    strike_put : float — Put strike for spreads / strangles.
    strike_low_put : float — Lower put strike (iron condor).
    strike_high_call : float — Upper call strike (iron condor).
    quantity : int — Number of contracts per leg (default 1).

    Returns
    -------
    OptionStrategy
    """
    strategy_name = strategy_name.lower().replace(" ", "_").replace("-", "_")
    strike = kwargs.get("strike", round(S))
    qty = kwargs.get("quantity", 1)

    T = _time_to_expiry_years(expiry)

    def _premium(K, otype):
        return bs_price(S, K, T, r, sigma, otype)

    if strategy_name == "long_call":
        K = kwargs.get("strike_call", strike)
        prem = _premium(K, "call")
        return OptionStrategy(
            name="Long Call",
            ticker=ticker,
            spot=S,
            risk_free_rate=r,
            option_legs=[
                OptionLeg(K, expiry, "call", qty, "buy", prem, sigma),
            ],
        )

    elif strategy_name == "long_put":
        K = kwargs.get("strike_put", strike)
        prem = _premium(K, "put")
        return OptionStrategy(
            name="Long Put",
            ticker=ticker,
            spot=S,
            risk_free_rate=r,
            option_legs=[
                OptionLeg(K, expiry, "put", qty, "buy", prem, sigma),
            ],
        )

    elif strategy_name == "covered_call":
        K = kwargs.get("strike_call", round(S * 1.05))
        prem = _premium(K, "call")
        return OptionStrategy(
            name="Covered Call",
            ticker=ticker,
            spot=S,
            risk_free_rate=r,
            option_legs=[
                OptionLeg(K, expiry, "call", qty, "sell", prem, sigma),
            ],
            stock_legs=[
                StockLeg(qty * CONTRACT_MULTIPLIER, S),
            ],
        )

    elif strategy_name == "protective_put":
        K = kwargs.get("strike_put", round(S * 0.95))
        prem = _premium(K, "put")
        return OptionStrategy(
            name="Protective Put",
            ticker=ticker,
            spot=S,
            risk_free_rate=r,
            option_legs=[
                OptionLeg(K, expiry, "put", qty, "buy", prem, sigma),
            ],
            stock_legs=[
                StockLeg(qty * CONTRACT_MULTIPLIER, S),
            ],
        )

    elif strategy_name == "bull_call_spread":
        K_low = kwargs.get("strike_call", round(S * 0.97))
        K_high = kwargs.get("strike_call_high", round(S * 1.03))
        if K_high <= K_low:
            K_low, K_high = K_high, K_low
        prem_low = _premium(K_low, "call")
        prem_high = _premium(K_high, "call")
        return OptionStrategy(
            name="Bull Call Spread",
            ticker=ticker,
            spot=S,
            risk_free_rate=r,
            option_legs=[
                OptionLeg(K_low, expiry, "call", qty, "buy", prem_low, sigma),
                OptionLeg(K_high, expiry, "call", qty, "sell", prem_high, sigma),
            ],
        )

    elif strategy_name == "bear_put_spread":
        K_high = kwargs.get("strike_put", round(S * 1.03))
        K_low = kwargs.get("strike_put_low", round(S * 0.97))
        if K_high <= K_low:
            K_low, K_high = K_high, K_low
        prem_high = _premium(K_high, "put")
        prem_low = _premium(K_low, "put")
        return OptionStrategy(
            name="Bear Put Spread",
            ticker=ticker,
            spot=S,
            risk_free_rate=r,
            option_legs=[
                OptionLeg(K_high, expiry, "put", qty, "buy", prem_high, sigma),
                OptionLeg(K_low, expiry, "put", qty, "sell", prem_low, sigma),
            ],
        )

    elif strategy_name == "iron_condor":
        K_lp = kwargs.get("strike_low_put", round(S * 0.93))
        K_hp = kwargs.get("strike_put", round(S * 0.97))
        if K_hp <= K_lp:
            K_lp, K_hp = K_hp, K_lp
        K_lc = kwargs.get("strike_call", round(S * 1.03))
        K_hc = kwargs.get("strike_high_call", round(S * 1.07))
        if K_hc <= K_lc:
            K_lc, K_hc = K_hc, K_lc
        return OptionStrategy(
            name="Iron Condor",
            ticker=ticker,
            spot=S,
            risk_free_rate=r,
            option_legs=[
                OptionLeg(K_lp, expiry, "put", qty, "buy", _premium(K_lp, "put"), sigma),
                OptionLeg(K_hp, expiry, "put", qty, "sell", _premium(K_hp, "put"), sigma),
                OptionLeg(K_lc, expiry, "call", qty, "sell", _premium(K_lc, "call"), sigma),
                OptionLeg(K_hc, expiry, "call", qty, "buy", _premium(K_hc, "call"), sigma),
            ],
        )

    elif strategy_name == "straddle":
        K = kwargs.get("strike", strike)
        return OptionStrategy(
            name="Straddle",
            ticker=ticker,
            spot=S,
            risk_free_rate=r,
            option_legs=[
                OptionLeg(K, expiry, "call", qty, "buy", _premium(K, "call"), sigma),
                OptionLeg(K, expiry, "put", qty, "buy", _premium(K, "put"), sigma),
            ],
        )

    elif strategy_name == "strangle":
        K_call = kwargs.get("strike_call", round(S * 1.05))
        K_put = kwargs.get("strike_put", round(S * 0.95))
        return OptionStrategy(
            name="Strangle",
            ticker=ticker,
            spot=S,
            risk_free_rate=r,
            option_legs=[
                OptionLeg(K_call, expiry, "call", qty, "buy",
                          _premium(K_call, "call"), sigma),
                OptionLeg(K_put, expiry, "put", qty, "buy",
                          _premium(K_put, "put"), sigma),
            ],
        )

    elif strategy_name == "wheel":
        # The Wheel: begin with Cash-Secured Put; if assigned, switch to
        # Covered Call. We model the initial CSP phase.
        K = kwargs.get("strike_put", round(S * 0.95))
        prem = _premium(K, "put")
        strat = OptionStrategy(
            name="Wheel (CSP Phase)",
            ticker=ticker,
            spot=S,
            risk_free_rate=r,
            option_legs=[
                OptionLeg(K, expiry, "put", qty, "sell", prem, sigma),
            ],
        )
        return strat

    else:
        raise ValueError(
            f"Unknown strategy '{strategy_name}'. Supported: long_call, long_put, "
            "covered_call, protective_put, bull_call_spread, bear_put_spread, "
            "iron_condor, straddle, strangle, wheel"
        )


# ══════════════════════════════════════════════════════════════
#  Section 4 — Portfolio Greeks Aggregation
# ══════════════════════════════════════════════════════════════

@dataclass
class StockPosition:
    """A stock holding for portfolio-level Greeks.

    Attributes
    ----------
    ticker : str — Ticker symbol.
    shares : int — Number of shares (positive = long, negative = short).
    price : float — Current price per share.
    """
    ticker: str
    shares: int
    price: float


@dataclass
class OptionPosition:
    """An option holding for portfolio-level Greeks.

    Attributes
    ----------
    ticker : str — Underlying ticker.
    strike : float — Strike price.
    expiry : str — Expiration ``YYYY-MM-DD``.
    option_type : str — ``'call'`` or ``'put'``.
    contracts : int — Number of contracts (positive = long, negative = short).
    sigma : float — IV or assumed volatility.
    spot : float — Current spot price of the underlying.
    risk_free_rate : float — Risk-free rate.
    """
    ticker: str
    strike: float
    expiry: str
    option_type: str
    contracts: int  # positive = long, negative = short
    sigma: float
    spot: float
    risk_free_rate: float = 0.05


def compute_portfolio_greeks(
    stock_positions: List[StockPosition],
    option_positions: List[OptionPosition],
) -> Dict[str, float]:
    """Aggregate portfolio-level Greeks from stock and option positions.

    Parameters
    ----------
    stock_positions : list[StockPosition] — All stock holdings.
    option_positions : list[OptionPosition] — All option holdings.

    Returns
    -------
    dict — ``{delta, gamma, theta, vega, rho}`` at the portfolio level.

    Notes
    -----
    - Stock: Delta = shares * 1.0, Gamma = Theta = Vega = Rho = 0.
    - Options: Greeks * contracts * CONTRACT_MULTIPLIER (100).
    - Signs follow the convention: long options have positive Greeks as returned
      by ``bs_greeks``; short options have their Greeks negated via the negative
      contracts count.
    """
    totals = {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0, "rho": 0.0}

    # Stock positions: delta = 1 per share, no other Greeks
    for sp in stock_positions:
        totals["delta"] += float(sp.shares)

    # Option positions
    for op in option_positions:
        T = _time_to_expiry_years(op.expiry)
        g = bs_greeks(op.spot, op.strike, T, op.risk_free_rate,
                      op.sigma, op.option_type)
        multiplier = op.contracts * CONTRACT_MULTIPLIER
        for key in totals:
            totals[key] += g[key] * multiplier

    return totals


# ══════════════════════════════════════════════════════════════
#  Section 5 — Educational Strategy Descriptions
# ══════════════════════════════════════════════════════════════

STRATEGY_INFO: Dict[str, Dict[str, str]] = {
    "long_call": {
        "description": (
            "Purchase a call option, giving the right (not obligation) to buy "
            "the underlying at the strike price before expiration."
        ),
        "when_to_use": (
            "Bullish outlook with defined risk. Expecting a significant upward "
            "move in the underlying within the option's lifetime."
        ),
        "risk_profile": "Limited risk (premium paid), unlimited profit potential.",
        "max_profit": "Unlimited (underlying can rise indefinitely).",
        "max_loss": "Limited to the premium paid.",
    },
    "long_put": {
        "description": (
            "Purchase a put option, giving the right to sell the underlying at "
            "the strike price before expiration."
        ),
        "when_to_use": (
            "Bearish outlook or hedging downside risk. Expecting a significant "
            "decline in the underlying."
        ),
        "risk_profile": "Limited risk (premium paid), large profit potential.",
        "max_profit": "Strike price minus premium paid (underlying can fall to zero).",
        "max_loss": "Limited to the premium paid.",
    },
    "covered_call": {
        "description": (
            "Hold 100 shares of the underlying and sell a call option against them. "
            "Generates income from the premium while capping upside."
        ),
        "when_to_use": (
            "Neutral to mildly bullish. Willing to sell shares at the strike price. "
            "Seeking to enhance yield on an existing stock position."
        ),
        "risk_profile": "Downside risk on the stock minus premium received; upside capped at strike.",
        "max_profit": "(Strike - Entry Price) * 100 + premium received.",
        "max_loss": "(Entry Price - Premium Received) * 100 (stock goes to zero).",
    },
    "protective_put": {
        "description": (
            "Hold 100 shares of the underlying and buy a put option as insurance. "
            "Establishes a floor on potential losses."
        ),
        "when_to_use": (
            "Bullish long-term but concerned about near-term downside risk. "
            "Willing to pay a premium for portfolio protection."
        ),
        "risk_profile": "Downside limited to (Entry - Strike + Premium); upside unlimited.",
        "max_profit": "Unlimited (underlying can rise indefinitely) minus premium paid.",
        "max_loss": "(Entry Price - Strike + Premium) * 100.",
    },
    "bull_call_spread": {
        "description": (
            "Buy a lower-strike call and sell a higher-strike call at the same "
            "expiration. A debit spread that profits from moderate upward moves."
        ),
        "when_to_use": (
            "Moderately bullish. Want to reduce cost of a long call by selling "
            "a higher-strike call, accepting capped upside."
        ),
        "risk_profile": "Both profit and loss are limited (defined-risk).",
        "max_profit": "(High Strike - Low Strike - Net Debit) * 100.",
        "max_loss": "Net debit paid * 100.",
    },
    "bear_put_spread": {
        "description": (
            "Buy a higher-strike put and sell a lower-strike put at the same "
            "expiration. A debit spread that profits from moderate downward moves."
        ),
        "when_to_use": (
            "Moderately bearish. Want to reduce the cost of a long put by selling "
            "a lower-strike put, accepting capped profit."
        ),
        "risk_profile": "Both profit and loss are limited (defined-risk).",
        "max_profit": "(High Strike - Low Strike - Net Debit) * 100.",
        "max_loss": "Net debit paid * 100.",
    },
    "iron_condor": {
        "description": (
            "Sell a put spread and a call spread simultaneously around the current "
            "price, collecting premium. Composed of four legs: buy low put, sell "
            "mid-low put, sell mid-high call, buy high call."
        ),
        "when_to_use": (
            "Neutral outlook expecting low volatility. Profiting from time decay "
            "when the underlying stays within a range."
        ),
        "risk_profile": "Both profit and loss are limited (defined-risk).",
        "max_profit": "Net credit received * 100.",
        "max_loss": "(Width of wider spread - Net Credit) * 100.",
    },
    "straddle": {
        "description": (
            "Buy a call and a put at the same strike and expiration. Profits from "
            "a large move in either direction."
        ),
        "when_to_use": (
            "Expecting a large move but uncertain about direction. Often used "
            "around earnings announcements or major events."
        ),
        "risk_profile": "Limited risk (total premium paid), unlimited profit potential.",
        "max_profit": "Unlimited (large move in either direction).",
        "max_loss": "Total premium paid for both legs.",
    },
    "strangle": {
        "description": (
            "Buy an OTM call and an OTM put at different strikes with the same "
            "expiration. Cheaper than a straddle but requires a larger move."
        ),
        "when_to_use": (
            "Expecting a very large move but uncertain about direction. Seeking "
            "lower upfront cost than a straddle."
        ),
        "risk_profile": "Limited risk (total premium paid), unlimited profit potential.",
        "max_profit": "Unlimited (large move in either direction).",
        "max_loss": "Total premium paid for both legs.",
    },
    "wheel": {
        "description": (
            "A cyclical income strategy: (1) Sell cash-secured puts at a strike you "
            "are willing to own the stock. (2) If assigned, sell covered calls against "
            "the shares. (3) If called away, restart with step 1. Repeat for "
            "continuous premium income."
        ),
        "when_to_use": (
            "Neutral to mildly bullish on high-quality stocks you would be happy to "
            "own. Seeking consistent income from option premiums."
        ),
        "risk_profile": (
            "Downside risk if stock falls significantly below put strike. Upside "
            "capped at call strike during the covered-call phase."
        ),
        "max_profit": "Premium collected each cycle + capital gains up to call strike.",
        "max_loss": "Stock falls to zero minus all premiums collected.",
    },
}


# ══════════════════════════════════════════════════════════════
#  Convenience / Quick-Analysis Functions
# ══════════════════════════════════════════════════════════════

def quick_bs_table(
    S: float,
    strikes: List[float],
    T: float,
    r: float,
    sigma: float,
    option_type: str = "call",
) -> "pd.DataFrame":
    """Generate a quick price + Greeks table for a list of strikes.

    Parameters
    ----------
    S : float — Spot price.
    strikes : list[float] — Strike prices to evaluate.
    T, r, sigma, option_type — Standard BS parameters.

    Returns
    -------
    pd.DataFrame — One row per strike with columns: strike, price, delta,
        gamma, theta, vega, rho.
    """
    import pandas as pd

    rows = []
    for K in strikes:
        price = bs_price(S, K, T, r, sigma, option_type)
        greeks = bs_greeks(S, K, T, r, sigma, option_type)
        rows.append({
            "strike": K,
            "price": round(price, 4),
            "delta": round(greeks["delta"], 4),
            "gamma": round(greeks["gamma"], 6),
            "theta": round(greeks["theta"], 4),
            "vega": round(greeks["vega"], 4),
            "rho": round(greeks["rho"], 4),
        })
    return pd.DataFrame(rows)


def summarize_strategy(strategy: OptionStrategy) -> Dict:
    """Return a full summary dict for a strategy: Greeks, metrics, info.

    Parameters
    ----------
    strategy : OptionStrategy — Built strategy.

    Returns
    -------
    dict — ``{name, ticker, spot, net_premium, greeks, metrics, info}``.
    """
    greeks = compute_strategy_greeks(strategy)
    metrics = strategy_metrics(strategy)
    name_key = strategy.name.lower().replace(" ", "_").replace("(", "").replace(")", "")
    # Try matching known strategies for info
    info = None
    for k, v in STRATEGY_INFO.items():
        if k in name_key or name_key in k:
            info = v
            break

    return {
        "name": strategy.name,
        "ticker": strategy.ticker,
        "spot": strategy.spot,
        "net_premium": strategy.net_premium(),
        "net_premium_total": strategy.net_premium_total(),
        "greeks": greeks,
        "metrics": metrics,
        "info": info,
    }
