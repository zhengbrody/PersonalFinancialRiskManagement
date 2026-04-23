"""
tests/integration/test_risk_pipeline.py
集成测试：DataProvider → RiskEngine 完整管道
使用合成数据，不依赖网络。
"""

import pytest
import numpy as np
import pandas as pd
from unittest.mock import patch, MagicMock

from data_provider import DataProvider
from risk_engine import RiskEngine, RiskReport


# ── Helpers ──────────────────────────────────────────────────

def _make_synthetic_prices(tickers, days=504, seed=42):
    """Generate synthetic price data for testing."""
    np.random.seed(seed)
    dates = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=days)
    prices = {}
    for tk in tickers:
        drift = np.random.uniform(0.0001, 0.001)
        vol = np.random.uniform(0.01, 0.03)
        log_returns = drift + vol * np.random.randn(days)
        prices[tk] = 100 * np.exp(np.cumsum(log_returns))
    return pd.DataFrame(prices, index=dates)


def _mock_yf_download(tickers_str, **kwargs):
    """Mock yf.download to return synthetic data."""
    if isinstance(tickers_str, str):
        tickers = tickers_str.split()
    else:
        tickers = list(tickers_str)

    # Filter out macro/benchmark tickers
    macro_tickers = {"^TNX", "DX-Y.NYB", "CL=F", "^IRX"}
    factor_tickers = {"SPY", "QQQ", "GLD", "TLT", "IWM", "VTV"}
    all_special = macro_tickers | factor_tickers

    real_tickers = [t for t in tickers if t not in macro_tickers]
    if not real_tickers:
        # Return dummy macro data
        dates = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=504)
        df = pd.DataFrame(
            {t: np.random.uniform(1, 5, len(dates)) for t in tickers},
            index=dates,
        )
        if len(tickers) > 1:
            df.columns = pd.MultiIndex.from_product([["Close"], tickers])
        else:
            df.columns = ["Close"]
        return df

    prices = _make_synthetic_prices(real_tickers, days=504)
    if len(real_tickers) == 1:
        df = prices.rename(columns={real_tickers[0]: "Close"})
    else:
        df = pd.DataFrame(
            {("Close", tk): prices[tk] for tk in real_tickers},
        )
        df.columns = pd.MultiIndex.from_tuples(df.columns)
        df.index = prices.index
    return df


# ── Fixtures ─────────────────────────────────────────────────

@pytest.fixture
def weights():
    return {"NVDA": 0.4, "SPY": 0.35, "GLD": 0.25}


@pytest.fixture
def data_provider(weights):
    with patch("data_provider.yf.download", side_effect=_mock_yf_download):
        dp = DataProvider(weights, period_years=2)
        yield dp


@pytest.fixture
def risk_engine(data_provider):
    engine = RiskEngine(
        data_provider,
        mc_simulations=5000,
        mc_horizon=21,
        risk_free_rate_fallback=0.045,
    )
    return engine


# ══════════════════════════════════════════════════════════════
#  Tests
# ══════════════════════════════════════════════════════════════

class TestDataProviderPipeline:
    """DataProvider 数据管道测试"""

    def test_returns_shape_and_columns(self, data_provider, weights):
        returns = data_provider.get_daily_returns()
        assert isinstance(returns, pd.DataFrame)
        assert len(returns) > 100
        for tk in weights:
            assert tk in returns.columns

    def test_returns_no_nans(self, data_provider):
        returns = data_provider.get_daily_returns()
        assert returns.isna().sum().sum() == 0

    def test_weight_array_order(self, data_provider, weights):
        returns = data_provider.get_daily_returns()
        w_arr = data_provider.get_weight_array()
        assert len(w_arr) == len(returns.columns)
        assert abs(w_arr.sum() - 1.0) < 0.01


class TestFullRiskPipeline:
    """DataProvider → RiskEngine.run() 完整管道"""

    @patch("data_provider.yf.download", side_effect=_mock_yf_download)
    @patch("data_provider.yf.download", side_effect=_mock_yf_download)
    def test_run_produces_valid_report(self, mock_dp, mock_re, weights):
        dp = DataProvider(weights, period_years=2)
        engine = RiskEngine(dp, mc_simulations=3000, mc_horizon=21,
                            risk_free_rate_fallback=0.045)
        report = engine.run()

        assert isinstance(report, RiskReport)
        # VaR should be positive (loss)
        assert report.var_95 > 0
        assert report.var_99 > 0
        assert report.var_99 >= report.var_95  # 99% VaR >= 95% VaR
        assert report.cvar_95 >= report.var_95  # CVaR >= VaR
        # Volatility should be positive
        assert report.annual_volatility > 0
        # Sharpe is a real number
        assert np.isfinite(report.sharpe_ratio)
        # Max drawdown should be negative
        assert report.max_drawdown <= 0

    @patch("data_provider.yf.download", side_effect=_mock_yf_download)
    @patch("data_provider.yf.download", side_effect=_mock_yf_download)
    def test_report_contains_all_fields(self, mock_dp, mock_re, weights):
        dp = DataProvider(weights, period_years=2)
        engine = RiskEngine(dp, mc_simulations=2000, mc_horizon=21,
                            risk_free_rate_fallback=0.045)
        report = engine.run()

        assert report.cov_matrix is not None
        assert report.corr_matrix is not None
        assert report.cov_matrix_ewma is not None
        assert report.mc_portfolio_returns is not None
        assert report.drawdown_series is not None
        assert isinstance(report.betas, dict)
        assert isinstance(report.stress_asset_losses, dict)

    @patch("data_provider.yf.download", side_effect=_mock_yf_download)
    @patch("data_provider.yf.download", side_effect=_mock_yf_download)
    def test_report_caching(self, mock_dp, mock_re, weights):
        """run() called twice should return the cached report."""
        dp = DataProvider(weights, period_years=2)
        engine = RiskEngine(dp, mc_simulations=2000, mc_horizon=21)
        r1 = engine.run()
        r2 = engine.run()
        assert r1 is r2


