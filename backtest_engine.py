"""
backtest_engine.py
Vectorized Portfolio Backtesting Engine v1.0
--------------------------------------------------------------
Fast, numpy-based backtesting for portfolio strategies.
Supports static-weight, momentum, and equal-weight strategies
with configurable rebalance frequency and benchmark comparison.
"""

import numpy as np
import pandas as pd
import yfinance as yf
import warnings
import os
import pickle
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Union
from datetime import datetime, timedelta

from logging_config import get_logger

logger = get_logger(__name__)

# ══════════════════════════════════════════════════════════════
#  Price data cache
# ══════════════════════════════════════════════════════════════
_PRICE_CACHE: Dict[str, pd.DataFrame] = {}
_CACHE_DIR = ".cache/backtest_data"
os.makedirs(_CACHE_DIR, exist_ok=True)


def _cache_key(ticker: str, start: str, end: str) -> str:
    """Generate a deterministic cache key."""
    safe = ticker.replace("/", "_").replace("^", "").replace("=", "")
    return f"{safe}_{start}_{end}"


def _download_prices(
    tickers: List[str],
    start_date: str,
    end_date: str,
    force_refresh: bool = False,
    max_age_hours: int = 24,
) -> pd.DataFrame:
    """
    Download adjusted close prices for *tickers* via yfinance.

    Results are cached in-memory and on disk (pickle) to avoid
    redundant network round-trips within a single session or across
    short-lived reruns.

    Returns
    -------
    pd.DataFrame
        Columns = tickers, Index = DatetimeIndex (trading days).
        Tickers that fail to download are silently omitted.
    """
    t0 = time.time()
    needed: List[str] = []
    frames: Dict[str, pd.Series] = {}

    for tk in tickers:
        key = _cache_key(tk, start_date, end_date)

        # 1. In-memory cache
        if not force_refresh and key in _PRICE_CACHE:
            frames[tk] = _PRICE_CACHE[key]
            continue

        # 2. On-disk cache
        disk_path = os.path.join(_CACHE_DIR, f"{key}.pkl")
        if not force_refresh and os.path.exists(disk_path):
            age = datetime.now() - datetime.fromtimestamp(os.path.getmtime(disk_path))
            if age < timedelta(hours=max_age_hours):
                try:
                    with open(disk_path, "rb") as fh:
                        series = pickle.load(fh)
                    _PRICE_CACHE[key] = series
                    frames[tk] = series
                    logger.info("backtest.cache.hit", ticker=tk)
                    continue
                except Exception:
                    pass  # fall through to download

        needed.append(tk)

    # 3. Batch download anything still missing
    if needed:
        logger.info(
            "backtest.download.start",
            tickers=needed,
            start=start_date,
            end=end_date,
        )
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                raw = yf.download(
                    needed,
                    start=start_date,
                    end=end_date,
                    auto_adjust=True,
                    progress=False,
                )
        except Exception as exc:
            logger.error("backtest.download.failed", error=str(exc))
            raw = pd.DataFrame()

        if not raw.empty:
            # yfinance returns MultiIndex columns when len(tickers) > 1
            for tk in needed:
                try:
                    if isinstance(raw.columns, pd.MultiIndex):
                        if "Close" in raw.columns.get_level_values(0):
                            col = raw["Close"]
                        else:
                            col = raw
                        if isinstance(col, pd.DataFrame):
                            if tk in col.columns:
                                series = col[tk].dropna()
                            else:
                                continue
                        else:
                            series = col.dropna()
                    else:
                        if len(needed) == 1:
                            if "Close" in raw.columns:
                                series = raw["Close"].dropna()
                            else:
                                series = raw.iloc[:, 0].dropna()
                        elif tk in raw.columns:
                            series = raw[tk].dropna()
                        else:
                            continue

                    if len(series) < 2:
                        logger.warning("backtest.download.insufficient", ticker=tk, rows=len(series))
                        continue

                    key = _cache_key(tk, start_date, end_date)
                    _PRICE_CACHE[key] = series
                    frames[tk] = series

                    # persist to disk
                    disk_path = os.path.join(_CACHE_DIR, f"{key}.pkl")
                    try:
                        with open(disk_path, "wb") as fh:
                            pickle.dump(series, fh)
                    except Exception:
                        pass

                except Exception as exc:
                    logger.warning("backtest.download.ticker_error", ticker=tk, error=str(exc))

    elapsed_ms = (time.time() - t0) * 1000
    logger.info(
        "backtest.download.complete",
        requested=len(tickers),
        obtained=len(frames),
        duration_ms=round(elapsed_ms, 2),
    )

    if not frames:
        raise ValueError(
            f"Failed to download price data for any of: {tickers}. "
            "Check network connection and ticker symbols."
        )

    prices = pd.DataFrame(frames)
    prices = prices.ffill().dropna(how="all")
    return prices


