"""
risk_engine.py
Deterministic portfolio risk engine v2.1
──────────────────────────────────────────────────────────
Added: macro sensitivity (Macro Beta) · liquidity risk (Days to Liquidate)
Retained: EWMA dynamic covariance · dynamic risk-free rate · multi-factor Beta
      margin call alerts · Markowitz efficient frontier · component VaR · drawdown stats
"""

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
from scipy.optimize import minimize

from data_provider import DataProvider
from logging_config import get_logger

logger = get_logger(__name__)


# ══════════════════════════════════════════════════════════════
#  Risk report data container
# ══════════════════════════════════════════════════════════════
@dataclass
class RiskReport:
    """Container for the results of a single risk computation."""

    # VaR
    var_95: float = 0.0
    var_99: float = 0.0
    cvar_95: float = 0.0
    # Basic statistics
    annual_return: float = 0.0
    annual_volatility: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0
    # Beta (relative to benchmark)
    betas: Dict[str, float] = field(default_factory=dict)
    # Multi-factor Beta (SPY/QQQ/GLD/TLT) — per-asset beta matrix for each factor (index=ticker)
    factor_betas: Optional[pd.DataFrame] = None
    # Multi-factor Beta statistical-significance info
    factor_betas_significance: Optional[pd.DataFrame] = None
    # Portfolio-level factor exposure: univariate regression of portfolio returns on each factor
    # (index=factor ticker, columns=[beta, r_squared, t_stat, p_value])
    portfolio_factor_betas: Optional[pd.DataFrame] = None
    # Covariance & correlation matrices (EWMA)
    cov_matrix: Optional[pd.DataFrame] = None
    cov_matrix_ewma: Optional[pd.DataFrame] = None
    corr_matrix: Optional[pd.DataFrame] = None
    corr_matrix_ewma: Optional[pd.DataFrame] = None
    # Monte Carlo simulation paths
    mc_portfolio_returns: Optional[np.ndarray] = None
    # Stress test
    stress_loss: float = 0.0
    stress_asset_losses: Dict[str, float] = field(default_factory=dict)
    # Actual market_shock used when computing stress_loss (so UI/AI/exports
    # report the same number the engine used, not a mismatched default).
    stress_market_shock: float = -0.10
    # Drawdown series
    drawdown_series: Optional[pd.Series] = None
    # Component VaR contributions
    component_var_pct: Optional[pd.Series] = None
    # Rolling correlation
    rolling_corr_with_port: Optional[pd.DataFrame] = None
    # Drawdown statistics
    drawdown_stats: Optional[dict] = None
    # Dynamic risk-free rate
    risk_free_rate: float = np.nan
    # Margin call alert
    margin_call_info: Optional[dict] = None
    # Efficient frontier
    efficient_frontier: Optional[dict] = None

    # ── v2.1 additions ────────────────────────────────────────
    # Macro sensitivity Beta (portfolio regression coefficients vs. rates / USD / oil)
    macro_betas: Optional[dict] = None
    # Liquidity risk (days-to-liquidate and ADV per asset)
    liquidity_risk: Optional[pd.DataFrame] = None