class TestMarginCall:
    """保证金预警计算"""

    @patch("data_provider.yf.download", side_effect=_mock_yf_download)
    @patch("data_provider.yf.download", side_effect=_mock_yf_download)
    def test_no_margin(self, mock_dp, mock_re, weights):
        dp = DataProvider(weights)
        engine = RiskEngine(dp, mc_simulations=1000)
        result = engine.compute_margin_call(100_000, 0)
        assert result["has_margin"] is False
        assert result["leverage"] == 1.0
        assert result["distance_to_call_pct"] == float("inf")

    @patch("data_provider.yf.download", side_effect=_mock_yf_download)
    @patch("data_provider.yf.download", side_effect=_mock_yf_download)
    def test_with_margin(self, mock_dp, mock_re, weights):
        dp = DataProvider(weights)
        engine = RiskEngine(dp, mc_simulations=1000)
        result = engine.compute_margin_call(100_000, 40_000, maintenance_ratio=0.25)
        assert result["has_margin"] is True
        assert result["leverage"] > 1.0
        assert 0 < result["distance_to_call_pct"] < 1.0
        assert result["margin_call_portfolio_value"] > 0


class TestComplianceWorkflow:
    """风控合规检查集成测试"""

    @patch("data_provider.yf.download", side_effect=_mock_yf_download)
    @patch("data_provider.yf.download", side_effect=_mock_yf_download)
    def test_violation_detected(self, mock_dp, mock_re, weights):
        dp = DataProvider(weights)
        engine = RiskEngine(dp, mc_simulations=1000)
        sector_map = {"NVDA": "Tech", "SPY": "ETF", "GLD": "Commodity"}
        proposed = {"NVDA": 0.50, "SPY": 0.30, "GLD": 0.20}
        violations = engine.check_trade_compliance(proposed, sector_map)
        # NVDA at 50% should violate 15% single stock limit
        assert len(violations) > 0
        assert any(v["ticker"] == "NVDA" for v in violations)

    @patch("data_provider.yf.download", side_effect=_mock_yf_download)
    @patch("data_provider.yf.download", side_effect=_mock_yf_download)
    def test_sector_violation(self, mock_dp, mock_re):
        weights = {"NVDA": 0.15, "AVGO": 0.15, "TSM": 0.15, "SPY": 0.55}
        dp = DataProvider(weights)
        engine = RiskEngine(dp, mc_simulations=1000)
        sector_map = {"NVDA": "Semi", "AVGO": "Semi", "TSM": "Semi", "SPY": "ETF"}
        violations = engine.check_trade_compliance(weights, sector_map)
        sector_violations = [v for v in violations if v["rule"] == "max_sector_weight"]
        assert len(sector_violations) > 0

    @patch("data_provider.yf.download", side_effect=_mock_yf_download)
    @patch("data_provider.yf.download", side_effect=_mock_yf_download)
    def test_adjust_weights(self, mock_dp, mock_re):
        # With max_single_stock=0.15 and max_sector=0.30 (the defaults), the
        # input below has every position over the per-stock cap — the
        # feasible solution caps all three at 0.15 and leaves the 0.55
        # residual as implicit cash. We explicitly do NOT renormalize back
        # to 1.0 since that would re-violate the caps we just enforced.
        weights = {"NVDA": 0.50, "SPY": 0.30, "GLD": 0.20}
        dp = DataProvider(weights)
        engine = RiskEngine(dp, mc_simulations=1000)
        sector_map = {"NVDA": "Tech", "SPY": "ETF", "GLD": "Commodity"}
        adjusted = engine.adjust_weights_for_compliance(weights, sector_map)
        # Every position respects the per-stock cap
        assert all(w <= 0.15 + 1e-9 for w in adjusted.values())
        # NVDA was reduced from 0.50
        assert adjusted["NVDA"] < 0.50
        # Feasibility: sum stays ≤ 1 (residual is cash, not an error)
        assert sum(adjusted.values()) <= 1.0 + 1e-9


class TestEfficientFrontier:
    """有效前沿计算"""

    @patch("data_provider.yf.download", side_effect=_mock_yf_download)
    @patch("data_provider.yf.download", side_effect=_mock_yf_download)
    def test_frontier_structure(self, mock_dp, mock_re, weights):
        dp = DataProvider(weights, period_years=2)
        engine = RiskEngine(dp, mc_simulations=1000)
        returns = dp.get_daily_returns()
        frontier = engine.compute_efficient_frontier(returns, risk_free=0.045, n_points=20)

        assert "frontier_vols" in frontier
        assert "frontier_rets" in frontier
        assert "max_sharpe_weights" in frontier
        assert "min_var_weights" in frontier
        assert "tickers" in frontier

        # Weights should sum to ~1
        ms_w = frontier["max_sharpe_weights"]
        assert abs(sum(ms_w.values()) - 1.0) < 0.05

        mv_w = frontier["min_var_weights"]
        assert abs(sum(mv_w.values()) - 1.0) < 0.05
