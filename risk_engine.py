"""
risk_engine.py
风险引擎：蒙特卡洛 VaR、协方差矩阵、夏普比率、Beta、压力测试
新增：成分VaR归因、滚动相关性、回撤统计、历史情景
"""

import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from data_provider import DataProvider


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
    # 协方差 & 相关系数矩阵
    cov_matrix: Optional[pd.DataFrame] = None
    corr_matrix: Optional[pd.DataFrame] = None
    # 蒙特卡洛模拟路径 (用于前端绘图)
    mc_portfolio_returns: Optional[np.ndarray] = None
    # 压力测试
    stress_loss: float = 0.0
    stress_asset_losses: Dict[str, float] = field(default_factory=dict)
    # 回撤序列
    drawdown_series: Optional[pd.Series] = None
    # 成分VaR贡献度 (占组合总方差的%)
    component_var_pct: Optional[pd.Series] = None
    # 滚动相关性（与组合）
    rolling_corr_with_port: Optional[pd.DataFrame] = None
    # 回撤统计
    drawdown_stats: Optional[dict] = None


class RiskEngine:
    """核心风险计算引擎。"""

    TRADING_DAYS = 252
    RISK_FREE_RATE = 0.045  # 年化无风险利率

    def __init__(
        self,
        data_provider: DataProvider,
        benchmark_ticker: str = "SPY",
        mc_simulations: int = 10_000,
        mc_horizon: int = 21,
    ):
        self.dp = data_provider
        self.benchmark_ticker = benchmark_ticker
        self.mc_simulations = mc_simulations
        self.mc_horizon = mc_horizon

        self._report: Optional[RiskReport] = None

    # ══════════════════════════════════════════════════════════
    #  公共接口
    # ══════════════════════════════════════════════════════════
    def run(self) -> RiskReport:
        """执行全部风险计算，返回 RiskReport。"""
        if self._report is not None:
            return self._report

        returns = self.dp.get_daily_returns()
        weights = self.dp.get_weight_array()

        report = RiskReport()

        # 协方差 / 相关系数
        report.cov_matrix = returns.cov() * self.TRADING_DAYS
        report.corr_matrix = returns.corr()

        # 蒙特卡洛 VaR / CVaR
        mc_port = self._monte_carlo_var(returns, weights)
        report.mc_portfolio_returns = mc_port
        report.var_95 = float(-np.percentile(mc_port, 5))
        report.var_99 = float(-np.percentile(mc_port, 1))
        report.cvar_95 = float(-mc_port[mc_port <= np.percentile(mc_port, 5)].mean())

        # 年化收益 / 波动率 / 夏普
        port_daily = returns.dot(weights)
        report.annual_return = float(port_daily.mean() * self.TRADING_DAYS)
        report.annual_volatility = float(port_daily.std() * np.sqrt(self.TRADING_DAYS))
        report.sharpe_ratio = self._sharpe(report.annual_return, report.annual_volatility)

        # 最大回撤
        cum = (1 + port_daily).cumprod()
        running_max = cum.cummax()
        dd = (cum - running_max) / running_max
        report.max_drawdown = float(dd.min())
        report.drawdown_series = dd

        # Beta
        report.betas = self._compute_betas(returns)

        # 压力测试
        stress_loss, asset_losses = self._stress_test(returns, weights)
        report.stress_loss = stress_loss
        report.stress_asset_losses = asset_losses

        # 成分VaR贡献度
        report.component_var_pct = self._component_var(returns, weights)

        # 滚动相关性（与组合）
        report.rolling_corr_with_port = self._rolling_correlation_with_portfolio(
            returns, weights, window=60
        )

        # 回撤统计
        report.drawdown_stats = self._drawdown_statistics(dd)

        self._report = report
        return report

    def compute_historical_scenarios(self, weights_dict: dict) -> pd.DataFrame:
        """
        按需计算历史情景回报（需要额外下载数据，耗时较长）。
        Returns a DataFrame with columns: Scenario, Portfolio Return, Coverage.
        """
        import yfinance as yf

        scenarios = [
            ("2020 COVID Crash (Feb 19 – Mar 23, 2020)",  "2020-02-18", "2020-03-23"),
            ("2022 Bear Market (Full Year 2022)",          "2021-12-31", "2022-12-30"),
            ("2018 Q4 Selloff (Oct 1 – Dec 24, 2018)",    "2018-09-28", "2018-12-24"),
            ("2008 Financial Crisis (Jan 2008 – Mar 2009)","2008-01-02", "2009-03-09"),
            ("2022 Crypto Winter (Nov 2021 – Nov 2022)",  "2021-10-29", "2022-11-18"),
        ]

        tickers = list(weights_dict.keys())
        results = []

        for name, start, end in scenarios:
            try:
                raw = yf.download(
                    tickers, start=start, end=end,
                    auto_adjust=True, progress=False,
                )
                # Handle MultiIndex columns
                if isinstance(raw.columns, pd.MultiIndex):
                    prices = raw["Close"]
                    if isinstance(prices.columns, pd.MultiIndex):
                        prices = prices.droplevel(0, axis=1)
                elif len(tickers) == 1:
                    prices = raw[["Close"]].rename(columns={"Close": tickers[0]})
                else:
                    prices = raw

                available = [t for t in tickers if t in prices.columns]
                if not available:
                    raise ValueError("No tickers available")

                # Per-asset total return (first to last available price)
                rets = {}
                for t in available:
                    col = prices[t].dropna()
                    if len(col) >= 2:
                        rets[t] = float(col.iloc[-1] / col.iloc[0] - 1)

                if not rets:
                    raise ValueError("No valid price data")

                # Re-normalize weights for available tickers
                avail_w = {t: weights_dict[t] for t in rets if t in weights_dict}
                total_w = sum(avail_w.values())
                if total_w <= 0:
                    raise ValueError("Zero total weight")
                norm_w = {t: w / total_w for t, w in avail_w.items()}
                port_ret = sum(rets[t] * norm_w[t] for t in rets)

                results.append({
                    "Scenario": name,
                    "Portfolio Return": port_ret,
                    "Coverage": f"{len(rets)}/{len(tickers)} assets",
                })
            except Exception:
                results.append({
                    "Scenario": name,
                    "Portfolio Return": None,
                    "Coverage": "N/A",
                })

        return pd.DataFrame(results)

    # ══════════════════════════════════════════════════════════
    #  内部方法
    # ══════════════════════════════════════════════════════════
    def _monte_carlo_var(
        self, returns: pd.DataFrame, weights: np.ndarray
    ) -> np.ndarray:
        mean_daily = returns.mean().values
        cov_daily = returns.cov().values
        n_assets = len(mean_daily)

        L = np.linalg.cholesky(cov_daily)

        np.random.seed(42)
        portfolio_returns = np.zeros(self.mc_simulations)

        for i in range(self.mc_simulations):
            Z = np.random.normal(size=(self.mc_horizon, n_assets))
            daily_rets = mean_daily + Z @ L.T
            cum_ret = np.prod(1 + daily_rets @ weights) - 1
            portfolio_returns[i] = cum_ret

        return portfolio_returns

    def _sharpe(self, annual_ret: float, annual_vol: float) -> float:
        if annual_vol == 0:
            return 0.0
        return (annual_ret - self.RISK_FREE_RATE) / annual_vol

    def _compute_betas(self, returns: pd.DataFrame) -> Dict[str, float]:
        try:
            import yfinance as yf
            bench_data = yf.download(
                self.benchmark_ticker,
                start=self.dp.start_date.strftime("%Y-%m-%d"),
                end=self.dp.end_date.strftime("%Y-%m-%d"),
                auto_adjust=True,
                progress=False,
            )
            if isinstance(bench_data.columns, pd.MultiIndex):
                bench_close = bench_data["Close"].squeeze()
            else:
                bench_close = bench_data["Close"]
            bench_ret = np.log(bench_close / bench_close.shift(1)).dropna()
        except Exception:
            return {t: np.nan for t in returns.columns}

        betas = {}
        for ticker in returns.columns:
            aligned = pd.concat(
                [returns[ticker], bench_ret], axis=1, join="inner"
            ).dropna()
            if len(aligned) < 30:
                betas[ticker] = np.nan
                continue
            cov = np.cov(aligned.iloc[:, 0], aligned.iloc[:, 1])
            betas[ticker] = float(cov[0, 1] / cov[1, 1]) if cov[1, 1] != 0 else np.nan
        return betas

    def _stress_test(
        self,
        returns: pd.DataFrame,
        weights: np.ndarray,
        market_shock: float = -0.10,
    ) -> tuple:
        betas = self._compute_betas(returns)
        asset_losses = {}
        port_loss = 0.0
        for i, ticker in enumerate(returns.columns):
            b = betas.get(ticker, 1.0)
            if np.isnan(b):
                b = 1.0
            loss = b * market_shock
            asset_losses[ticker] = float(loss)
            port_loss += weights[i] * loss
        return float(port_loss), asset_losses

    def _component_var(
        self, returns: pd.DataFrame, weights: np.ndarray
    ) -> pd.Series:
        """
        成分VaR贡献度：Euler分解。
        每个资产对组合总方差的百分比贡献（合计=100%）。
        """
        cov = returns.cov().values
        port_var = float(weights @ cov @ weights)
        if port_var <= 0:
            return pd.Series(np.zeros(len(weights)), index=returns.columns)
        cov_w = cov @ weights          # shape (n,): Σw
        pct = (weights * cov_w) / port_var  # Euler decomposition; sums to 1.0
        return pd.Series(pct, index=returns.columns)

    def _rolling_correlation_with_portfolio(
        self,
        returns: pd.DataFrame,
        weights: np.ndarray,
        window: int = 60,
    ) -> pd.DataFrame:
        """每个资产与组合收益的滚动相关系数。"""
        port_ret = returns.dot(weights)
        result = {
            col: returns[col].rolling(window).corr(port_ret)
            for col in returns.columns
        }
        return pd.DataFrame(result)

    def _drawdown_statistics(self, dd_series: pd.Series) -> dict:
        """
        回撤期统计：记录每次入水到出水的持续交易日数。
        """
        is_dd = dd_series < -0.005  # 0.5% threshold to filter noise

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
