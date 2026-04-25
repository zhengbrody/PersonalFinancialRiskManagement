"""
risk_engine.py
机构级风险引擎 v2.1
──────────────────────────────────────────────────────────
新增：宏观敏感度 (Macro Beta) · 流动性风险 (Days to Liquidate)
保留：EWMA 动态协方差 · 动态无风险利率 · 多因子 Beta
      保证金预警 · 马科维茨有效前沿 · 成分 VaR · 回撤统计
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
#  风险报告数据容器
# ══════════════════════════════════════════════════════════════
@dataclass
class RiskReport:
    """单次风险计算结果的容器。"""

    # VaR
    var_95: float = 0.0
    var_99: float = 0.0
    cvar_95: float = 0.0
    # 基本统计
    annual_return: float = 0.0
    annual_volatility: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0
    # Beta (相对基准)
    betas: Dict[str, float] = field(default_factory=dict)
    # 多因子 Beta (SPY/QQQ/GLD/TLT)
    factor_betas: Optional[pd.DataFrame] = None
    # 多因子 Beta 统计显著性信息
    factor_betas_significance: Optional[pd.DataFrame] = None
    # 协方差 & 相关系数矩阵（EWMA）
    cov_matrix: Optional[pd.DataFrame] = None
    cov_matrix_ewma: Optional[pd.DataFrame] = None
    corr_matrix: Optional[pd.DataFrame] = None
    corr_matrix_ewma: Optional[pd.DataFrame] = None
    # 蒙特卡洛模拟路径
    mc_portfolio_returns: Optional[np.ndarray] = None
    # 压力测试
    stress_loss: float = 0.0
    stress_asset_losses: Dict[str, float] = field(default_factory=dict)
    # Actual market_shock used when computing stress_loss (so UI/AI/exports
    # report the same number the engine used, not a mismatched default).
    stress_market_shock: float = -0.10
    # 回撤序列
    drawdown_series: Optional[pd.Series] = None
    # 成分VaR贡献度
    component_var_pct: Optional[pd.Series] = None
    # 滚动相关性
    rolling_corr_with_port: Optional[pd.DataFrame] = None
    # 回撤统计
    drawdown_stats: Optional[dict] = None
    # 动态无风险利率
    risk_free_rate: float = np.nan
    # 保证金预警
    margin_call_info: Optional[dict] = None
    # 有效前沿
    efficient_frontier: Optional[dict] = None

    # ── v2.1 新增 ─────────────────────────────────────────────
    # 宏观敏感度 Beta（组合对 利率 / 美元 / 原油 的回归系数）
    macro_betas: Optional[dict] = None
    # 流动性风险（每个资产的清仓天数和 ADV）
    liquidity_risk: Optional[pd.DataFrame] = None


# ══════════════════════════════════════════════════════════════
#  风险引擎
# ══════════════════════════════════════════════════════════════
class RiskEngine:
    """机构级风险计算引擎。"""

    TRADING_DAYS = 252
    EWMA_LAMBDA = 0.94

    # 多因子基准
    FACTOR_TICKERS = {
        "SPY": "S&P 500",
        "QQQ": "NASDAQ 100",
        "GLD": "Gold",
        "TLT": "US Treasury 20Y+",
        "IWM": "Small Cap (Size)",
        "VTV": "Value (Style)",
    }

    # 机构标准参与率（ADV 的 10%）
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
    #  公共接口
    # ══════════════════════════════════════════════════════════
    def run(self) -> RiskReport:
        """执行全部风险计算。"""
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

        # ── 动态无风险利率 ────────────────────────────────────
        report.risk_free_rate = self._fetch_risk_free_rate()

        # ── 协方差矩阵（传统 + EWMA）────────────────────────
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

        # ── 蒙特卡洛 VaR / CVaR（使用 EWMA 协方差）─────────
        mc_port = self._monte_carlo_var(returns, weights, ewma_cov_daily)
        report.mc_portfolio_returns = mc_port
        report.var_95 = float(-np.percentile(mc_port, 5))
        report.var_99 = float(-np.percentile(mc_port, 1))
        report.cvar_95 = float(-mc_port[mc_port <= np.percentile(mc_port, 5)].mean())

        # ── 年化收益 / 波动率 / 夏普 ─────────────────────────
        port_daily = returns.dot(weights)
        report.annual_return = float(port_daily.mean() * self.TRADING_DAYS)
        ewma_port_var = float(weights @ ewma_cov_daily @ weights) * self.TRADING_DAYS
        report.annual_volatility = float(np.sqrt(ewma_port_var))
        report.sharpe_ratio = self._sharpe(
            report.annual_return, report.annual_volatility, report.risk_free_rate
        )

        # ── 最大回撤 ─────────────────────────────────────────
        cum = (1 + port_daily).cumprod()
        running_max = cum.cummax()
        dd = (cum - running_max) / running_max
        report.max_drawdown = float(dd.min())
        report.drawdown_series = dd

        # ── 单因子 Beta (SPY) ────────────────────────────────
        report.betas = self._compute_betas(returns, self.benchmark_ticker)

        # ── 多因子 Beta (SPY/QQQ/GLD/TLT) ───────────────────
        factor_result = self._compute_multi_factor_betas(returns)
        report.factor_betas = factor_result["betas"]
        report.factor_betas_significance = factor_result["significance"]

        # ── 压力测试 (uses user-configured market_shock, not default) ───
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

        # ── 成分 VaR ─────────────────────────────────────────
        report.component_var_pct = self._component_var(ewma_cov_daily, weights, returns.columns)

        # ── 滚动相关性 ───────────────────────────────────────
        report.rolling_corr_with_port = self._rolling_correlation_with_portfolio(
            returns, weights, window=60
        )

        # ── 回撤统计 ─────────────────────────────────────────
        report.drawdown_stats = self._drawdown_statistics(dd)

        # ── v2.1: 宏观敏感度 ─────────────────────────────────
        report.macro_betas = self._compute_macro_betas(returns, weights)

        # ── v2.1: 流动性风险 ─────────────────────────────────
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
    #  保证金 / 有效前沿 / 历史情景（保持不变）
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

    # ── 风控合规检查 ───────────────────────────────────────

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
        sector_weights = {}
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
    #  内部方法
    # ══════════════════════════════════════════════════════════

    # ── 无风险利率 ────────────────────────────────────────────
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

    # ── EWMA 协方差 ──────────────────────────────────────────
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

    # ── 蒙特卡洛 ─────────────────────────────────────────────
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

    # ── 单因子 Beta ──────────────────────────────────────────
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

    # ── Beta统计显著性检验 ───────────────────────────────────
    def _compute_beta_with_significance(
        self, asset_returns: np.ndarray, factor_returns: np.ndarray
    ) -> dict:
        """
        计算Beta及统计显著性（单因子OLS回归）

        Args:
            asset_returns: 资产收益率 (T,)
            factor_returns: 因子收益率 (T,)

        Returns:
            {
                'beta': float,           # 因子beta系数
                'intercept': float,      # 截距（alpha）
                't_stat': float,         # t统计量
                'p_value': float,        # p值（双尾检验）
                'is_significant': bool,  # 是否显著（p<0.05）
                'r_squared': float,      # 拟合优度
                'std_error': float       # 标准误
            }
        """
        from scipy import stats

        # 添加截距项
        n = len(asset_returns)
        X = np.column_stack([np.ones(n), factor_returns])
        y = asset_returns

        # OLS回归
        try:
            beta_coefs, residuals, rank, s = np.linalg.lstsq(X, y, rcond=None)
        except np.linalg.LinAlgError:
            # 奇异矩阵
            return {
                "beta": np.nan,
                "intercept": np.nan,
                "t_stat": np.nan,
                "p_value": np.nan,
                "is_significant": False,
                "r_squared": np.nan,
                "std_error": np.nan,
            }

        # 计算统计量
        k = X.shape[1]  # 参数数量（2: 截距+斜率）

        # 残差标准差
        if len(residuals) > 0:
            mse = residuals[0] / (n - k)
        else:
            # lstsq对秩亏矩阵可能不返回residuals
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

        # Beta的方差-协方差矩阵
        try:
            XtX_inv = np.linalg.inv(X.T @ X)
            var_covar = mse * XtX_inv
            std_errors = np.sqrt(var_covar.diagonal())
        except np.linalg.LinAlgError:
            # 完全共线
            std_errors = np.full(k, np.nan)

        # t统计量 = beta / se(beta)
        t_stats = np.full(k, np.nan)
        for i in range(k):
            if std_errors[i] > 0:
                t_stats[i] = beta_coefs[i] / std_errors[i]

        # p值（双尾检验）
        p_values = np.full(k, np.nan)
        for i in range(k):
            if not np.isnan(t_stats[i]):
                p_values[i] = 2 * (1 - stats.t.cdf(np.abs(t_stats[i]), df=n - k))

        # R²（拟合优度）
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

    # ── 多因子 Beta (SPY/QQQ/GLD/TLT) ───────────────────────
    def _compute_multi_factor_betas(self, returns):
        """
        计算多因子beta及统计显著性

        Returns:
            dict: {
                'betas': DataFrame,          # beta值表格
                'significance': DataFrame,   # 统计信息表格（t_stat, p_value等）
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

        aligned = pd.concat([returns, factor_ret], axis=1, join="inner").dropna()
        asset_cols = returns.columns
        factor_cols = [c for c in factor_ret.columns if c in aligned.columns]

        if len(aligned) < 60 or len(factor_cols) == 0:
            empty_df = pd.DataFrame(
                np.nan,
                index=returns.columns,
                columns=[self.FACTOR_TICKERS.get(f, f) for f in factor_tickers],
            )
            return {"betas": empty_df, "significance": pd.DataFrame()}

        # 存储beta值和统计信息
        beta_result = {}
        sig_result = []

        for ticker in asset_cols:
            if ticker not in aligned.columns:
                beta_result[ticker] = {self.FACTOR_TICKERS.get(f, f): np.nan for f in factor_cols}
                continue

            y = aligned[ticker].values
            beta_result[ticker] = {}

            # 对每个因子单独计算beta和显著性
            for f in factor_cols:
                X_factor = aligned[f].values
                factor_name = self.FACTOR_TICKERS.get(f, f)

                try:
                    stats = self._compute_beta_with_significance(y, X_factor)
                    beta_result[ticker][factor_name] = stats["beta"]

                    # 记录统计信息
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

    # ── Barra 风格因子风险归因 ────────────────────────────────
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
        total_factor_pnl = 0
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

    # ── 压力测试 ──────────────────────────────────────────────
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

    # ── 条件压力测试（黑天鹅冲击传导）────────────────────

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

    # ── 成分 VaR ─────────────────────────────────────────────
    def _component_var(self, cov_daily, weights, columns):
        port_var = float(weights @ cov_daily @ weights)
        if port_var <= 0:
            return pd.Series(np.zeros(len(weights)), index=columns)
        cov_w = cov_daily @ weights
        pct = (weights * cov_w) / port_var
        pct = np.nan_to_num(pct, nan=0.0, posinf=0.0, neginf=0.0)
        return pd.Series(pct, index=columns)

    # ── 滚动相关性 ───────────────────────────────────────────
    def _rolling_correlation_with_portfolio(self, returns, weights, window=60):
        port_ret = returns.dot(weights)
        return pd.DataFrame(
            {col: returns[col].rolling(window).corr(port_ret) for col in returns.columns}
        )

    # ── 回撤统计 ─────────────────────────────────────────────
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
    #  v2.1 新增：宏观敏感度 (Macro Beta)
    # ══════════════════════════════════════════════════════════
    def _compute_macro_betas(
        self,
        returns: pd.DataFrame,
        weights: np.ndarray,
    ) -> dict:
        """
        多元线性回归：Portfolio_Return ~ β1·ΔRate + β2·ΔUSD + β3·ΔOil + ε

        使用纯 numpy OLS (np.linalg.lstsq)，无需任何付费 API。

        Returns
        -------
        dict with keys:
            "betas"   : {factor_name: beta_value}  — 组合对各宏观因子的敏感度
            "r_squared": float                      — 回归 R²（宏观因子的解释力）
            "alpha"   : float                       — 截距项（alpha, 年化）
            "residual_vol": float                   — 残差波动率（年化）
            "t_stats" : {factor_name: t_statistic}  — t 统计量
            "per_asset": DataFrame                  — 每个资产对宏观因子的 beta
        """
        try:
            macro_ret = self.dp.get_macro_returns()
        except Exception as e:
            logger.error("Failed to fetch macro returns data", error=str(e))
            return self._empty_macro_result()

        # Degraded path: empty macro data (e.g. offline / provider failure)
        if macro_ret is None or macro_ret.empty:
            return self._empty_macro_result()

        # 组合日收益率
        port_daily = returns.dot(weights)

        # 对齐日期
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
        X_aug = np.column_stack([np.ones(len(X)), X])  # 加截距列

        # ── OLS：beta = (X'X)^{-1} X'y ──────────────────────
        beta, residuals, rank, sv = np.linalg.lstsq(X_aug, y, rcond=None)

        alpha = float(beta[0])
        factor_betas = {factor_names[i]: float(beta[i + 1]) for i in range(len(factor_names))}

        # ── R² ───────────────────────────────────────────────
        y_hat = X_aug @ beta
        ss_res = float(np.sum((y - y_hat) ** 2))
        ss_tot = float(np.sum((y - y.mean()) ** 2))
        r_squared = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0

        # ── 残差波动率（年化）──────────────────────────────────
        T = len(y)
        k = len(factor_names) + 1  # 含截距
        resid_var = ss_res / (T - k) if T > k else ss_res / max(T, 1)
        residual_vol = float(np.sqrt(resid_var) * np.sqrt(self.TRADING_DAYS))

        # ── t 统计量 ─────────────────────────────────────────
        t_stats = {}
        try:
            XtX_inv = np.linalg.inv(X_aug.T @ X_aug)
            se = np.sqrt(np.diag(XtX_inv) * resid_var)
            for i, fn in enumerate(factor_names):
                t_stats[fn] = float(beta[i + 1] / se[i + 1]) if se[i + 1] > 0 else 0.0
        except np.linalg.LinAlgError:
            t_stats = {fn: np.nan for fn in factor_names}

        # ── 每个资产的宏观 beta ──────────────────────────────
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
            "alpha": alpha * self.TRADING_DAYS,  # 年化
            "residual_vol": residual_vol,
            "t_stats": t_stats,
            "per_asset": per_asset_df,
        }

    def _empty_macro_result(self) -> dict:
        """宏观数据不可用时的空结果。"""
        return {
            "betas": {},
            "r_squared": 0.0,
            "alpha": 0.0,
            "residual_vol": 0.0,
            "t_stats": {},
            "per_asset": pd.DataFrame(),
        }

    # ══════════════════════════════════════════════════════════
    #  v2.1 新增：流动性风险 (Days to Liquidate)
    # ══════════════════════════════════════════════════════════
    def _compute_liquidity_risk(self) -> pd.DataFrame:
        """
        流动性风险分析。

        公式：Days to Liquidate = Shares / (ADV × Participation Rate)
        参与率 = 10%（机构标准：单日交易量中你的卖出不超过总量的 10%）

        Returns
        -------
        DataFrame with columns:
            Ticker, Shares, ADV_30d, Days_to_Liquidate,
            Liquidity_Tier, Market_Value_Pct
        """
        holdings = self.dp.holdings
        if not holdings:
            # 没有持仓股数信息，返回仅含 ADV 的表
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

            # 清仓天数
            tradable_per_day = avg_vol * self.LIQUIDITY_PARTICIPATION_RATE
            if tradable_per_day > 0 and shares > 0:
                days_to_liq = shares / tradable_per_day
            else:
                days_to_liq = np.nan

            # 流动性分级
            if np.isnan(days_to_liq) or avg_vol == 0:
                tier = "Unknown"
            elif days_to_liq < 0.01:
                tier = "Instant"  # 秒级清仓
            elif days_to_liq < 0.1:
                tier = "High"  # 分钟级
            elif days_to_liq < 1.0:
                tier = "Good"  # 当日可清
            elif days_to_liq < 5.0:
                tier = "Moderate"  # 1-5 日
            else:
                tier = "⚠️ Low"  # 超过 5 日

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
