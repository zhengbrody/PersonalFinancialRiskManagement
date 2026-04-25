"""
performance_attribution.py
Performance Attribution Module v1.0
──────────────────────────────────────────────────────────
Brinson-Hood-Beebower sector attribution · Multi-factor regression
attribution · Daily/period PnL decomposition · Tracking error ·
Information ratio · Hit ratio
"""

from typing import Dict, List, Optional, Union

import numpy as np
import pandas as pd

from logging_config import get_logger

logger = get_logger(__name__)

# ══════════════════════════════════════════════════════════════
#  Constants
# ══════════════════════════════════════════════════════════════
TRADING_DAYS = 252

# Canonical sector map lives in portfolio_config.py.
# Re-exported here as DEFAULT_SECTOR_MAP for backward compatibility with callers
# (e.g. pages/9_Quant_Lab.py imports this name directly).
from portfolio_config import SECTOR_MAP as DEFAULT_SECTOR_MAP  # noqa: F401

# ══════════════════════════════════════════════════════════════
#  Helper Functions
# ══════════════════════════════════════════════════════════════


def _tracking_error(active_returns: Union[pd.Series, np.ndarray]) -> float:
    """
    Annualized tracking error (standard deviation of active returns).

    Parameters
    ----------
    active_returns : Series or array
        Daily active returns (portfolio minus benchmark).

    Returns
    -------
    float
        Annualized tracking error.
    """
    active = np.asarray(active_returns, dtype=float)
    active = active[np.isfinite(active)]
    if len(active) < 2:
        return 0.0
    return float(np.std(active, ddof=1) * np.sqrt(TRADING_DAYS))


def _information_ratio(active_returns: Union[pd.Series, np.ndarray]) -> float:
    """
    Information ratio: annualized mean active return / annualized tracking error.

    IR = mean(active) / std(active) * sqrt(252)

    Parameters
    ----------
    active_returns : Series or array
        Daily active returns.

    Returns
    -------
    float
        Information ratio, or 0.0 if tracking error is negligible.
    """
    active = np.asarray(active_returns, dtype=float)
    active = active[np.isfinite(active)]
    if len(active) < 2:
        return 0.0
    std = np.std(active, ddof=1)
    if std < 1e-12:
        return 0.0
    return float(np.mean(active) / std * np.sqrt(TRADING_DAYS))


def _hit_ratio(active_returns: Union[pd.Series, np.ndarray]) -> float:
    """
    Hit ratio: percentage of periods with positive active return.

    Parameters
    ----------
    active_returns : Series or array
        Active returns per period.

    Returns
    -------
    float
        Hit ratio in [0, 1].
    """
    active = np.asarray(active_returns, dtype=float)
    active = active[np.isfinite(active)]
    if len(active) == 0:
        return 0.0
    return float(np.sum(active > 0) / len(active))


# ══════════════════════════════════════════════════════════════
#  1. Brinson-Hood-Beebower Attribution
# ══════════════════════════════════════════════════════════════