# ══════════════════════════════════════════════════════════════
#  Performance metrics helpers
# ══════════════════════════════════════════════════════════════
TRADING_DAYS_PER_YEAR = 252


def _sharpe_ratio(returns: pd.Series, rf: float = 0.045) -> float:
    """
    Annualized Sharpe ratio.

    Parameters
    ----------
    returns : pd.Series
        Daily simple returns (not log returns).
    rf : float
        Annual risk-free rate (default 4.5 %).
    """
    if len(returns) < 2 or returns.std() == 0:
        return 0.0
    daily_rf = rf / TRADING_DAYS_PER_YEAR
    excess = returns - daily_rf
    if excess.std() < 1e-10:
        return 0.0
    return float(np.sqrt(TRADING_DAYS_PER_YEAR) * excess.mean() / excess.std())


def _sortino_ratio(returns: pd.Series, rf: float = 0.045) -> float:
    """
    Annualized Sortino ratio (downside deviation in denominator).
    """
    if len(returns) < 2:
        return 0.0
    daily_rf = rf / TRADING_DAYS_PER_YEAR
    excess = returns - daily_rf
    downside = excess[excess < 0]
    if len(downside) == 0:
        return float('inf') if excess.mean() > 0 else 0.0
    if downside.std() == 0:
        return 0.0
    return float(np.sqrt(TRADING_DAYS_PER_YEAR) * excess.mean() / downside.std())


def _calmar_ratio(annual_return: float, max_drawdown: float) -> float:
    """Calmar ratio = annualized return / max drawdown."""
    if max_drawdown == 0:
        return 0.0
    return float(annual_return / abs(max_drawdown))


def _max_drawdown(equity_curve: pd.Series) -> float:
    """
    Maximum drawdown as a negative fraction (e.g. -0.25 means -25 %).

    Parameters
    ----------
    equity_curve : pd.Series
        Cumulative portfolio value (not returns).

    Returns
    -------
    float  (negative or zero)
    """
    if len(equity_curve) < 2:
        return 0.0
    running_max = equity_curve.cummax()
    running_max = running_max.replace(0, np.nan)
    drawdown = (equity_curve - running_max) / running_max
    result = float(drawdown.min())
    return result if not np.isnan(result) else 0.0


def _drawdown_series(equity_curve: pd.Series) -> pd.Series:
    """Percentage drawdown at every point in time (non-positive values)."""
    running_max = equity_curve.cummax()
    dd = (equity_curve - running_max) / running_max
    dd.name = "drawdown"
    return dd


def _alpha_beta(
    portfolio_returns: pd.Series,
    benchmark_returns: pd.Series,
) -> Tuple[float, float]:
    """
    OLS regression of portfolio returns on benchmark returns.

    Returns (annualized alpha, beta).
    """
    # Align on common dates
    aligned = pd.concat(
        [portfolio_returns.rename("port"), benchmark_returns.rename("bench")],
        axis=1,
    ).dropna()

    if len(aligned) < 10:
        return 0.0, 0.0

    y = aligned["port"].values
    x = aligned["bench"].values
    x_with_const = np.column_stack([np.ones(len(x)), x])

    # OLS via normal equations
    try:
        coeffs = np.linalg.lstsq(x_with_const, y, rcond=None)[0]
    except np.linalg.LinAlgError:
        return 0.0, 0.0

    daily_alpha = coeffs[0]
    beta = coeffs[1]
    annual_alpha = daily_alpha * TRADING_DAYS_PER_YEAR
    return float(annual_alpha), float(beta)


def _win_rate(returns: pd.Series) -> float:
    """Fraction of days with positive returns."""
    if len(returns) == 0:
        return 0.0
    return float((returns > 0).sum() / len(returns))