# ══════════════════════════════════════════════════════════════
#  Risk engine
# ══════════════════════════════════════════════════════════════
class RiskEngine:
    """Deterministic portfolio risk-computation engine."""

    TRADING_DAYS = 252
    EWMA_LAMBDA = 0.94

    # Multi-factor benchmarks
    FACTOR_TICKERS = {
        "SPY": "S&P 500",
        "QQQ": "NASDAQ 100",
        "GLD": "Gold",
        "TLT": "US Treasury 20Y+",
        "IWM": "Small Cap (Size)",
        "VTV": "Value (Style)",
    }

    # Reserved prefix used to namespace factor columns when they are aligned
    # (``pd.concat``) against the holdings return frame. A user can HOLD a
    # factor ETF (SPY/QQQ/GLD/...), which would otherwise produce duplicate
    # column labels — see ``_compute_multi_factor_betas``.
    FACTOR_COL_PREFIX = "__factor__"

    # Institutional-standard participation rate (10% of ADV)
    LIQUIDITY_PARTICIPATION_RATE = 0.10

    def __init__(
        self,
        data_provider: DataProvider,
        benchmark_ticker: str = "SPY",
        mc_simulations: int = 10_000,
        mc_horizon: int = 21,
        risk_free_rate_fallback: float = 0.045,
        market_shock: float = -0.10,
    ):
        self.dp = data_provider
        self.benchmark_ticker = benchmark_ticker
        self.mc_simulations = mc_simulations
        self.mc_horizon = mc_horizon
        self.risk_free_rate_fallback = max(float(risk_free_rate_fallback), 0.0)
        # Stress-test shock applied to the benchmark when deriving per-asset
        # losses (asset_loss = beta * market_shock). Sidebar-configurable.
        # Clamped to [-0.90, 0.0] — positive shocks aren't stress scenarios.
        self.market_shock = max(-0.90, min(0.0, float(market_shock)))
        self._report: Optional[RiskReport] = None

    # ══════════════════════════════════════════════════════════
    #  Public interface
    # ══════════════════════════════════════════════════════════
    def run(self) -> RiskReport:
        """Run all risk computations."""
        if self._report is not None:
            return self._report

        logger.info(
            "risk.run.start",
            benchmark=self.benchmark_ticker,
            mc_simulations=self.mc_simulations,
            mc_horizon=self.mc_horizon,
        )
        run_start_time = time.time()

        returns = self.dp.get_daily_returns()
        weights = self.dp.get_weight_array()

        report = RiskReport()

        # ── Dynamic risk-free rate ────────────────────────────
        report.risk_free_rate = self._fetch_risk_free_rate()

        # ── Covariance matrix (classic + EWMA) ────────────────
        report.cov_matrix = returns.cov() * self.TRADING_DAYS
        report.corr_matrix = returns.corr()

        ewma_cov_daily = self._ewma_covariance(returns)
        report.cov_matrix_ewma = pd.DataFrame(
            ewma_cov_daily * self.TRADING_DAYS,
            index=returns.columns,
            columns=returns.columns,
        )
        std_diag = np.sqrt(np.diag(ewma_cov_daily))
        std_outer = np.outer(std_diag, std_diag)
        std_outer[std_outer == 0] = 1e-12
        ewma_corr = ewma_cov_daily / std_outer
        report.corr_matrix_ewma = pd.DataFrame(
            ewma_corr,
            index=returns.columns,
            columns=returns.columns,
        )

        # ── Monte Carlo VaR / CVaR (using EWMA covariance) ────
        mc_port = self._monte_carlo_var(returns, weights, ewma_cov_daily)
        report.mc_portfolio_returns = mc_port
        report.var_95 = float(-np.percentile(mc_port, 5))
        report.var_99 = float(-np.percentile(mc_port, 1))
        report.cvar_95 = float(-mc_port[mc_port <= np.percentile(mc_port, 5)].mean())

        # ── Annualized return / volatility / Sharpe ───────────
        port_daily = returns.dot(weights)
        report.annual_return = float(port_daily.mean() * self.TRADING_DAYS)
        ewma_port_var = float(weights @ ewma_cov_daily @ weights) * self.TRADING_DAYS
        report.annual_volatility = float(np.sqrt(ewma_port_var))
        report.sharpe_ratio = self._sharpe(
            report.annual_return, report.annual_volatility, report.risk_free_rate
        )

        # ── Maximum drawdown ──────────────────────────────────
        cum = (1 + port_daily).cumprod()
        running_max = cum.cummax()
        dd = (cum - running_max) / running_max
        report.max_drawdown = float(dd.min())
        report.drawdown_series = dd

        # ── Single-factor Beta (SPY) ──────────────────────────
        report.betas = self._compute_betas(returns, self.benchmark_ticker)

        # ── Multi-factor Beta (SPY/QQQ/GLD/TLT) ───────────────
        factor_result = self._compute_multi_factor_betas(returns)
        report.factor_betas = factor_result["betas"]
        report.factor_betas_significance = factor_result["significance"]
        # Portfolio-level factor exposure (portfolio returns vs. each factor)
        report.portfolio_factor_betas = self._compute_portfolio_factor_betas(returns, weights)

        # ── Stress test (uses user-configured market_shock, not default) ───
        stress_loss, asset_losses = self._stress_test(
            returns,
            weights,
            market_shock=self.market_shock,
        )
        report.stress_loss = stress_loss
        report.stress_asset_losses = asset_losses
        # Record the shock actually used so downstream UI/AI/exports
        # can reference the same number.
        report.stress_market_shock = self.market_shock

        # ── Component VaR ─────────────────────────────────────
        report.component_var_pct = self._component_var(ewma_cov_daily, weights, returns.columns)

        # ── Rolling correlation ───────────────────────────────
        report.rolling_corr_with_port = self._rolling_correlation_with_portfolio(
            returns, weights, window=60
        )

        # ── Drawdown statistics ───────────────────────────────
        report.drawdown_stats = self._drawdown_statistics(dd)

        # ── v2.1: macro sensitivity ───────────────────────────
        report.macro_betas = self._compute_macro_betas(returns, weights)

        # ── v2.1: liquidity risk ──────────────────────────────
        report.liquidity_risk = self._compute_liquidity_risk()

        run_duration = (time.time() - run_start_time) * 1000
        logger.info(
            "risk.run.complete",
            var_95=report.var_95,
            var_99=report.var_99,
            annual_return=report.annual_return,
            annual_volatility=report.annual_volatility,
            sharpe_ratio=report.sharpe_ratio,
            max_drawdown=report.max_drawdown,
            duration_ms=round(run_duration, 2),
        )

        self._report = report
        return report

    # ══════════════════════════════════════════════════════════
    #  Margin / efficient frontier / historical scenarios (unchanged)
    # ══════════════════════════════════════════════════════════
    def compute_margin_call(
        self,
        total_long: float,
        margin_loan: float,
        maintenance_ratio: float = 0.25,
    ) -> dict:
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
        equity_ratio = net_equity / total_long if total_long > 0 else 0
        call_value = margin_loan / (1 - maintenance_ratio)
        distance_pct = (total_long - call_value) / total_long if total_long > 0 else 0
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

    def compute_efficient_frontier(
        self,
        returns: pd.DataFrame,
        risk_free: float,
        n_points: int = 50,
    ) -> dict:
        mean_ret = returns.mean().values * self.TRADING_DAYS
        cov_ann = returns.cov().values * self.TRADING_DAYS
        n = len(mean_ret)
        tickers = list(returns.columns)
        bounds = tuple((0.0, 1.0) for _ in range(n))
        constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1.0}]

        def port_vol(w):
            return np.sqrt(w @ cov_ann @ w)

        def neg_sharpe(w):
            ret = w @ mean_ret
            vol = port_vol(w)
            return -(ret - risk_free) / vol if vol > 1e-10 else 1e10

        w0 = np.ones(n) / n
        res_minvar = minimize(
            port_vol,
            w0,
            bounds=bounds,
            constraints=constraints,
            method="SLSQP",
            options={"maxiter": 1000},
        )
        w_minvar = res_minvar.x
        res_maxsharpe = minimize(
            neg_sharpe,
            w0,
            bounds=bounds,
            constraints=constraints,
            method="SLSQP",
            options={"maxiter": 1000},
        )
        w_maxsharpe = res_maxsharpe.x

        min_ret = w_minvar @ mean_ret
        max_ret = np.max(mean_ret) * 1.1
        target_rets = np.linspace(min_ret, max_ret, n_points)
        frontier_vols, frontier_rets, frontier_weights = [], [], []
        for target in target_rets:
            cons = [
                {"type": "eq", "fun": lambda w: np.sum(w) - 1.0},
                {"type": "eq", "fun": lambda w, t=target: w @ mean_ret - t},
            ]
            res = minimize(
                port_vol,
                w0,
                bounds=bounds,
                constraints=cons,
                method="SLSQP",
                options={"maxiter": 500},
            )
            if res.success:
                frontier_vols.append(float(port_vol(res.x)))
                frontier_rets.append(float(res.x @ mean_ret))
                frontier_weights.append(res.x.tolist())

        return {
            "frontier_vols": frontier_vols,
            "frontier_rets": frontier_rets,
            "frontier_weights": frontier_weights,
            "max_sharpe_weights": dict(zip(tickers, w_maxsharpe.tolist())),
            "max_sharpe_ret": float(w_maxsharpe @ mean_ret),
            "max_sharpe_vol": float(port_vol(w_maxsharpe)),
            "max_sharpe_ratio": float(-neg_sharpe(w_maxsharpe)),
            "min_var_weights": dict(zip(tickers, w_minvar.tolist())),
            "min_var_ret": float(w_minvar @ mean_ret),
            "min_var_vol": float(port_vol(w_minvar)),
            "tickers": tickers,
        }

    # ── Risk-limit compliance checks ───────────────────────

    DEFAULT_RISK_LIMITS = {
        "max_single_stock_weight": 0.15,
        "max_sector_weight": 0.30,
    }

    def check_trade_compliance(
        self,
        proposed_weights: Dict[str, float],
        sector_map: Dict[str, str],
        limits: Optional[Dict[str, float]] = None,
    ) -> List[dict]:
        """
        Check proposed weights against risk limits. Returns list of violations.

        A floating-point tolerance (1e-6) is applied: a weight of
        0.6000000000000001 is NOT reported as violating a 0.6 limit. Users
        can't meaningfully act on sub-millionth-percent violations and they
        only ever arise from numerical rounding in the auto-corrector.
        """
        rules = limits or self.DEFAULT_RISK_LIMITS
        tol = 1e-6
        violations = []

        # Single stock limit
        max_stock = rules.get("max_single_stock_weight", 0.15)
        for tk, w in proposed_weights.items():
            if w > max_stock + tol:
                violations.append(
                    {
                        "rule": "max_single_stock_weight",
                        "limit": max_stock,
                        "actual": w,
                        "ticker": tk,
                        "severity": "hard",
                    }
                )

        # Sector limit
        max_sector = rules.get("max_sector_weight", 0.30)
        sector_weights: Dict[str, float] = {}
        for tk, w in proposed_weights.items():
            s = sector_map.get(tk, "Other")
            sector_weights[s] = sector_weights.get(s, 0) + w
        for sector, w in sector_weights.items():
            if w > max_sector + tol:
                violations.append(
                    {
                        "rule": "max_sector_weight",
                        "limit": max_sector,
                        "actual": w,
                        "sector": sector,
                        "severity": "hard",
                    }
                )

        return violations

    def adjust_weights_for_compliance(
        self,
        proposed_weights: Dict[str, float],
        sector_map: Dict[str, str],
        limits: Optional[Dict[str, float]] = None,
    ) -> Dict[str, float]:
        """
        Project weights onto the feasible set defined by
        {max_single_stock, max_sector, sum <= 1.0}.

        Algorithm: alternating projection.
          - Clip each stock to max_stock
          - Scale down any sector exceeding max_sector
          - Renormalize only the NON-capped weights to absorb the remainder,
            preserving their relative proportions
          - Repeat until stable (default 20 iterations) or convergence.

        If the feasible region is tighter than 1.0 sum (e.g. many stocks
        all hit the per-stock cap), the final sum may be < 1.0 and the
        residual is effectively "cash". We do NOT blindly renormalize to
        1.0 since that would violate the caps we just enforced.
        """
        rules = limits or self.DEFAULT_RISK_LIMITS
        max_stock = rules.get("max_single_stock_weight", 0.15)
        max_sector = rules.get("max_sector_weight", 0.30)
        tol = 1e-9

        adjusted = dict(proposed_weights)

        for _ in range(20):
            changed = False

            # ── Stock cap: clip to max_stock and redistribute slack
            capped, uncapped = [], []
            for tk, w in adjusted.items():
                if w > max_stock + tol:
                    adjusted[tk] = max_stock
                    capped.append(tk)
                    changed = True
                else:
                    uncapped.append(tk)

            # Absorb slack (1.0 - sum) into uncapped weights in proportion
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

            # ── Sector cap: scale every ticker in over-cap sectors proportionally
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

            # Converged?
            violations = self.check_trade_compliance(adjusted, sector_map, limits)
            if not violations and not changed:
                break

        # Final safety clip (bounds the output regardless of convergence)
        for tk in list(adjusted):
            adjusted[tk] = max(0.0, min(adjusted[tk], max_stock))

        return adjusted

    def compute_historical_scenarios(self, weights_dict: dict) -> pd.DataFrame:
        scenarios = [
            ("2020 COVID Crash (Feb 19 – Mar 23, 2020)", "2020-02-18", "2020-03-23"),
            ("2022 Bear Market (Full Year 2022)", "2021-12-31", "2022-12-30"),
            ("2018 Q4 Selloff (Oct 1 – Dec 24, 2018)", "2018-09-28", "2018-12-24"),
            ("2008 Financial Crisis (Jan 2008 – Mar 2009)", "2008-01-02", "2009-03-09"),
            ("2022 Crypto Winter (Nov 2021 – Nov 2022)", "2021-10-29", "2022-11-18"),
        ]
        tickers = list(weights_dict.keys())
        results = []
        for name, start, end in scenarios:
            try:
                prices = self.dp.get_historical_scenario_prices(tickers, start, end)
                if prices is None or prices.empty:
                    raise ValueError("No price data from provider")
                available = [t for t in tickers if t in prices.columns]
                if not available:
                    raise ValueError("No tickers available")
                rets = {}
                for t in available:
                    col = prices[t].dropna()
                    if len(col) >= 2:
                        rets[t] = float(col.iloc[-1] / col.iloc[0] - 1)
                if not rets:
                    raise ValueError("No valid price data")
                avail_w = {t: weights_dict[t] for t in rets if t in weights_dict}
                total_w = sum(avail_w.values())
                if total_w <= 0:
                    raise ValueError("Zero total weight")
                norm_w = {t: w / total_w for t, w in avail_w.items()}
                port_ret = sum(rets[t] * norm_w[t] for t in rets)
                results.append(
                    {
                        "Scenario": name,
                        "Portfolio Return": port_ret,
                        "Coverage": f"{len(rets)}/{len(tickers)} assets",
                    }
                )
            except Exception as e:
                logger.warning(
                    f"Historical scenario calculation failed: {name}", error=str(e), scenario=name
                )
                results.append({"Scenario": name, "Portfolio Return": None, "Coverage": "N/A"})
        return pd.DataFrame(results)

    # ══════════════════════════════════════════════════════════
    #  Internal methods
    # ══════════════════════════════════════════════════════════

    # ── Risk-free rate ────────────────────────────────────────
    def _fetch_risk_free_rate(self) -> float:
        # Delegated to DataProvider so risk_engine has no direct yfinance calls.
        # DataProvider.get_risk_free_rate() returns fallback on any failure.
        try:
            return self.dp.get_risk_free_rate(self.risk_free_rate_fallback)
        except Exception as e:
            logger.info(
                "risk.rf.delegate_failed",
                error=str(e),
                fallback=self.risk_free_rate_fallback,
            )
            return self.risk_free_rate_fallback

    # ── EWMA covariance ───────────────────────────────────────
    def _ewma_covariance(self, returns: pd.DataFrame) -> np.ndarray:
        data = returns.values
        T, n = data.shape
        if T < 2:
            return np.eye(n)
        lam = self.EWMA_LAMBDA
        cov = np.cov(data.T)
        if cov.ndim < 2:
            cov = cov.reshape(1, 1)
        for t in range(1, T):
            r = data[t].reshape(-1, 1)
            cov = lam * cov + (1 - lam) * (r @ r.T)
        return cov

    # ── Monte Carlo ───────────────────────────────────────────
    def _monte_carlo_var(self, returns, weights, cov_daily):
        """
        Fully vectorized Monte Carlo VaR calculation.

        Performance: ~100x faster than loop-based approach for 10,000 simulations.

        Args:
            returns: Historical returns DataFrame
            weights: Portfolio weights array
            cov_daily: Daily covariance matrix

        Returns:
            portfolio_returns: Array of simulated portfolio returns
        """
        logger.info(
            "risk.var.mc.start",
            mc_simulations=self.mc_simulations,
            mc_horizon=self.mc_horizon,
            n_assets=len(weights),
        )
        start_time = time.time()

        mean_daily = returns.mean().values
        n_assets = len(mean_daily)

        # Cholesky decomposition with numerical stability
        try:
            L = np.linalg.cholesky(cov_daily)
        except np.linalg.LinAlgError:
            # Add small ridge for positive definiteness
            cov_daily = cov_daily + np.eye(n_assets) * 1e-8
            L = np.linalg.cholesky(cov_daily)

        rng = np.random.default_rng(42)

        # VECTORIZED APPROACH - Generate all random numbers at once
        # Shape: (mc_simulations, mc_horizon, n_assets)
        Z = rng.standard_normal(size=(self.mc_simulations, self.mc_horizon, n_assets))

        # Vectorized daily returns: mean + correlated random shocks
        # Broadcasting: mean_daily[None, None, :] + Z @ L.T
        # Result shape: (mc_simulations, mc_horizon, n_assets)
        daily_rets = mean_daily[None, None, :] + (Z @ L.T)

        # Vectorized portfolio returns for each day
        # Shape: (mc_simulations, mc_horizon)
        portfolio_daily_returns = daily_rets @ weights

        # Clip to prevent numerical issues (daily return < -99%)
        portfolio_daily_returns = np.clip(portfolio_daily_returns, -0.99, 10.0)

        # Vectorized compound return calculation
        # For each simulation: (1+r1) × (1+r2) × ... × (1+rn) - 1
        # np.prod along axis=1 (horizon dimension)
        # Shape: (mc_simulations,)
        portfolio_returns = np.prod(1 + portfolio_daily_returns, axis=1) - 1

        duration_ms = (time.time() - start_time) * 1000
        var_95 = -np.percentile(portfolio_returns, 5)
        var_99 = -np.percentile(portfolio_returns, 1)

        logger.info(
            "risk.var.mc.complete",
            var_95=float(var_95),
            var_99=float(var_99),
            duration_ms=round(duration_ms, 2),
            speedup_note="Fully vectorized - no Python loops",
        )

        return portfolio_returns

    def _sharpe(self, annual_ret, annual_vol, rf):
        return (annual_ret - rf) / annual_vol if annual_vol != 0 else 0.0

    # ── Single-factor Beta ────────────────────────────────────
    def _compute_betas(self, returns, benchmark):
        logger.info("risk.beta.start", benchmark=benchmark)
        start_time = time.time()

        # Delegate benchmark fetch to DataProvider (project-wide simple returns).
        bench_df = self.dp.get_benchmark_returns([benchmark])
        if bench_df is None or bench_df.empty or benchmark not in bench_df.columns:
            logger.warning(
                "risk.beta.benchmark_unavailable",
                benchmark=benchmark,
                reason="no_data_from_provider",
            )
            return {t: np.nan for t in returns.columns}
        bench_ret = bench_df[benchmark].dropna()

        betas = {}
        for ticker in returns.columns:
            aligned = pd.concat([returns[ticker], bench_ret], axis=1, join="inner").dropna()
            if len(aligned) < 30:
                betas[ticker] = np.nan
                continue
            cov = np.cov(aligned.iloc[:, 0], aligned.iloc[:, 1])
            betas[ticker] = float(cov[0, 1] / cov[1, 1]) if cov[1, 1] != 0 else np.nan

        duration_ms = (time.time() - start_time) * 1000
        logger.info(
            "risk.beta.complete",
            benchmark=benchmark,
            tickers_calculated=len(betas),
            duration_ms=round(duration_ms, 2),
        )
        return betas

    # ── Beta statistical-significance test ─────────────────────
    def _compute_beta_with_significance(
        self, asset_returns: np.ndarray, factor_returns: np.ndarray
    ) -> dict:
        """
        Compute Beta and its statistical significance (single-factor OLS regression)

        Args:
            asset_returns: asset returns (T,)
            factor_returns: factor returns (T,)

        Returns:
            {
                'beta': float,           # factor beta coefficient
                'intercept': float,      # intercept (alpha)
                't_stat': float,         # t-statistic
                'p_value': float,        # p-value (two-tailed test)
                'is_significant': bool,  # whether significant (p<0.05)
                'r_squared': float,      # goodness of fit
                'std_error': float       # standard error
            }
        """
        from scipy import stats

        # Add intercept term
        n = len(asset_returns)
        X = np.column_stack([np.ones(n), factor_returns])
        y = asset_returns

        # OLS regression
        try:
            beta_coefs, residuals, rank, s = np.linalg.lstsq(X, y, rcond=None)
        except np.linalg.LinAlgError:
            # Singular matrix
            return {
                "beta": np.nan,
                "intercept": np.nan,
                "t_stat": np.nan,
                "p_value": np.nan,
                "is_significant": False,
                "r_squared": np.nan,
                "std_error": np.nan,
            }

        # Compute statistics
        k = X.shape[1]  # number of parameters (2: intercept + slope)

        # Residual standard deviation
        if len(residuals) > 0:
            mse = residuals[0] / (n - k)
        else:
            # lstsq may not return residuals for a rank-deficient matrix
            predictions = X @ beta_coefs
            residuals_manual = y - predictions
            mse = np.sum(residuals_manual**2) / (n - k) if n > k else np.nan

        if np.isnan(mse) or mse < 0:
            return {
                "beta": float(beta_coefs[1]) if len(beta_coefs) > 1 else np.nan,
                "intercept": float(beta_coefs[0]) if len(beta_coefs) > 0 else np.nan,
                "t_stat": np.nan,
                "p_value": np.nan,
                "is_significant": False,
                "r_squared": np.nan,
                "std_error": np.nan,
            }

        # Variance-covariance matrix of Beta
        try:
            XtX_inv = np.linalg.inv(X.T @ X)
            var_covar = mse * XtX_inv
            std_errors = np.sqrt(var_covar.diagonal())
        except np.linalg.LinAlgError:
            # Perfectly collinear
            std_errors = np.full(k, np.nan)

        # t-statistic = beta / se(beta)
        t_stats = np.full(k, np.nan)
        for i in range(k):
            if std_errors[i] > 0:
                t_stats[i] = beta_coefs[i] / std_errors[i]

        # p-value (two-tailed test)
        p_values = np.full(k, np.nan)
        for i in range(k):
            if not np.isnan(t_stats[i]):
                p_values[i] = 2 * (1 - stats.t.cdf(np.abs(t_stats[i]), df=n - k))

        # R² (goodness of fit)
        ss_total = np.sum((y - np.mean(y)) ** 2)
        ss_residual = np.sum((y - X @ beta_coefs) ** 2)
        r_squared = 1 - (ss_residual / ss_total) if ss_total > 0 else 0

        return {
            "beta": float(beta_coefs[1]),
            "intercept": float(beta_coefs[0]),
            "t_stat": float(t_stats[1]),
            "p_value": float(p_values[1]),
            "is_significant": bool(p_values[1] < 0.05) if not np.isnan(p_values[1]) else False,
            "r_squared": float(max(0, min(1, r_squared))),
            "std_error": float(std_errors[1]) if len(std_errors) > 1 else np.nan,
        }

    # ── Multi-factor Beta (SPY/QQQ/GLD/TLT) ───────────────────
    def _compute_multi_factor_betas(self, returns):
        """
        Compute multi-factor beta and its statistical significance

        Returns:
            dict: {
                'betas': DataFrame,          # table of beta values
                'significance': DataFrame,   # table of statistics (t_stat, p_value, etc.)
            }
        """
        factor_tickers = list(self.FACTOR_TICKERS.keys())
        # Delegate factor-benchmark fetch to DataProvider (simple returns).
        factor_ret = self.dp.get_benchmark_returns(factor_tickers)
        if factor_ret is None or factor_ret.empty:
            logger.warning(
                "risk.factor_beta.benchmarks_unavailable",
                factors=factor_tickers,
                reason="no_data_from_provider",
            )
            empty_df = pd.DataFrame(
                np.nan,
                index=returns.columns,
                columns=[self.FACTOR_TICKERS[f] for f in factor_tickers],
            )
            return {"betas": empty_df, "significance": pd.DataFrame()}

        # Namespace the factor columns BEFORE aligning. A user may hold a
        # ticker that is also a factor ETF (SPY/QQQ/GLD/TLT/IWM/VTV); without
        # this, `aligned` carries duplicate labels and `aligned[label]` returns
        # a (T, 2) DataFrame instead of a Series. That broke two ways:
        #   * the held factor ETF's own `y` became 2-D -> ValueError -> its
        #     entire factor-beta row was NaN (logged as "Beta calculation
        #     failed for SPY vs S&P 500");
        #   * for EVERY other holding, the duplicated (collinear) factor column
        #     silently turned the univariate regression into a bivariate one,
        #     splitting the coefficient across the two identical columns —
        #     a wrong beta with no error at all.
        # Only the labels change; the aligned values / join / dropna are
        # unchanged, so betas for non-overlapping tickers are identical.
        prefix = self.FACTOR_COL_PREFIX
        factor_ret = factor_ret.rename(columns=lambda c: f"{prefix}{c}")

        aligned = pd.concat([returns, factor_ret], axis=1, join="inner").dropna()
        asset_cols = returns.columns
        factor_cols = [c for c in factor_ret.columns if c in aligned.columns]

        def _factor_name(col: str) -> str:
            """Prefixed aligned-frame column -> human-readable factor name."""
            raw = col[len(prefix) :] if col.startswith(prefix) else col
            return self.FACTOR_TICKERS.get(raw, raw)

        if len(aligned) < 60 or len(factor_cols) == 0:
            empty_df = pd.DataFrame(
                np.nan,
                index=returns.columns,
                columns=[self.FACTOR_TICKERS.get(f, f) for f in factor_tickers],
            )
            return {"betas": empty_df, "significance": pd.DataFrame()}

        # Store beta values and statistics
        beta_result = {}
        sig_result = []

        for ticker in asset_cols:
            if ticker not in aligned.columns:
                beta_result[ticker] = {_factor_name(f): np.nan for f in factor_cols}
                continue

            y = aligned[ticker].values
            beta_result[ticker] = {}

            # Compute beta and significance separately for each factor
            for f in factor_cols:
                X_factor = aligned[f].values
                factor_name = _factor_name(f)

                try:
                    stats = self._compute_beta_with_significance(y, X_factor)
                    beta_result[ticker][factor_name] = stats["beta"]

                    # Record statistics
                    sig_result.append(
                        {
                            "Ticker": ticker,
                            "Factor": factor_name,
                            "Beta": stats["beta"],
                            "t_stat": stats["t_stat"],
                            "p_value": stats["p_value"],
                            "is_significant": stats["is_significant"],
                            "r_squared": stats["r_squared"],
                            "std_error": stats["std_error"],
                        }
                    )
                except Exception as e:
                    logger.warning(
                        f"Beta calculation failed for {ticker} vs {factor_name}",
                        error=str(e),
                        ticker=ticker,
                        factor=factor_name,
                    )
                    beta_result[ticker][factor_name] = np.nan
                    sig_result.append(
                        {
                            "Ticker": ticker,
                            "Factor": factor_name,
                            "Beta": np.nan,
                            "t_stat": np.nan,
                            "p_value": np.nan,
                            "is_significant": False,
                            "r_squared": np.nan,
                            "std_error": np.nan,
                        }
                    )

        return {"betas": pd.DataFrame(beta_result).T, "significance": pd.DataFrame(sig_result)}

    def _compute_portfolio_factor_betas(self, returns, weights):
        """Portfolio-level factor exposures.

        Regresses the *portfolio* daily return series (returns · weights) on
        each factor (SPY/QQQ/GLD/TLT/IWM/VTV) univariately — i.e. the
        sensitivity of the whole book to each factor. This is what the
        report UI's "Regression of portfolio returns on each factor" table
        shows; it is distinct from ``factor_betas`` (the per-asset beta
        matrix indexed by ticker).

        Returns a DataFrame indexed by factor ticker with columns
        ``[beta, r_squared, t_stat, p_value]``, or ``None`` when factor
        history is unavailable / too short to regress.
        """
        factor_tickers = list(self.FACTOR_TICKERS.keys())
        factor_ret = self.dp.get_benchmark_returns(factor_tickers)
        if factor_ret is None or getattr(factor_ret, "empty", True):
            logger.warning("risk.portfolio_factor_beta.benchmarks_unavailable")
            return None

        port = pd.Series(returns.dot(weights), index=returns.index, name="__port__")
        aligned = pd.concat([port, factor_ret], axis=1, join="inner").dropna()
        if len(aligned) < 60:
            logger.warning(
                "risk.portfolio_factor_beta.insufficient_overlap", observations=len(aligned)
            )
            return None

        y = aligned["__port__"].values
        rows = {}
        for f in factor_tickers:
            if f not in aligned.columns:
                continue
            try:
                stats = self._compute_beta_with_significance(y, aligned[f].values)
            except Exception as e:  # pragma: no cover - defensive
                logger.warning("risk.portfolio_factor_beta.failed", factor=f, error=str(e))
                continue
            rows[f] = {
                "beta": stats["beta"],
                "r_squared": stats["r_squared"],
                "t_stat": stats["t_stat"],
                "p_value": stats["p_value"],
            }
        if not rows:
            return None
        return pd.DataFrame(rows).T

    # ── Barra-style factor risk attribution ───────────────────
    def compute_factor_risk_attribution(
        self,
        returns: pd.DataFrame,
        weights: np.ndarray,
        n_factors: int = 5,
    ) -> dict:
        """PCA-based Barra-style factor risk attribution."""
        # Standardize returns
        mu = returns.mean().values
        std = returns.std().values
        std[std == 0] = 1e-10  # avoid division by zero
        Z = (returns.values - mu) / std

        # PCA via eigendecomposition
        cov_z = np.cov(Z, rowvar=False)
        eigenvalues, eigenvectors = np.linalg.eigh(cov_z)
        idx = np.argsort(eigenvalues)[::-1]
        eigenvalues = eigenvalues[idx]
        eigenvectors = eigenvectors[:, idx]

        n_factors = min(n_factors, len(eigenvalues))
        loadings = eigenvectors[:, :n_factors]  # (n_assets x n_factors)
        factor_returns = Z @ loadings  # (T x n_factors)

        explained_ratio = eigenvalues[:n_factors] / eigenvalues.sum()

        # Label factors by correlation with known benchmarks
        factor_names = [f"Factor {i+1}" for i in range(n_factors)]
        try:
            benchmark_tickers = list(self.FACTOR_TICKERS.keys())[:4]  # SPY, QQQ, GLD, TLT
            bench_ret = self.dp.get_benchmark_returns(benchmark_tickers)
            if bench_ret is None or bench_ret.empty:
                raise ValueError("benchmark data unavailable from provider")

            # Align dates
            common_idx = returns.index.intersection(bench_ret.index)
            if len(common_idx) > 50:
                bench_aligned = bench_ret.loc[common_idx].values
                factor_aligned = factor_returns[-len(common_idx) :]

                label_map = {
                    "SPY": "Market",
                    "QQQ": "Growth/Momentum",
                    "GLD": "Safe Haven",
                    "TLT": "Duration",
                    "IWM": "Size",
                    "VTV": "Value",
                }
                used_factors = set()
                for j, btk in enumerate(benchmark_tickers):
                    if btk not in bench_ret.columns or j >= bench_aligned.shape[1]:
                        continue
                    best_corr = 0
                    best_k = -1
                    for k in range(n_factors):
                        if k in used_factors:
                            continue
                        c = np.corrcoef(bench_aligned[:, j], factor_aligned[:, k])[0, 1]
                        if abs(c) > abs(best_corr):
                            best_corr = c
                            best_k = k
                    if best_k >= 0 and abs(best_corr) > 0.3:
                        factor_names[best_k] = label_map.get(btk, btk)
                        used_factors.add(best_k)
        except Exception as e:
            logger.info(
                "risk.pca.factor_label_skipped",
                error=str(e),
                reason="benchmark data unavailable; keeping generic factor names",
            )

        # Rename remaining unlabeled
        for i in range(n_factors):
            if factor_names[i].startswith("Factor "):
                factor_names[i] = f"Latent Factor {i+1}"

        # Portfolio factor exposure
        port_exposure = loadings.T @ weights  # (n_factors,)

        # Factor contribution to variance
        port_var = weights @ cov_z @ weights
        factor_var_contrib = {}
        for k in range(n_factors):
            contrib = (port_exposure[k] ** 2) * eigenvalues[k]
            factor_var_contrib[factor_names[k]] = float(contrib / port_var) if port_var > 0 else 0
        idio_var = 1.0 - sum(factor_var_contrib.values())
        factor_var_contrib["Idiosyncratic"] = max(0, idio_var)

        # Last-day P&L attribution (in return space)
        last_factor_ret = factor_returns[-1]  # (n_factors,)
        actual_port_ret = float(returns.iloc[-1].values @ weights)
        factor_pnl = {}
        total_factor_pnl = 0.0
        for k in range(n_factors):
            pnl = float(port_exposure[k] * last_factor_ret[k] * std.mean())
            factor_pnl[factor_names[k]] = pnl
            total_factor_pnl += pnl
        factor_pnl["Alpha (Idiosyncratic)"] = actual_port_ret - total_factor_pnl

        # R-squared
        predicted = factor_returns @ port_exposure * std.mean()
        actual_port_series = returns.values @ weights
        ss_res = np.sum((actual_port_series - predicted) ** 2)
        ss_tot = np.sum((actual_port_series - actual_port_series.mean()) ** 2)
        r_squared = 1 - ss_res / ss_tot if ss_tot > 0 else 0

        # Factor exposures DataFrame
        exposure_df = pd.DataFrame(loadings, index=returns.columns, columns=factor_names)

        return {
            "factor_names": factor_names,
            "factor_var_contrib": factor_var_contrib,
            "factor_pnl": factor_pnl,
            "idiosyncratic_alpha": factor_pnl.get("Alpha (Idiosyncratic)", 0),
            "total_return": actual_port_ret,
            "r_squared": float(max(0, min(1, r_squared))),
            "factor_exposures": exposure_df,
            "explained_variance_ratio": [float(r) for r in explained_ratio],
            "portfolio_exposures": {
                factor_names[k]: float(port_exposure[k]) for k in range(n_factors)
            },
        }

    # ── Stress test ───────────────────────────────────────────
    def _stress_test(self, returns, weights, market_shock=-0.10):
        logger.info("risk.stress.start", market_shock=market_shock)
        start_time = time.time()

        betas = self._compute_betas(returns, self.benchmark_ticker)
        asset_losses = {}
        port_loss = 0.0
        for i, ticker in enumerate(returns.columns):
            b = betas.get(ticker, 1.0)
            try:
                if np.isnan(b):
                    b = 1.0
            except (TypeError, ValueError):
                b = 1.0
            loss = b * market_shock
            asset_losses[ticker] = float(loss)
            port_loss += weights[i] * loss

        duration_ms = (time.time() - start_time) * 1000
        logger.info(
            "risk.stress.complete",
            market_shock=market_shock,
            portfolio_loss=float(port_loss),
            duration_ms=round(duration_ms, 2),
        )

        return float(port_loss), asset_losses

    # ── Conditional stress test (black-swan shock propagation) ─

    # Preset scenarios for Black Swan testing
    PRESET_SCENARIOS = {
        "Taiwan Conflict": {"TSM": -0.30, "NVDA": -0.15},
        "Rate Shock (+200bp)": {"TLT": -0.15},
        "Crypto Winter": {"BTC-USD": -0.50},
        "Tech Meltdown": {"QQQ": -0.25},
        "Oil Crisis (Proxy via Energy)": {"XLE": 0.30},
    }

    def compute_conditional_stress(
        self,
        scenario: Dict[str, float],
        returns: pd.DataFrame,
        weights: np.ndarray,
        use_ewma: bool = True,
    ) -> dict:
        """
        Conditional stress test using multivariate normal properties.
        E[B|A=x] = mu_B + Sigma_BA * Sigma_AA^(-1) * (x - mu_A)
        """
        tickers = list(returns.columns)
        n = len(tickers)

        # Filter scenario to tickers actually in portfolio
        observed = {tk: shock for tk, shock in scenario.items() if tk in tickers}
        if not observed:
            return {
                "conditional_returns": {},
                "portfolio_loss": 0.0,
                "propagation_chain": [],
                "observed_tickers": list(scenario.keys()),
                "warning": "No scenario tickers found in portfolio",
            }

        # Get covariance and mean
        if use_ewma:
            cov = self._ewma_covariance(returns)
        else:
            cov = returns.cov().values
        mu = returns.mean().values

        # Partition indices
        obs_names = list(observed.keys())
        obs_idx = [tickers.index(tk) for tk in obs_names]
        unobs_idx = [i for i in range(n) if i not in obs_idx]

        # Block matrices
        Sigma_oo = cov[np.ix_(obs_idx, obs_idx)]
        Sigma_uo = cov[np.ix_(unobs_idx, obs_idx)]

        # Regularize and invert
        Sigma_oo_reg = Sigma_oo + 1e-10 * np.eye(len(obs_idx))
        try:
            Sigma_oo_inv = np.linalg.inv(Sigma_oo_reg)
        except np.linalg.LinAlgError:
            Sigma_oo_inv = np.linalg.pinv(Sigma_oo_reg)

        # Observed shock vector (daily return scale)
        x_obs = np.array([observed[tk] for tk in obs_names])
        mu_obs = mu[obs_idx]
        mu_unobs = mu[unobs_idx]

        # Conditional expectation
        E_unobs = mu_unobs + Sigma_uo @ Sigma_oo_inv @ (x_obs - mu_obs)

        # Build full return vector
        full_returns = np.zeros(n)
        for i, idx in enumerate(obs_idx):
            full_returns[idx] = x_obs[i]
        for i, idx in enumerate(unobs_idx):
            full_returns[idx] = float(E_unobs[i])

        # Portfolio loss
        portfolio_loss = float(full_returns @ weights)

        # Conditional returns dict
        conditional_returns = {tickers[i]: float(full_returns[i]) for i in range(n)}

        # Propagation chain: unobserved assets sorted by absolute impact
        propagation = [(tickers[idx], float(E_unobs[i])) for i, idx in enumerate(unobs_idx)]
        propagation.sort(key=lambda x: x[1])  # most negative first

        return {
            "conditional_returns": conditional_returns,
            "portfolio_loss": portfolio_loss,
            "propagation_chain": propagation,
            "observed_tickers": obs_names,
        }

    # ── Component VaR ─────────────────────────────────────────
    def _component_var(self, cov_daily, weights, columns):
        port_var = float(weights @ cov_daily @ weights)
        if port_var <= 0:
            return pd.Series(np.zeros(len(weights)), index=columns)
        cov_w = cov_daily @ weights
        pct = (weights * cov_w) / port_var
        pct = np.nan_to_num(pct, nan=0.0, posinf=0.0, neginf=0.0)
        return pd.Series(pct, index=columns)

    # ── Rolling correlation ───────────────────────────────────
    def _rolling_correlation_with_portfolio(self, returns, weights, window=60):
        port_ret = returns.dot(weights)
        return pd.DataFrame(
            {col: returns[col].rolling(window).corr(port_ret) for col in returns.columns}
        )

    # ── Drawdown statistics ───────────────────────────────────
    def _drawdown_statistics(self, dd_series):
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

    # ══════════════════════════════════════════════════════════
    #  v2.1 addition: macro sensitivity (Macro Beta)
    # ══════════════════════════════════════════════════════════
    def _compute_macro_betas(
        self,
        returns: pd.DataFrame,
        weights: np.ndarray,
    ) -> dict:
        """
        Multivariate linear regression: Portfolio_Return ~ β1·ΔRate + β2·ΔUSD + β3·ΔOil + ε

        Uses pure numpy OLS (np.linalg.lstsq), no paid API required.

        Returns
        -------
        dict with keys:
            "betas"   : {factor_name: beta_value}  — portfolio sensitivity to each macro factor
            "r_squared": float                      — regression R² (explanatory power of the macro factors)
            "alpha"   : float                       — intercept term (alpha, annualized)
            "residual_vol": float                   — residual volatility (annualized)
            "t_stats" : {factor_name: t_statistic}  — t-statistics
            "per_asset": DataFrame                  — per-asset beta to the macro factors
        """
        try:
            macro_ret = self.dp.get_macro_returns()
        except Exception as e:
            logger.error("Failed to fetch macro returns data", error=str(e))
            return self._empty_macro_result()

        # Degraded path: empty macro data (e.g. offline / provider failure)
        if macro_ret is None or macro_ret.empty:
            return self._empty_macro_result()

        # Portfolio daily returns
        port_daily = returns.dot(weights)

        # Align dates
        aligned = pd.concat(
            [port_daily.rename("Portfolio"), macro_ret], axis=1, join="inner"
        ).dropna()

        if len(aligned) < 60:
            return self._empty_macro_result()

        factor_names = [c for c in macro_ret.columns if c in aligned.columns]
        if not factor_names:
            return self._empty_macro_result()

        y = aligned["Portfolio"].values  # (T,)
        X = aligned[factor_names].values  # (T, k)
        X_aug = np.column_stack([np.ones(len(X)), X])  # add intercept column

        # ── OLS: beta = (X'X)^{-1} X'y ──────────────────────
        beta, residuals, rank, sv = np.linalg.lstsq(X_aug, y, rcond=None)

        alpha = float(beta[0])
        factor_betas = {factor_names[i]: float(beta[i + 1]) for i in range(len(factor_names))}

        # ── R² ───────────────────────────────────────────────
        y_hat = X_aug @ beta
        ss_res = float(np.sum((y - y_hat) ** 2))
        ss_tot = float(np.sum((y - y.mean()) ** 2))
        r_squared = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0

        # ── Residual volatility (annualized) ──────────────────
        T = len(y)
        k = len(factor_names) + 1  # includes intercept
        resid_var = ss_res / (T - k) if T > k else ss_res / max(T, 1)
        residual_vol = float(np.sqrt(resid_var) * np.sqrt(self.TRADING_DAYS))

        # ── t-statistics ──────────────────────────────────────
        t_stats = {}
        try:
            XtX_inv = np.linalg.inv(X_aug.T @ X_aug)
            se = np.sqrt(np.diag(XtX_inv) * resid_var)
            for i, fn in enumerate(factor_names):
                t_stats[fn] = float(beta[i + 1] / se[i + 1]) if se[i + 1] > 0 else 0.0
        except np.linalg.LinAlgError:
            t_stats = {fn: np.nan for fn in factor_names}

        # ── Per-asset macro beta ──────────────────────────────
        per_asset = {}
        for ticker in returns.columns:
            asset_aligned = pd.concat([returns[ticker], macro_ret], axis=1, join="inner").dropna()
            if len(asset_aligned) < 30:
                per_asset[ticker] = {fn: np.nan for fn in factor_names}
                continue
            y_a = asset_aligned[ticker].values
            X_a = asset_aligned[factor_names].values
            X_a_aug = np.column_stack([np.ones(len(X_a)), X_a])
            try:
                b_a, _, _, _ = np.linalg.lstsq(X_a_aug, y_a, rcond=None)
                per_asset[ticker] = {
                    factor_names[i]: float(b_a[i + 1]) for i in range(len(factor_names))
                }
            except Exception as e:
                logger.warning(
                    f"Macro beta calculation failed for {ticker}", error=str(e), ticker=ticker
                )
                per_asset[ticker] = {fn: np.nan for fn in factor_names}

        per_asset_df = pd.DataFrame(per_asset).T
        per_asset_df.index.name = "Ticker"

        return {
            "betas": factor_betas,
            "r_squared": r_squared,
            "alpha": alpha * self.TRADING_DAYS,  # annualized
            "residual_vol": residual_vol,
            "t_stats": t_stats,
            "per_asset": per_asset_df,
        }

    def _empty_macro_result(self) -> dict:
        """Empty result when macro data is unavailable."""
        return {
            "betas": {},
            "r_squared": 0.0,
            "alpha": 0.0,
            "residual_vol": 0.0,
            "t_stats": {},
            "per_asset": pd.DataFrame(),
        }

    # ══════════════════════════════════════════════════════════
    #  v2.1 addition: liquidity risk (Days to Liquidate)
    # ══════════════════════════════════════════════════════════
    def _compute_liquidity_risk(self) -> pd.DataFrame:
        """
        Liquidity risk analysis.

        Formula: Days to Liquidate = Shares / (ADV × Participation Rate)
        Participation rate = 10% (institutional standard: your sell never exceeds 10% of a single day's total volume)

        Returns
        -------
        DataFrame with columns:
            Ticker, Shares, ADV_30d, Days_to_Liquidate,
            Liquidity_Tier, Market_Value_Pct
        """
        holdings = self.dp.holdings
        if not holdings:
            # No share-count data available; return a table with ADV only
            try:
                adv = self.dp.get_adv_30d()
                df = pd.DataFrame(
                    {
                        "Ticker": adv.index,
                        "ADV_30d": adv.values.astype(float),
                    }
                )
                df["Shares"] = np.nan
                df["Days_to_Liquidate"] = np.nan
                df["Liquidity_Tier"] = "N/A (no share data)"
                df["Weight"] = [self.dp.weights.get(tk, 0) for tk in df["Ticker"]]
                return df.set_index("Ticker")
            except Exception as e:
                logger.error("Failed to get ADV data (no holdings mode)", error=str(e))
                return pd.DataFrame()

        try:
            adv = self.dp.get_adv_30d()
        except Exception as e:
            logger.error("Failed to get ADV data for liquidity risk calculation", error=str(e))
            return pd.DataFrame()

        rows = []
        for ticker in self.dp.tickers:
            shares = holdings.get(ticker, {}).get("shares", 0)
            avg_vol = float(adv.get(ticker, 0))
            weight = self.dp.weights.get(ticker, 0)

            # Days to liquidate
            tradable_per_day = avg_vol * self.LIQUIDITY_PARTICIPATION_RATE
            if tradable_per_day > 0 and shares > 0:
                days_to_liq = shares / tradable_per_day
            else:
                days_to_liq = np.nan

            # Liquidity tier
            if np.isnan(days_to_liq) or avg_vol == 0:
                tier = "Unknown"
            elif days_to_liq < 0.01:
                tier = "Instant"  # liquidate within seconds
            elif days_to_liq < 0.1:
                tier = "High"  # minutes
            elif days_to_liq < 1.0:
                tier = "Good"  # same-day
            elif days_to_liq < 5.0:
                tier = "Moderate"  # 1-5 days
            else:
                tier = "⚠️ Low"  # more than 5 days

            rows.append(
                {
                    "Ticker": ticker,
                    "Shares": shares,
                    "ADV_30d": avg_vol,
                    "Days_to_Liquidate": (
                        round(days_to_liq, 3) if not np.isnan(days_to_liq) else np.nan
                    ),
                    "Liquidity_Tier": tier,
                    "Weight": weight,
                }
            )

        df = pd.DataFrame(rows).set_index("Ticker")
        return df