def brinson_attribution(
    portfolio_weights: Dict[str, float],
    benchmark_weights: Dict[str, float],
    portfolio_returns: Dict[str, float],
    benchmark_returns: Dict[str, float],
    sector_map: Optional[Dict[str, str]] = None,
) -> Dict:
    """
    Brinson-Hood-Beebower (BHB) performance attribution.

    Decomposes active return into allocation, selection, and interaction
    effects at the sector level.

    Parameters
    ----------
    portfolio_weights : dict
        Ticker -> portfolio weight (should sum to ~1).
    benchmark_weights : dict
        Ticker -> benchmark weight (should sum to ~1).
    portfolio_returns : dict
        Ticker -> return over the period for portfolio holdings.
    benchmark_returns : dict
        Ticker -> return over the period for benchmark holdings.
    sector_map : dict, optional
        Ticker -> sector name. Defaults to DEFAULT_SECTOR_MAP.

    Returns
    -------
    dict
        total_active_return : float
        allocation_effect : float
        selection_effect : float
        interaction_effect : float
        sector_detail : DataFrame with per-sector breakdown
    """
    logger.info(
        "attribution.brinson.start",
        n_portfolio=len(portfolio_weights),
        n_benchmark=len(benchmark_weights),
    )

    if sector_map is None:
        sector_map = DEFAULT_SECTOR_MAP

    # Collect all tickers
    all_tickers = set(portfolio_weights.keys()) | set(benchmark_weights.keys())

    # Assign sectors — tickers without a mapping go to "Other"
    ticker_sectors = {t: sector_map.get(t, "Other") for t in all_tickers}
    sectors = sorted(set(ticker_sectors.values()))

    # Aggregate weights and returns by sector
    # Portfolio: sector weight = sum of ticker weights in that sector
    #            sector return = weighted-average return within sector
    # Benchmark: analogous

    # Total benchmark return (computed once, used in allocation effect for all sectors)
    total_bm_return = sum(
        benchmark_weights.get(t, 0.0) * benchmark_returns.get(t, 0.0) for t in all_tickers
    )

    sector_rows = []

    for sector in sectors:
        # Tickers in this sector
        tickers_in_sector = [t for t in all_tickers if ticker_sectors[t] == sector]

        # Portfolio aggregation
        pw_sector = sum(portfolio_weights.get(t, 0.0) for t in tickers_in_sector)
        pw_return_num = sum(
            portfolio_weights.get(t, 0.0) * portfolio_returns.get(t, 0.0) for t in tickers_in_sector
        )
        # Guard against division by near-zero sector weight to avoid inf/NaN;
        # sectors with negligible total weight get a zero return attribution.
        pr_sector = pw_return_num / pw_sector if abs(pw_sector) > 1e-12 else 0.0

        # Benchmark aggregation
        bw_sector = sum(benchmark_weights.get(t, 0.0) for t in tickers_in_sector)
        bw_return_num = sum(
            benchmark_weights.get(t, 0.0) * benchmark_returns.get(t, 0.0) for t in tickers_in_sector
        )
        # Guard against division by near-zero sector weight to avoid inf/NaN;
        # sectors with negligible total weight get a zero return attribution.
        br_sector = bw_return_num / bw_sector if abs(bw_sector) > 1e-12 else 0.0

        # BHB decomposition per sector
        allocation = (pw_sector - bw_sector) * (br_sector - total_bm_return)
        selection = bw_sector * (pr_sector - br_sector)
        interaction = (pw_sector - bw_sector) * (pr_sector - br_sector)

        sector_rows.append(
            {
                "sector": sector,
                "portfolio_weight": pw_sector,
                "benchmark_weight": bw_sector,
                "weight_diff": pw_sector - bw_sector,
                "portfolio_return": pr_sector,
                "benchmark_return": br_sector,
                "allocation_effect": allocation,
                "selection_effect": selection,
                "interaction_effect": interaction,
                "total_effect": allocation + selection + interaction,
            }
        )

    sector_df = pd.DataFrame(sector_rows).set_index("sector")

    allocation_total = float(sector_df["allocation_effect"].sum())
    selection_total = float(sector_df["selection_effect"].sum())
    interaction_total = float(sector_df["interaction_effect"].sum())
    total_active = allocation_total + selection_total + interaction_total

    logger.info(
        "attribution.brinson.complete",
        total_active_return=round(total_active, 6),
        allocation=round(allocation_total, 6),
        selection=round(selection_total, 6),
        interaction=round(interaction_total, 6),
        n_sectors=len(sectors),
    )

    return {
        "total_active_return": total_active,
        "allocation_effect": allocation_total,
        "selection_effect": selection_total,
        "interaction_effect": interaction_total,
        "sector_detail": sector_df,
    }


# ══════════════════════════════════════════════════════════════
#  2. Factor-Based Attribution (Multi-Factor Regression)
# ══════════════════════════════════════════════════════════════