# ══════════════════════════════════════════════════════════════
#  BacktestResult container
# ══════════════════════════════════════════════════════════════
@dataclass
class BacktestResult:
    """Immutable container for a single backtest run."""

    # Scalar metrics
    total_return: float = 0.0
    annual_return: float = 0.0
    annual_volatility: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0
    calmar_ratio: float = 0.0
    sortino_ratio: float = 0.0
    win_rate: float = 0.0
    num_trades: int = 0
    start_date: Optional[str] = None
    end_date: Optional[str] = None

    # Series / DataFrame fields
    equity_curve: Optional[pd.Series] = field(default=None, repr=False)
    drawdown_series: Optional[pd.Series] = field(default=None, repr=False)
    monthly_returns: Optional[pd.Series] = field(default=None, repr=False)

    # Benchmark comparison
    benchmark_total_return: Optional[float] = None
    alpha: float = 0.0
    beta: float = 0.0

    # Strategy metadata
    strategy_name: str = ""
    weights: Optional[Dict[str, float]] = field(default=None, repr=False)


# ══════════════════════════════════════════════════════════════
#  Rebalance-date generation
# ══════════════════════════════════════════════════════════════
def _rebalance_dates(
    index: pd.DatetimeIndex,
    freq: str,
) -> List[pd.Timestamp]:
    """
    Return a sorted list of dates from *index* on which the portfolio
    should be rebalanced.

    Parameters
    ----------
    freq : str
        'D' = daily, 'W' = weekly (every Monday), 'M' = monthly
        (first trading day), 'Q' = quarterly, 'N' = never (only at start).
    """
    freq = freq.upper()
    dates = index.sort_values()

    if freq == "D":
        return list(dates)
    elif freq == "N":
        return [dates[0]]
    elif freq == "W":
        # First trading day of each ISO week
        groups = dates.to_series().groupby([dates.isocalendar().year, dates.isocalendar().week])
        return [g.index[0] for _, g in groups]
    elif freq == "M":
        groups = dates.to_series().groupby([dates.year, dates.month])
        return [g.index[0] for _, g in groups]
    elif freq == "Q":
        groups = dates.to_series().groupby([dates.year, dates.quarter])
        return [g.index[0] for _, g in groups]
    else:
        raise ValueError(f"Unknown rebalance frequency: {freq!r}. Use D/W/M/Q/N.")


# ══════════════════════════════════════════════════════════════
#  Core simulation engine (vectorized between rebalances)
# ══════════════════════════════════════════════════════════════
def _simulate_portfolio(
    prices: pd.DataFrame,
    weight_schedule: Dict[pd.Timestamp, Dict[str, float]],
    initial_capital: float,
) -> Tuple[pd.Series, int]:
    """
    Simulate a portfolio given a weight schedule.

    Parameters
    ----------
    prices : pd.DataFrame
        Adjusted close prices (date x ticker).
    weight_schedule : dict
        {rebalance_date: {ticker: weight, ...}, ...}
        Dates must be a subset of prices.index.
    initial_capital : float
        Starting portfolio value.

    Returns
    -------
    (equity_curve, num_trades)
        equity_curve is a pd.Series indexed by dates.
        num_trades is the total number of individual asset trades executed.
    """
    dates = prices.index.sort_values()
    tickers = prices.columns.tolist()

    # Pre-compute daily return matrix (date x ticker), first row is 0
    daily_returns = prices.pct_change().fillna(0.0).values  # ndarray
    ticker_idx = {tk: i for i, tk in enumerate(tickers)}

    n_days = len(dates)
    equity = np.empty(n_days, dtype=np.float64)
    equity[0] = initial_capital

    # Sort rebalance dates
    reb_dates = sorted(weight_schedule.keys())

    # Current weight vector (n_tickers,)
    current_weights = np.zeros(len(tickers), dtype=np.float64)
    num_trades = 0

    for i in range(n_days):
        dt = dates[i]

        # Apply rebalance if this date is a rebalance date
        if dt in weight_schedule:
            new_w = weight_schedule[dt]
            new_vec = np.zeros(len(tickers), dtype=np.float64)
            for tk, w in new_w.items():
                if tk in ticker_idx:
                    new_vec[ticker_idx[tk]] = w

            # Count trades: any position that changed
            if i == 0 or not np.allclose(current_weights, new_vec, atol=1e-8):
                changes = np.abs(new_vec - current_weights)
                num_trades += int((changes > 1e-8).sum())
                current_weights = new_vec.copy()

        if i == 0:
            equity[i] = initial_capital
        else:
            # Portfolio return for this day = sum(weight_j * return_j)
            day_ret = daily_returns[i]
            port_ret = current_weights @ day_ret
            equity[i] = equity[i - 1] * (1.0 + port_ret)

            # Drift weights according to price moves (before next rebalance)
            # w_new_j = w_old_j * (1 + r_j) / (1 + r_port)
            if 1.0 + port_ret != 0:
                current_weights = current_weights * (1.0 + day_ret) / (1.0 + port_ret)

    equity_series = pd.Series(equity, index=dates, name="portfolio_value")
    return equity_series, num_trades