def factor_attribution(
    returns: Union[pd.Series, np.ndarray],
    factor_returns: pd.DataFrame,
    factor_names: Optional[List[str]] = None,
) -> Dict:
    """
    Multi-factor regression attribution.

    R_portfolio = alpha + sum(beta_i * F_i) + epsilon

    Uses OLS via numpy.linalg.lstsq to decompose portfolio returns into
    factor contributions, alpha, and residual.

    Parameters
    ----------
    returns : Series or 1-D array
        Portfolio daily returns (T observations).
    factor_returns : DataFrame
        T x K DataFrame of daily factor returns. Columns are factor names.
    factor_names : list of str, optional
        Subset of columns to use. If None, all columns are used.

    Returns
    -------
    dict
        alpha : float (annualized)
        factor_betas : dict {factor_name: beta}
        factor_contributions : dict {factor_name: annualized contribution}
        r_squared : float
        residual_return : float (annualized)
        attribution_df : DataFrame summarizing per-factor attribution
    """
    logger.info(
        "attribution.factor.start",
        n_observations=len(returns),
        n_factors=factor_returns.shape[1] if factor_names is None else len(factor_names),
    )

    # Align data
    if isinstance(returns, np.ndarray):
        returns = pd.Series(returns)

    if factor_names is not None:
        factor_returns = factor_returns[factor_names]
    else:
        factor_names = list(factor_returns.columns)

    # Align indices — inner join on dates
    common_idx = returns.dropna().index.intersection(factor_returns.dropna().index)
    y = returns.loc[common_idx].values.astype(float)
    X_factors = factor_returns.loc[common_idx].values.astype(float)

    n_obs = len(y)
    n_factors = X_factors.shape[1]

    if n_obs < n_factors + 2:
        logger.warning(
            "attribution.factor.insufficient_data",
            n_observations=n_obs,
            n_factors=n_factors,
        )
        return {
            "alpha": 0.0,
            "factor_betas": {f: 0.0 for f in factor_names},
            "factor_contributions": {f: 0.0 for f in factor_names},
            "r_squared": 0.0,
            "residual_return": 0.0,
            "attribution_df": pd.DataFrame(),
        }

    # OLS: y = X @ b  where X = [1, F1, F2, ...]
    X = np.column_stack([np.ones(n_obs), X_factors])
    coeffs, residuals, rank, sv = np.linalg.lstsq(X, y, rcond=None)
    if rank < X.shape[1]:
        logger.warning("attribution.factor.rank_deficient", rank=rank, expected=X.shape[1])

    alpha_daily = coeffs[0]
    betas = coeffs[1:]

    # Fitted values and residuals
    y_hat = X @ coeffs
    eps = y - y_hat

    # R-squared
    ss_res = np.sum(eps**2)
    ss_tot = np.sum((y - np.mean(y)) ** 2)
    r_squared = 1.0 - ss_res / ss_tot if ss_tot > 1e-16 else 0.0

    # Factor contributions (annualized)
    factor_means = np.mean(X_factors, axis=0)
    factor_contributions = {}
    factor_betas_dict = {}
    rows = []

    for i, fname in enumerate(factor_names):
        beta_i = float(betas[i])
        contrib_daily = beta_i * factor_means[i]
        contrib_annual = contrib_daily * TRADING_DAYS
        factor_betas_dict[fname] = beta_i
        factor_contributions[fname] = contrib_annual
        rows.append(
            {
                "factor": fname,
                "beta": beta_i,
                "factor_mean_daily": factor_means[i],
                "contribution_daily": contrib_daily,
                "contribution_annual": contrib_annual,
            }
        )

    alpha_annual = float(alpha_daily * TRADING_DAYS)
    residual_annual = float(np.mean(eps) * TRADING_DAYS)

    rows.append(
        {
            "factor": "Alpha",
            "beta": np.nan,
            "factor_mean_daily": np.nan,
            "contribution_daily": alpha_daily,
            "contribution_annual": alpha_annual,
        }
    )
    rows.append(
        {
            "factor": "Residual",
            "beta": np.nan,
            "factor_mean_daily": np.nan,
            "contribution_daily": np.mean(eps),
            "contribution_annual": residual_annual,
        }
    )

    attribution_df = pd.DataFrame(rows).set_index("factor")

    logger.info(
        "attribution.factor.complete",
        alpha_annual=round(alpha_annual, 6),
        r_squared=round(r_squared, 4),
        n_factors=n_factors,
    )

    return {
        "alpha": alpha_annual,
        "factor_betas": factor_betas_dict,
        "factor_contributions": factor_contributions,
        "r_squared": float(r_squared),
        "residual_return": residual_annual,
        "attribution_df": attribution_df,
    }


# ══════════════════════════════════════════════════════════════
#  3. Daily PnL Attribution
# ══════════════════════════════════════════════════════════════