def _build_result(
    equity_curve: pd.Series,
    num_trades: int,
    benchmark_equity: Optional[pd.Series],
    strategy_name: str,
    weights: Optional[Dict[str, float]] = None,
) -> BacktestResult:
    """Populate a BacktestResult from an equity curve."""
    daily_returns = equity_curve.pct_change().dropna()

    n_years = len(equity_curve) / TRADING_DAYS_PER_YEAR
    total_ret = (equity_curve.iloc[-1] / equity_curve.iloc[0]) - 1.0
    annual_ret = (1.0 + total_ret) ** (1.0 / max(n_years, 1e-6)) - 1.0 if n_years > 0 else 0.0
    annual_vol = float(daily_returns.std() * np.sqrt(TRADING_DAYS_PER_YEAR)) if len(daily_returns) > 1 else 0.0
    mdd = _max_drawdown(equity_curve)
    dd_series = _drawdown_series(equity_curve)

    # Monthly returns
    monthly_eq = equity_curve.resample("ME").last().dropna()
    monthly_rets = monthly_eq.pct_change().dropna()
    monthly_rets.name = "monthly_return"

    # Benchmark comparison
    bench_total = None
    alpha = 0.0
    beta = 0.0
    if benchmark_equity is not None and len(benchmark_equity) > 10:
        bench_total = float(benchmark_equity.iloc[-1] / benchmark_equity.iloc[0] - 1.0)
        bench_returns = benchmark_equity.pct_change().dropna()
        alpha, beta = _alpha_beta(daily_returns, bench_returns)

    return BacktestResult(
        total_return=float(total_ret),
        annual_return=float(annual_ret),
        annual_volatility=annual_vol,
        sharpe_ratio=_sharpe_ratio(daily_returns),
        max_drawdown=mdd,
        calmar_ratio=_calmar_ratio(annual_ret, mdd),
        sortino_ratio=_sortino_ratio(daily_returns),
        win_rate=_win_rate(daily_returns),
        num_trades=num_trades,
        start_date=str(equity_curve.index[0].date()),
        end_date=str(equity_curve.index[-1].date()),
        equity_curve=equity_curve,
        drawdown_series=dd_series,
        monthly_returns=monthly_rets,
        benchmark_total_return=bench_total,
        alpha=alpha,
        beta=beta,
        strategy_name=strategy_name,
        weights=weights,
    )