def compute_daily_pnl_attribution(
    weights: pd.Series,
    daily_returns: pd.DataFrame,
) -> pd.DataFrame:
    """
    Compute daily PnL contribution per ticker.

    PnL_contribution_i(t) = weight_i * return_i(t)

    Parameters
    ----------
    weights : Series
        Ticker -> weight (static weights applied across all days).
    daily_returns : DataFrame
        DatetimeIndex x tickers DataFrame of daily returns.

    Returns
    -------
    DataFrame
        DatetimeIndex x (tickers + 'total_return' + 'cumulative_return')
        with daily PnL contributions per ticker and portfolio totals.
    """
    logger.info(
        "attribution.daily_pnl.start",
        n_tickers=len(weights),
        n_days=len(daily_returns),
    )

    # Align weights with available columns
    common_tickers = [t for t in weights.index if t in daily_returns.columns]
    if len(common_tickers) == 0:
        logger.warning("attribution.daily_pnl.no_common_tickers")
        return pd.DataFrame()

    w = weights[common_tickers]
    ret = daily_returns[common_tickers]

    # PnL contribution: weight * daily return
    pnl = ret.multiply(w, axis=1)

    # Total portfolio return per day
    pnl["total_return"] = pnl[common_tickers].sum(axis=1)

    # Cumulative contributions
    # Use log-space computation for numerical stability over long time series
    pnl["cumulative_return"] = np.expm1(np.log1p(pnl["total_return"]).cumsum())

    # Also add cumulative contributions per ticker
    for t in common_tickers:
        pnl[f"{t}_cumulative"] = pnl[t].cumsum()

    logger.info(
        "attribution.daily_pnl.complete",
        n_days=len(pnl),
        total_cumulative=(
            round(float(pnl["cumulative_return"].iloc[-1]), 6) if len(pnl) > 0 else 0.0
        ),
    )

    return pnl


# ══════════════════════════════════════════════════════════════
#  4. Period Attribution (Monthly / Quarterly / Yearly)
# ══════════════════════════════════════════════════════════════


def compute_period_attribution(
    weights: pd.Series,
    returns: pd.DataFrame,
    period: str = "M",
) -> pd.DataFrame:
    """
    Aggregate PnL attribution by calendar period.

    Parameters
    ----------
    weights : Series
        Ticker -> weight.
    returns : DataFrame
        DatetimeIndex x tickers daily returns.
    period : str
        Pandas period alias: 'M' (monthly), 'Q' (quarterly), 'Y' or 'A' (yearly).

    Returns
    -------
    DataFrame
        Period index x tickers with aggregated PnL contribution per period.
        Includes a 'total_return' column.
    """
    logger.info(
        "attribution.period.start",
        n_tickers=len(weights),
        n_days=len(returns),
        period=period,
    )

    # Compute daily PnL contributions
    common_tickers = [t for t in weights.index if t in returns.columns]
    if len(common_tickers) == 0:
        logger.warning("attribution.period.no_common_tickers")
        return pd.DataFrame()

    w = weights[common_tickers]
    daily_pnl = returns[common_tickers].multiply(w, axis=1)
    daily_pnl["total_return"] = daily_pnl[common_tickers].sum(axis=1)

    # Normalize period alias
    period_alias = period.upper()
    if period_alias == "A":
        period_alias = "Y"

    # Group by period and sum daily contributions
    # For compounded returns use: (1+r).prod() - 1, but for linear attribution
    # we sum the daily weighted contributions (first-order approximation).
    period_pnl = daily_pnl.groupby(daily_pnl.index.to_period(period_alias)).sum()

    logger.info(
        "attribution.period.complete",
        n_periods=len(period_pnl),
        period_type=period_alias,
    )

    return period_pnl


# ══════════════════════════════════════════════════════════════
#  5. High-Level Attribution Summary
# ══════════════════════════════════════════════════════════════