# ══════════════════════════════════════════════════════════════
#  Public API: run_backtest (static weights)
# ══════════════════════════════════════════════════════════════
def run_backtest(
    weights: Dict[str, float],
    start_date: str,
    end_date: str,
    initial_capital: float = 100_000,
    rebalance_freq: str = "M",
    benchmark: str = "SPY",
) -> BacktestResult:
    """
    Backtest a portfolio with fixed target weights.

    Parameters
    ----------
    weights : dict
        {ticker: target_weight}  weights should sum to ~1.0.
    start_date, end_date : str
        'YYYY-MM-DD' date boundaries.
    initial_capital : float
        Starting cash.
    rebalance_freq : str
        'D' daily, 'W' weekly, 'M' monthly, 'Q' quarterly, 'N' never.
    benchmark : str
        Ticker for the benchmark (e.g. 'SPY').  Set to '' or None to skip.

    Returns
    -------
    BacktestResult
    """
    logger.info(
        "backtest.static.start",
        tickers=list(weights.keys()),
        start=start_date,
        end=end_date,
        rebalance_freq=rebalance_freq,
        initial_capital=initial_capital,
    )
    t0 = time.time()

    all_tickers = list(weights.keys())
    if benchmark:
        all_tickers = list(set(all_tickers + [benchmark]))

    prices = _download_prices(all_tickers, start_date, end_date)

    # Separate benchmark prices
    bench_equity = None
    if benchmark and benchmark in prices.columns:
        bench_prices = prices[benchmark]
        bench_equity = bench_prices / bench_prices.iloc[0] * initial_capital
        bench_equity.name = "benchmark"

    # Keep only portfolio tickers that were successfully downloaded
    port_tickers = [t for t in weights if t in prices.columns]
    if not port_tickers:
        raise ValueError(f"None of the portfolio tickers could be downloaded: {list(weights.keys())}")
    port_prices = prices[port_tickers]

    # Re-normalize weights to downloaded tickers
    raw_sum = sum(weights[t] for t in port_tickers)
    norm_weights = {t: weights[t] / raw_sum for t in port_tickers} if raw_sum > 0 else {t: 1.0 / len(port_tickers) for t in port_tickers}

    # Build weight schedule
    reb_dates = _rebalance_dates(port_prices.index, rebalance_freq)
    schedule = {dt: norm_weights for dt in reb_dates}

    equity_curve, num_trades = _simulate_portfolio(port_prices, schedule, initial_capital)

    result = _build_result(equity_curve, num_trades, bench_equity, "static_weight", norm_weights)

    elapsed = (time.time() - t0) * 1000
    logger.info(
        "backtest.static.complete",
        total_return=round(result.total_return, 4),
        sharpe=round(result.sharpe_ratio, 3),
        max_dd=round(result.max_drawdown, 4),
        duration_ms=round(elapsed, 2),
    )
    return result


# ══════════════════════════════════════════════════════════════
#  Public API: run_momentum_backtest
# ══════════════════════════════════════════════════════════════
def run_momentum_backtest(
    universe: List[str],
    start_date: str,
    end_date: str,
    lookback: int = 252,
    top_n: int = 5,
    rebalance_freq: str = "M",
    initial_capital: float = 100_000,
    benchmark: str = "SPY",
) -> BacktestResult:
    """
    Momentum strategy: at each rebalance, pick *top_n* tickers from
    *universe* ranked by trailing *lookback*-day total return, then
    equal-weight them.

    Parameters
    ----------
    universe : list[str]
        Ticker universe to select from.
    lookback : int
        Number of trading days to measure trailing return.
    top_n : int
        How many tickers to hold.
    """
    logger.info(
        "backtest.momentum.start",
        universe_size=len(universe),
        lookback=lookback,
        top_n=top_n,
        rebalance_freq=rebalance_freq,
    )
    t0 = time.time()

    # We need extra history for the lookback window
    # Add ~1.5x lookback calendar days before start_date
    extra_days = int(lookback * 1.5)
    padded_start = (pd.Timestamp(start_date) - timedelta(days=extra_days)).strftime("%Y-%m-%d")

    all_tickers = list(set(universe + ([benchmark] if benchmark else [])))
    prices = _download_prices(all_tickers, padded_start, end_date)

    # Filter to available universe tickers
    avail_universe = [t for t in universe if t in prices.columns]
    if len(avail_universe) < top_n:
        raise ValueError(
            f"Only {len(avail_universe)} tickers available from universe, "
            f"but top_n={top_n} requested."
        )

    # Trim to actual backtest period for scheduling
    bt_start = pd.Timestamp(start_date)
    bt_mask = prices.index >= bt_start
    bt_prices_full = prices  # keep full history for lookback
    bt_index = prices.index[bt_mask]

    if len(bt_index) < 2:
        raise ValueError("Not enough trading days in the specified date range.")

    # Determine rebalance dates within the backtest window
    reb_dates = _rebalance_dates(bt_index, rebalance_freq)

    # Build dynamic weight schedule
    schedule: Dict[pd.Timestamp, Dict[str, float]] = {}
    for dt in reb_dates:
        loc = bt_prices_full.index.get_loc(dt)
        if loc < lookback:
            # Not enough history yet -- equal weight all available
            w = 1.0 / len(avail_universe)
            schedule[dt] = {tk: w for tk in avail_universe}
            continue

        # Compute trailing return for each ticker
        trailing_returns = {}
        for tk in avail_universe:
            p_now = bt_prices_full[tk].iloc[loc]
            p_past = bt_prices_full[tk].iloc[loc - lookback]
            if pd.notna(p_now) and pd.notna(p_past) and p_past > 0:
                trailing_returns[tk] = p_now / p_past - 1.0

        # Rank and pick top_n
        if len(trailing_returns) < top_n:
            selected = list(trailing_returns.keys())
        else:
            ranked = sorted(trailing_returns.items(), key=lambda x: x[1], reverse=True)
            selected = [tk for tk, _ in ranked[:top_n]]

        w = 1.0 / len(selected) if selected else 0.0
        schedule[dt] = {tk: w for tk in selected}

    # Simulate on the backtest-period prices only
    # We need all universe tickers in the price frame
    sim_prices = prices.loc[bt_mask, avail_universe]
    equity_curve, num_trades = _simulate_portfolio(sim_prices, schedule, initial_capital)

    # Benchmark
    bench_equity = None
    if benchmark and benchmark in prices.columns:
        bp = prices.loc[bt_mask, benchmark]
        bench_equity = bp / bp.iloc[0] * initial_capital

    result = _build_result(equity_curve, num_trades, bench_equity, "momentum", None)

    elapsed = (time.time() - t0) * 1000
    logger.info(
        "backtest.momentum.complete",
        total_return=round(result.total_return, 4),
        sharpe=round(result.sharpe_ratio, 3),
        duration_ms=round(elapsed, 2),
    )
    return result