def get_attribution_summary(
    weights: pd.Series,
    returns: pd.DataFrame,
    benchmark_ticker: str = "SPY",
    sector_map: Optional[Dict[str, str]] = None,
) -> Dict:
    """
    High-level convenience function that runs Brinson and factor attribution,
    computes tracking error, information ratio, and hit ratio.

    Parameters
    ----------
    weights : Series
        Ticker -> portfolio weight.
    returns : DataFrame
        DatetimeIndex x tickers daily returns. Must include the benchmark ticker
        as a column (or it will be skipped for Brinson).
    benchmark_ticker : str
        Column name for the benchmark in `returns`.
    sector_map : dict, optional
        Ticker -> sector. Defaults to DEFAULT_SECTOR_MAP.

    Returns
    -------
    dict
        brinson : dict (Brinson attribution results, or None)
        factor : dict (factor attribution results, or None)
        tracking_error : float
        information_ratio : float
        hit_ratio : float
        active_return_annual : float
        daily_pnl : DataFrame
        monthly_pnl : DataFrame
    """
    logger.info(
        "attribution.summary.start",
        n_tickers=len(weights),
        n_days=len(returns),
        benchmark=benchmark_ticker,
    )

    if sector_map is None:
        sector_map = DEFAULT_SECTOR_MAP

    result: Dict = {}
    portfolio_tickers = [t for t in weights.index if t in returns.columns]

    # ── Portfolio daily returns ────────────────────────────────
    w_aligned = weights[portfolio_tickers]
    port_daily = returns[portfolio_tickers].dot(w_aligned)

    # ── Benchmark daily returns ────────────────────────────────
    has_benchmark = benchmark_ticker in returns.columns
    if has_benchmark:
        bench_daily = returns[benchmark_ticker]
        active_daily = port_daily - bench_daily
        active_daily = active_daily.dropna()
    else:
        logger.warning(
            "attribution.summary.no_benchmark",
            benchmark=benchmark_ticker,
        )
        active_daily = port_daily  # treat as absolute returns

    # ── Tracking error, IR, hit ratio ──────────────────────────
    result["tracking_error"] = _tracking_error(active_daily)
    result["information_ratio"] = _information_ratio(active_daily)
    result["hit_ratio"] = _hit_ratio(active_daily)
    result["active_return_annual"] = float(np.mean(active_daily) * TRADING_DAYS)

    # ── Brinson attribution (period-level) ─────────────────────
    brinson_result = None
    if has_benchmark:
        try:
            # Use cumulative returns over the full period for Brinson
            period_returns = {}
            for t in portfolio_tickers:
                col = returns[t].dropna()
                if len(col) > 0:
                    period_returns[t] = float((1 + col).prod() - 1)

            bench_tickers = [benchmark_ticker]
            # Build equal-weight benchmark weights and returns
            # If benchmark is a single ETF, it gets weight 1.0
            bm_weights = {benchmark_ticker: 1.0}
            bm_returns = {}
            bm_col = returns[benchmark_ticker].dropna()
            if len(bm_col) > 0:
                bm_returns[benchmark_ticker] = float((1 + bm_col).prod() - 1)

            # Build portfolio weights dict
            pw_dict = {t: float(w_aligned[t]) for t in portfolio_tickers}

            brinson_result = brinson_attribution(
                portfolio_weights=pw_dict,
                benchmark_weights=bm_weights,
                portfolio_returns=period_returns,
                benchmark_returns=bm_returns,
                sector_map=sector_map,
            )
        except Exception as e:
            logger.error("attribution.summary.brinson_failed", error=str(e))
            brinson_result = None

    result["brinson"] = brinson_result

    # ── Factor attribution ─────────────────────────────────────
    factor_result = None
    # Use benchmark and common factor ETFs available in the returns DataFrame
    factor_candidates = ["SPY", "QQQ", "GLD", "TLT", "IWM", "VTV"]
    available_factors = [f for f in factor_candidates if f in returns.columns]

    if len(available_factors) > 0:
        try:
            factor_ret_df = returns[available_factors].copy()
            factor_result = factor_attribution(
                returns=port_daily,
                factor_returns=factor_ret_df,
                factor_names=available_factors,
            )
        except Exception as e:
            logger.error("attribution.summary.factor_failed", error=str(e))
            factor_result = None

    result["factor"] = factor_result

    # ── Daily and monthly PnL ──────────────────────────────────
    try:
        result["daily_pnl"] = compute_daily_pnl_attribution(w_aligned, returns)
    except Exception as e:
        logger.error("attribution.summary.daily_pnl_failed", error=str(e))
        result["daily_pnl"] = pd.DataFrame()

    try:
        result["monthly_pnl"] = compute_period_attribution(w_aligned, returns, period="M")
    except Exception as e:
        logger.error("attribution.summary.monthly_pnl_failed", error=str(e))
        result["monthly_pnl"] = pd.DataFrame()

    logger.info(
        "attribution.summary.complete",
        tracking_error=round(result["tracking_error"], 6),
        information_ratio=round(result["information_ratio"], 4),
        hit_ratio=round(result["hit_ratio"], 4),
        active_return_annual=round(result["active_return_annual"], 6),
        has_brinson=brinson_result is not None,
        has_factor=factor_result is not None,
    )

    return result