# ══════════════════════════════════════════════════════════════
#  Public API: run_equal_weight_backtest
# ══════════════════════════════════════════════════════════════
def run_equal_weight_backtest(
    tickers: List[str],
    start_date: str,
    end_date: str,
    rebalance_freq: str = "M",
    initial_capital: float = 100_000,
    benchmark: str = "SPY",
) -> BacktestResult:
    """
    Equal-weight strategy: hold all *tickers* at 1/N weight,
    rebalanced at *rebalance_freq*.
    """
    logger.info(
        "backtest.equal_weight.start",
        tickers=tickers,
        rebalance_freq=rebalance_freq,
    )

    weights = {tk: 1.0 / len(tickers) for tk in tickers}
    result = run_backtest(
        weights=weights,
        start_date=start_date,
        end_date=end_date,
        initial_capital=initial_capital,
        rebalance_freq=rebalance_freq,
        benchmark=benchmark,
    )
    result.strategy_name = "equal_weight"
    return result


# ══════════════════════════════════════════════════════════════
#  Rolling metrics
# ══════════════════════════════════════════════════════════════
def compute_rolling_metrics(
    equity_curve: pd.Series,
    window: int = 252,
    rf: float = 0.045,
) -> pd.DataFrame:
    """
    Compute rolling performance metrics over a trailing *window*.

    Parameters
    ----------
    equity_curve : pd.Series
        Daily portfolio value.
    window : int
        Rolling window in trading days (default 252 = ~1 year).
    rf : float
        Annualized risk-free rate for Sharpe computation.

    Returns
    -------
    pd.DataFrame
        Columns: rolling_sharpe, rolling_volatility, rolling_max_drawdown.
    """
    daily_returns = equity_curve.pct_change().dropna()
    daily_rf = rf / TRADING_DAYS_PER_YEAR

    # Rolling volatility (annualized)
    rolling_vol = daily_returns.rolling(window).std() * np.sqrt(TRADING_DAYS_PER_YEAR)

    # Rolling Sharpe
    rolling_mean_excess = (daily_returns - daily_rf).rolling(window).mean()
    rolling_std = daily_returns.rolling(window).std()
    rolling_sharpe = np.sqrt(TRADING_DAYS_PER_YEAR) * rolling_mean_excess / rolling_std
    # Avoid inf where std == 0
    rolling_sharpe = rolling_sharpe.replace([np.inf, -np.inf], np.nan)

    # Rolling max drawdown
    def _roll_mdd(window_vals):
        if len(window_vals) < 2:
            return 0.0
        cumulative = (1.0 + window_vals).cumprod()
        peak = cumulative.cummax()
        dd = (cumulative - peak) / peak
        return dd.min()

    rolling_mdd = daily_returns.rolling(window).apply(_roll_mdd, raw=False)

    metrics = pd.DataFrame(
        {
            "rolling_sharpe": rolling_sharpe,
            "rolling_volatility": rolling_vol,
            "rolling_max_drawdown": rolling_mdd,
        },
        index=daily_returns.index,
    )
    return metrics


# ══════════════════════════════════════════════════════════════
#  Strategy comparison
# ══════════════════════════════════════════════════════════════
def compare_strategies(
    results: List[BacktestResult],
    names: Optional[List[str]] = None,
) -> pd.DataFrame:
    """
    Create a side-by-side comparison DataFrame for multiple backtest results.

    Parameters
    ----------
    results : list[BacktestResult]
        Backtest results to compare.
    names : list[str], optional
        Display names; defaults to each result's strategy_name.

    Returns
    -------
    pd.DataFrame
        Rows = metric names, Columns = strategy names.
    """
    if names is None:
        names = []
        for i, r in enumerate(results):
            n = r.strategy_name if r.strategy_name else f"strategy_{i}"
            names.append(n)

    rows = {}
    for name, r in zip(names, results):
        rows[name] = {
            "Total Return": f"{r.total_return:.2%}",
            "Annual Return": f"{r.annual_return:.2%}",
            "Annual Volatility": f"{r.annual_volatility:.2%}",
            "Sharpe Ratio": f"{r.sharpe_ratio:.3f}",
            "Sortino Ratio": f"{r.sortino_ratio:.3f}",
            "Calmar Ratio": f"{r.calmar_ratio:.3f}",
            "Max Drawdown": f"{r.max_drawdown:.2%}",
            "Win Rate": f"{r.win_rate:.2%}",
            "Num Trades": r.num_trades,
            "Start Date": r.start_date,
            "End Date": r.end_date,
            "Benchmark Return": f"{r.benchmark_total_return:.2%}" if r.benchmark_total_return is not None else "N/A",
            "Alpha (ann.)": f"{r.alpha:.4f}",
            "Beta": f"{r.beta:.3f}",
        }

    df = pd.DataFrame(rows)
    return df


# ══════════════════════════════════════════════════════════════
#  Quick-run convenience (for testing / CLI)
# ══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    from logging_config import setup_logging

    setup_logging()

    print("=" * 60)
    print(" Portfolio Backtesting Engine -- Quick Demo")
    print("=" * 60)

    # 1. Static weight backtest
    demo_weights = {"AAPL": 0.3, "MSFT": 0.3, "GOOGL": 0.2, "AMZN": 0.2}
    print("\n[1] Static weight backtest")
    result_static = run_backtest(
        weights=demo_weights,
        start_date="2022-01-01",
        end_date="2024-12-31",
        rebalance_freq="M",
    )
    print(f"    Total Return: {result_static.total_return:.2%}")
    print(f"    Sharpe Ratio: {result_static.sharpe_ratio:.3f}")
    print(f"    Max Drawdown: {result_static.max_drawdown:.2%}")
    print(f"    Alpha: {result_static.alpha:.4f}  Beta: {result_static.beta:.3f}")

    # 2. Equal weight backtest
    print("\n[2] Equal weight backtest")
    result_ew = run_equal_weight_backtest(
        tickers=["AAPL", "MSFT", "GOOGL", "AMZN"],
        start_date="2022-01-01",
        end_date="2024-12-31",
        rebalance_freq="M",
    )
    print(f"    Total Return: {result_ew.total_return:.2%}")
    print(f"    Sharpe Ratio: {result_ew.sharpe_ratio:.3f}")

    # 3. Momentum backtest
    print("\n[3] Momentum backtest (top 3 of 8)")
    result_mom = run_momentum_backtest(
        universe=["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "NFLX"],
        start_date="2022-01-01",
        end_date="2024-12-31",
        lookback=126,
        top_n=3,
        rebalance_freq="M",
    )
    print(f"    Total Return: {result_mom.total_return:.2%}")
    print(f"    Sharpe Ratio: {result_mom.sharpe_ratio:.3f}")

    # 4. Compare all
    print("\n[4] Strategy comparison")
    comparison = compare_strategies(
        [result_static, result_ew, result_mom],
        names=["Static Weight", "Equal Weight", "Momentum Top-3"],
    )
    print(comparison.to_string())

    # 5. Rolling metrics
    print("\n[5] Rolling metrics (last 5 rows)")
    rolling = compute_rolling_metrics(result_static.equity_curve, window=63)
    print(rolling.dropna().tail().to_string())

    print("\nDone.")
