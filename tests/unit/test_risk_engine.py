"""
tests/unit/test_risk_engine.py
Comprehensive unit tests for risk_engine.py
Covers: RiskReport, RiskEngine init, margin call, compliance checks,
        efficient frontier, component VaR, rolling correlation, drawdown
        statistics, stress tests, conditional stress, macro betas,
        liquidity risk, factor risk attribution, and the full run() pipeline.
"""

import pytest
import numpy as np
import pandas as pd
from unittest.mock import Mock, patch
from datetime import datetime, timedelta

from risk_engine import RiskEngine, RiskReport
from data_provider import DataProvider


# ══════════════════════════════════════════════════════════════
#  Helpers / Fixtures
# ══════════════════════════════════════════════════════════════

@pytest.fixture
def mock_dp():
    """Create a minimal mock DataProvider."""
    dp = Mock(spec=DataProvider)
    dp.tickers = ["AAPL", "GOOGL", "MSFT"]
    dp.weights = {"AAPL": 0.4, "GOOGL": 0.3, "MSFT": 0.3}
    dp.holdings = {
        "AAPL": {"shares": 500},
        "GOOGL": {"shares": 200},
        "MSFT": {"shares": 300},
    }
    dp.start_date = pd.Timestamp("2022-01-01")
    dp.end_date = pd.Timestamp("2023-12-31")
    return dp


@pytest.fixture
def engine(mock_dp):
    """Create a RiskEngine with mock DataProvider."""
    return RiskEngine(
        data_provider=mock_dp,
        benchmark_ticker="SPY",
        mc_simulations=1000,
        mc_horizon=21,
        risk_free_rate_fallback=0.045,
    )


@pytest.fixture
def sample_returns():
    """252-day returns for 3 assets with controlled random state."""
    np.random.seed(42)
    dates = pd.date_range("2022-01-03", periods=252, freq="B")
    return pd.DataFrame(
        {
            "AAPL": np.random.randn(252) * 0.02,
            "GOOGL": np.random.randn(252) * 0.018,
            "MSFT": np.random.randn(252) * 0.015,
        },
        index=dates,
    )


@pytest.fixture
def sample_weights():
    return np.array([0.4, 0.3, 0.3])


# ══════════════════════════════════════════════════════════════
#  RiskReport dataclass
# ══════════════════════════════════════════════════════════════


class TestRiskReport:
    """Test the RiskReport dataclass defaults and mutability."""

    def test_default_values(self):
        r = RiskReport()
        assert r.var_95 == 0.0
        assert r.var_99 == 0.0
        assert r.cvar_95 == 0.0
        assert r.annual_return == 0.0
        assert r.annual_volatility == 0.0
        assert r.sharpe_ratio == 0.0
        assert r.max_drawdown == 0.0
        assert r.betas == {}
        assert r.stress_loss == 0.0
        assert r.stress_asset_losses == {}
        assert np.isnan(r.risk_free_rate)
        assert r.macro_betas is None
        assert r.liquidity_risk is None
        assert r.factor_betas is None
        assert r.factor_betas_significance is None
        assert r.cov_matrix is None
        assert r.cov_matrix_ewma is None
        assert r.corr_matrix is None
        assert r.corr_matrix_ewma is None
        assert r.mc_portfolio_returns is None
        assert r.drawdown_series is None
        assert r.component_var_pct is None
        assert r.rolling_corr_with_port is None
        assert r.drawdown_stats is None
        assert r.margin_call_info is None
        assert r.efficient_frontier is None

    def test_mutable_defaults_are_independent(self):
        """Verify that default mutable fields (dicts) are not shared."""
        r1 = RiskReport()
        r2 = RiskReport()
        r1.betas["SPY"] = 1.0
        assert "SPY" not in r2.betas

    def test_assign_fields(self):
        r = RiskReport()
        r.var_95 = 0.05
        r.var_99 = 0.09
        r.cvar_95 = 0.07
        r.annual_return = 0.12
        r.annual_volatility = 0.18
        r.sharpe_ratio = 0.55
        r.max_drawdown = -0.15
        assert r.var_95 == 0.05
        assert r.annual_return == 0.12
        assert r.max_drawdown == -0.15


# ══════════════════════════════════════════════════════════════
#  RiskEngine.__init__
# ══════════════════════════════════════════════════════════════


class TestRiskEngineInit:

    def test_default_init(self, mock_dp):
        eng = RiskEngine(mock_dp)
        assert eng.dp is mock_dp
        assert eng.benchmark_ticker == "SPY"
        assert eng.mc_simulations == 10_000
        assert eng.mc_horizon == 21
        assert eng.risk_free_rate_fallback == 0.045
        assert eng._report is None

    def test_custom_init(self, mock_dp):
        eng = RiskEngine(
            mock_dp,
            benchmark_ticker="QQQ",
            mc_simulations=5000,
            mc_horizon=10,
            risk_free_rate_fallback=0.03,
        )
        assert eng.benchmark_ticker == "QQQ"
        assert eng.mc_simulations == 5000
        assert eng.mc_horizon == 10
        assert eng.risk_free_rate_fallback == 0.03

    def test_negative_risk_free_rate_clamped(self, mock_dp):
        """Negative fallback rates should be clamped to 0."""
        eng = RiskEngine(mock_dp, risk_free_rate_fallback=-0.02)
        assert eng.risk_free_rate_fallback == 0.0

    def test_class_constants(self):
        assert RiskEngine.TRADING_DAYS == 252
        assert RiskEngine.EWMA_LAMBDA == 0.94
        assert "SPY" in RiskEngine.FACTOR_TICKERS
        assert RiskEngine.LIQUIDITY_PARTICIPATION_RATE == 0.10


# ══════════════════════════════════════════════════════════════
#  _sharpe
# ══════════════════════════════════════════════════════════════


class TestSharpe:

    def test_basic_sharpe(self, engine):
        # (0.10 - 0.02) / 0.15 = 0.5333...
        assert abs(engine._sharpe(0.10, 0.15, 0.02) - 0.5333) < 0.01

    def test_zero_volatility_returns_zero(self, engine):
        assert engine._sharpe(0.10, 0.0, 0.02) == 0.0

    def test_negative_sharpe(self, engine):
        result = engine._sharpe(-0.05, 0.20, 0.04)
        assert result < 0


# ══════════════════════════════════════════════════════════════
#  compute_margin_call
# ══════════════════════════════════════════════════════════════


class TestComputeMarginCall:

    def test_no_margin(self, engine):
        result = engine.compute_margin_call(total_long=100_000, margin_loan=0)
        assert result["has_margin"] is False
        assert result["leverage"] == 1.0
        assert result["distance_to_call_pct"] == float("inf")
        assert result["margin_call_portfolio_value"] == 0.0
        assert result["current_equity_ratio"] == 1.0
        assert result["buffer_dollars"] == 100_000

    def test_negative_margin_loan(self, engine):
        result = engine.compute_margin_call(total_long=100_000, margin_loan=-5000)
        assert result["has_margin"] is False

    def test_typical_margin(self, engine):
        # total_long=200k, margin_loan=100k, equity=100k, leverage=2x
        result = engine.compute_margin_call(
            total_long=200_000, margin_loan=100_000, maintenance_ratio=0.25
        )
        assert result["has_margin"] is True
        assert abs(result["leverage"] - 2.0) < 1e-6
        assert abs(result["current_equity_ratio"] - 0.5) < 1e-6
        # call_value = 100_000 / (1 - 0.25) = 133_333.33
        expected_call_value = 100_000 / 0.75
        assert abs(result["margin_call_portfolio_value"] - expected_call_value) < 0.1
        # distance = (200_000 - 133_333.33) / 200_000 = 0.3333
        expected_distance = (200_000 - expected_call_value) / 200_000
        assert abs(result["distance_to_call_pct"] - expected_distance) < 1e-4
        # buffer_dollars = 200_000 - 133_333.33 = 66_666.67
        assert abs(result["buffer_dollars"] - (200_000 - expected_call_value)) < 0.1
        # num_limit_downs = distance / 0.10
        assert abs(result["num_limit_downs"] - expected_distance / 0.10) < 1e-4

    def test_high_leverage(self, engine):
        # total_long=200k, margin_loan=180k, equity=20k => leverage=10x
        result = engine.compute_margin_call(
            total_long=200_000, margin_loan=180_000, maintenance_ratio=0.25
        )
        assert result["leverage"] == 10.0
        assert result["current_equity_ratio"] == 0.1
        # call_value = 180_000 / 0.75 = 240_000 > total_long => already in call
        assert result["buffer_dollars"] < 0

    def test_zero_total_long_with_margin(self, engine):
        result = engine.compute_margin_call(total_long=0, margin_loan=50_000)
        assert result["has_margin"] is True
        assert result["current_equity_ratio"] == 0
        assert result["distance_to_call_pct"] == 0


# ══════════════════════════════════════════════════════════════
#  check_trade_compliance
# ══════════════════════════════════════════════════════════════


class TestCheckTradeCompliance:

    def test_no_violations(self, engine):
        weights = {"AAPL": 0.10, "GOOGL": 0.10, "AMZN": 0.10, "TSLA": 0.10}
        sector_map = {
            "AAPL": "Tech", "GOOGL": "Tech",
            "AMZN": "Consumer", "TSLA": "Auto",
        }
        violations = engine.check_trade_compliance(weights, sector_map)
        assert violations == []

    def test_single_stock_violation(self, engine):
        weights = {"AAPL": 0.50, "GOOGL": 0.10, "MSFT": 0.10}
        sector_map = {"AAPL": "Tech", "GOOGL": "Cloud", "MSFT": "Software"}
        violations = engine.check_trade_compliance(weights, sector_map)
        stock_violations = [v for v in violations if v["rule"] == "max_single_stock_weight"]
        assert len(stock_violations) == 1
        assert stock_violations[0]["ticker"] == "AAPL"
        assert stock_violations[0]["actual"] == 0.50
        assert stock_violations[0]["severity"] == "hard"

    def test_sector_violation(self, engine):
        weights = {"AAPL": 0.15, "GOOGL": 0.15, "MSFT": 0.15}
        sector_map = {"AAPL": "Tech", "GOOGL": "Tech", "MSFT": "Tech"}
        violations = engine.check_trade_compliance(weights, sector_map)
        sector_violations = [v for v in violations if v["rule"] == "max_sector_weight"]
        assert len(sector_violations) == 1
        assert sector_violations[0]["sector"] == "Tech"
        assert abs(sector_violations[0]["actual"] - 0.45) < 1e-9

    def test_both_violations(self, engine):
        weights = {"AAPL": 0.50, "GOOGL": 0.30, "MSFT": 0.20}
        sector_map = {"AAPL": "Tech", "GOOGL": "Tech", "MSFT": "Tech"}
        violations = engine.check_trade_compliance(weights, sector_map)
        rules = {v["rule"] for v in violations}
        assert "max_single_stock_weight" in rules
        assert "max_sector_weight" in rules

    def test_custom_limits(self, engine):
        weights = {"AAPL": 0.25, "GOOGL": 0.25, "MSFT": 0.25, "AMZN": 0.25}
        sector_map = {
            "AAPL": "Tech", "GOOGL": "Tech",
            "MSFT": "Tech", "AMZN": "Retail",
        }
        custom = {"max_single_stock_weight": 0.30, "max_sector_weight": 0.50}
        violations = engine.check_trade_compliance(weights, sector_map, limits=custom)
        # All single stocks <= 0.30, Tech sector = 0.75 > 0.50
        stock_violations = [v for v in violations if v["rule"] == "max_single_stock_weight"]
        sector_violations = [v for v in violations if v["rule"] == "max_sector_weight"]
        assert len(stock_violations) == 0
        assert len(sector_violations) == 1

    def test_unknown_sector_defaults_to_other(self, engine):
        weights = {"AAPL": 0.10, "UNKNOWN": 0.10}
        sector_map = {"AAPL": "Tech"}
        violations = engine.check_trade_compliance(weights, sector_map)
        assert violations == []


# ══════════════════════════════════════════════════════════════
#  adjust_weights_for_compliance
# ══════════════════════════════════════════════════════════════


class TestAdjustWeightsForCompliance:

    def test_already_compliant_unchanged(self, engine):
        weights = {"A": 0.10, "B": 0.10, "C": 0.10, "D": 0.10}
        sector = {"A": "S1", "B": "S2", "C": "S3", "D": "S4"}
        adjusted = engine.adjust_weights_for_compliance(weights, sector)
        # Already compliant, should be similar (but renormalized to 1)
        total = sum(adjusted.values())
        assert abs(total - 1.0) < 1e-6

    def test_single_stock_clipping(self, engine):
        weights = {"AAPL": 0.60, "GOOGL": 0.20, "MSFT": 0.20}
        sector_map = {"AAPL": "S1", "GOOGL": "S2", "MSFT": "S3"}
        adjusted = engine.adjust_weights_for_compliance(weights, sector_map)
        # After clipping, AAPL should be reduced from 0.60
        assert adjusted["AAPL"] < 0.60
        # Total should still sum to 1
        assert abs(sum(adjusted.values()) - 1.0) < 1e-6

    def test_sector_clipping(self, engine):
        weights = {"AAPL": 0.15, "GOOGL": 0.15, "MSFT": 0.15, "AMZN": 0.55}
        sector_map = {
            "AAPL": "Tech", "GOOGL": "Tech", "MSFT": "Tech", "AMZN": "Retail"
        }
        adjusted = engine.adjust_weights_for_compliance(weights, sector_map)
        # Total should sum to 1
        assert abs(sum(adjusted.values()) - 1.0) < 1e-6

    def test_output_sums_to_one(self, engine):
        weights = {"A": 0.50, "B": 0.30, "C": 0.20}
        sector_map = {"A": "X", "B": "X", "C": "Y"}
        adjusted = engine.adjust_weights_for_compliance(weights, sector_map)
        assert abs(sum(adjusted.values()) - 1.0) < 1e-6


# ══════════════════════════════════════════════════════════════
#  _component_var
# ══════════════════════════════════════════════════════════════


class TestComponentVaR:

    def test_component_var_sums_to_one(self, engine, sample_returns, sample_weights):
        cov_daily = sample_returns.cov().values
        comp = engine._component_var(cov_daily, sample_weights, sample_returns.columns)
        assert isinstance(comp, pd.Series)
        assert abs(comp.sum() - 1.0) < 1e-6

    def test_component_var_index(self, engine, sample_returns, sample_weights):
        cov_daily = sample_returns.cov().values
        comp = engine._component_var(cov_daily, sample_weights, sample_returns.columns)
        assert list(comp.index) == list(sample_returns.columns)

    def test_component_var_values_are_finite(self, engine, sample_returns, sample_weights):
        """With positive weights and a valid cov matrix, contributions are finite."""
        cov_daily = sample_returns.cov().values
        comp = engine._component_var(cov_daily, sample_weights, sample_returns.columns)
        assert not comp.isna().any()

    def test_component_var_zero_portfolio_variance(self, engine):
        """When portfolio variance is zero, component VaR should be all zeros."""
        cov_daily = np.zeros((2, 2))
        weights = np.array([0.5, 0.5])
        columns = pd.Index(["A", "B"])
        comp = engine._component_var(cov_daily, weights, columns)
        np.testing.assert_array_almost_equal(comp.values, [0.0, 0.0])

    def test_single_asset_component_var(self, engine):
        """Single asset portfolio: component VaR = 100%."""
        cov_daily = np.array([[0.0004]])
        weights = np.array([1.0])
        columns = pd.Index(["AAPL"])
        comp = engine._component_var(cov_daily, weights, columns)
        assert abs(comp["AAPL"] - 1.0) < 1e-6


# ══════════════════════════════════════════════════════════════
#  _rolling_correlation_with_portfolio
# ══════════════════════════════════════════════════════════════


class TestRollingCorrelation:

    def test_output_shape(self, engine, sample_returns, sample_weights):
        result = engine._rolling_correlation_with_portfolio(
            sample_returns, sample_weights, window=60
        )
        assert isinstance(result, pd.DataFrame)
        assert result.shape == sample_returns.shape

    def test_columns_match(self, engine, sample_returns, sample_weights):
        result = engine._rolling_correlation_with_portfolio(
            sample_returns, sample_weights, window=60
        )
        assert list(result.columns) == list(sample_returns.columns)

    def test_correlation_range(self, engine, sample_returns, sample_weights):
        result = engine._rolling_correlation_with_portfolio(
            sample_returns, sample_weights, window=60
        )
        # Drop NaN from warmup, correlations should be in [-1, 1]
        valid = result.dropna()
        assert (valid >= -1.0 - 1e-9).all().all()
        assert (valid <= 1.0 + 1e-9).all().all()

    def test_warmup_nans(self, engine, sample_returns, sample_weights):
        """First (window - 1) values should be NaN."""
        window = 60
        result = engine._rolling_correlation_with_portfolio(
            sample_returns, sample_weights, window=window
        )
        # First window-1 rows should be NaN
        assert result.iloc[: window - 1].isna().all().all()
        # After warmup there should be valid values
        assert result.iloc[window:].notna().all().all()


# ══════════════════════════════════════════════════════════════
#  _drawdown_statistics
# ══════════════════════════════════════════════════════════════


class TestDrawdownStatistics:

    def _make_drawdown_series(self, values):
        """Helper to build a drawdown pd.Series from a list of values."""
        return pd.Series(values, index=pd.date_range("2022-01-01", periods=len(values)))

    def test_no_drawdown(self, engine):
        """All values above threshold => no episodes."""
        dd = self._make_drawdown_series([0.0] * 50)
        stats = engine._drawdown_statistics(dd)
        assert stats["num_episodes"] == 0
        assert stats["avg_episode_days"] == 0
        assert stats["max_episode_days"] == 0
        assert stats["pct_time_underwater"] == 0.0
        assert stats["is_currently_underwater"] is False
        assert stats["current_episode_days"] is None

    def test_single_episode(self, engine):
        vals = [0.0] * 10 + [-0.02] * 5 + [0.0] * 10
        dd = self._make_drawdown_series(vals)
        stats = engine._drawdown_statistics(dd)
        assert stats["num_episodes"] == 1
        assert stats["max_episode_days"] == 5
        assert stats["is_currently_underwater"] is False

    def test_multiple_episodes(self, engine):
        vals = [0.0] * 5 + [-0.02] * 3 + [0.0] * 5 + [-0.03] * 7 + [0.0] * 5
        dd = self._make_drawdown_series(vals)
        stats = engine._drawdown_statistics(dd)
        assert stats["num_episodes"] == 2
        assert stats["max_episode_days"] == 7
        assert abs(stats["avg_episode_days"] - 5.0) < 0.1

    def test_currently_underwater(self, engine):
        vals = [0.0] * 5 + [-0.02] * 10
        dd = self._make_drawdown_series(vals)
        stats = engine._drawdown_statistics(dd)
        assert stats["is_currently_underwater"] is True
        assert stats["current_episode_days"] == 10

    def test_pct_time_underwater(self, engine):
        vals = [-0.02] * 50 + [0.0] * 50
        dd = self._make_drawdown_series(vals)
        stats = engine._drawdown_statistics(dd)
        assert abs(stats["pct_time_underwater"] - 50.0) < 0.1

    def test_threshold_boundary(self, engine):
        """Values exactly at -0.005 are not in drawdown (< -0.005 is strict)."""
        vals = [-0.005] * 10
        dd = self._make_drawdown_series(vals)
        stats = engine._drawdown_statistics(dd)
        assert stats["num_episodes"] == 0

    def test_just_below_threshold(self, engine):
        vals = [-0.006] * 10
        dd = self._make_drawdown_series(vals)
        stats = engine._drawdown_statistics(dd)
        assert stats["is_currently_underwater"] is True

    def test_return_keys(self, engine):
        dd = self._make_drawdown_series([0.0] * 10)
        stats = engine._drawdown_statistics(dd)
        expected_keys = {
            "num_episodes", "avg_episode_days", "max_episode_days",
            "median_episode_days", "pct_time_underwater",
            "is_currently_underwater", "current_episode_days",
            "episode_durations",
        }
        assert set(stats.keys()) == expected_keys


# ══════════════════════════════════════════════════════════════
#  _stress_test
# ══════════════════════════════════════════════════════════════


class TestStressTest:

    @patch("yfinance.download")
    def test_stress_test_basic(self, mock_yf, engine, sample_returns, sample_weights):
        """Stress test with a -10% market shock propagated via betas."""
        dates = sample_returns.index
        bench_prices = pd.Series(
            np.cumprod(1 + np.random.RandomState(42).randn(len(dates)) * 0.01) * 100,
            index=dates,
        )
        bench_df = pd.DataFrame({"Close": bench_prices})
        mock_yf.return_value = bench_df

        engine.dp.start_date = dates[0]
        engine.dp.end_date = dates[-1]

        port_loss, asset_losses = engine._stress_test(
            sample_returns, sample_weights, market_shock=-0.10
        )

        assert isinstance(port_loss, float)
        assert isinstance(asset_losses, dict)
        assert set(asset_losses.keys()) == set(sample_returns.columns)
        # With a negative shock, portfolio loss should be negative
        assert port_loss < 0

    @patch("yfinance.download")
    def test_stress_test_nan_betas_fallback(self, mock_yf, engine, sample_returns, sample_weights):
        """When yfinance fails, betas default to NaN then 1.0 fallback."""
        mock_yf.side_effect = Exception("Network error")
        engine.dp.start_date = sample_returns.index[0]
        engine.dp.end_date = sample_returns.index[-1]

        port_loss, asset_losses = engine._stress_test(
            sample_returns, sample_weights, market_shock=-0.10
        )

        # All betas should fallback to 1.0, so each asset loss = 1.0 * -0.10
        for ticker, loss in asset_losses.items():
            assert abs(loss - (-0.10)) < 1e-6


# ══════════════════════════════════════════════════════════════
#  compute_conditional_stress
# ══════════════════════════════════════════════════════════════


class TestConditionalStress:

    def test_no_matching_tickers(self, engine, sample_returns, sample_weights):
        scenario = {"BTC-USD": -0.50}
        result = engine.compute_conditional_stress(
            scenario, sample_returns, sample_weights, use_ewma=False
        )
        assert result["portfolio_loss"] == 0.0
        assert result["conditional_returns"] == {}
        assert "warning" in result

    def test_observed_tickers_shock_applied(self, engine, sample_returns, sample_weights):
        """When a portfolio ticker is shocked, its conditional return should match."""
        scenario = {"AAPL": -0.15}
        result = engine.compute_conditional_stress(
            scenario, sample_returns, sample_weights, use_ewma=False
        )
        assert abs(result["conditional_returns"]["AAPL"] - (-0.15)) < 1e-6
        assert "GOOGL" in result["conditional_returns"]
        assert "MSFT" in result["conditional_returns"]

    def test_portfolio_loss_direction(self, engine, sample_returns, sample_weights):
        """Large negative shock on biggest position should give negative portfolio return."""
        scenario = {"AAPL": -0.30}
        result = engine.compute_conditional_stress(
            scenario, sample_returns, sample_weights, use_ewma=False
        )
        assert result["portfolio_loss"] < 0

    def test_use_ewma_flag(self, engine, sample_returns, sample_weights):
        scenario = {"AAPL": -0.10}
        result_ewma = engine.compute_conditional_stress(
            scenario, sample_returns, sample_weights, use_ewma=True
        )
        result_simple = engine.compute_conditional_stress(
            scenario, sample_returns, sample_weights, use_ewma=False
        )
        # Both should complete and have same keys
        assert set(result_ewma.keys()) == set(result_simple.keys())

    def test_propagation_chain_sorted(self, engine, sample_returns, sample_weights):
        scenario = {"AAPL": -0.20}
        result = engine.compute_conditional_stress(
            scenario, sample_returns, sample_weights, use_ewma=False
        )
        chain = result["propagation_chain"]
        # Should be sorted by value ascending (most negative first)
        values = [v for _, v in chain]
        assert values == sorted(values)

    def test_return_structure(self, engine, sample_returns, sample_weights):
        scenario = {"AAPL": -0.10}
        result = engine.compute_conditional_stress(
            scenario, sample_returns, sample_weights
        )
        assert "conditional_returns" in result
        assert "portfolio_loss" in result
        assert "propagation_chain" in result
        assert "observed_tickers" in result

    def test_all_tickers_observed(self, engine, sample_returns, sample_weights):
        """When all tickers are in the scenario, propagation chain is empty."""
        scenario = {"AAPL": -0.10, "GOOGL": -0.05, "MSFT": -0.08}
        result = engine.compute_conditional_stress(
            scenario, sample_returns, sample_weights, use_ewma=False
        )
        assert result["propagation_chain"] == []
        # Portfolio loss should be weighted sum of shocks
        expected = 0.4 * (-0.10) + 0.3 * (-0.05) + 0.3 * (-0.08)
        assert abs(result["portfolio_loss"] - expected) < 1e-6


# ══════════════════════════════════════════════════════════════
#  _ewma_covariance
# ══════════════════════════════════════════════════════════════


class TestEWMACovariance:

    def test_symmetric(self, engine, sample_returns):
        cov = engine._ewma_covariance(sample_returns)
        np.testing.assert_array_almost_equal(cov, cov.T)

    def test_positive_diagonal(self, engine, sample_returns):
        cov = engine._ewma_covariance(sample_returns)
        assert (np.diag(cov) > 0).all()

    def test_shape(self, engine, sample_returns):
        cov = engine._ewma_covariance(sample_returns)
        n = sample_returns.shape[1]
        assert cov.shape == (n, n)

    def test_regime_change_weights_recent(self, engine):
        """EWMA should weight recent observations more."""
        np.random.seed(42)
        early = np.random.randn(126, 2) * 0.01
        late = np.random.randn(126, 2) * 0.04
        returns = pd.DataFrame(np.vstack([early, late]), columns=["A", "B"])

        simple_cov = returns.cov().values
        ewma_cov = engine._ewma_covariance(returns)

        # EWMA should have higher variance (emphasizes recent high-vol period)
        assert ewma_cov[0, 0] > simple_cov[0, 0]
        assert ewma_cov[1, 1] > simple_cov[1, 1]


# ══════════════════════════════════════════════════════════════
#  _fetch_risk_free_rate
# ══════════════════════════════════════════════════════════════


class TestFetchRiskFreeRate:

    @patch("yfinance.download")
    def test_successful_fetch(self, mock_yf, engine):
        # ^IRX returns in percentage points (e.g. 4.5 means 4.5%)
        mock_yf.return_value = pd.DataFrame(
            {"Close": [4.5, 4.6, 4.55]},
            index=pd.date_range("2023-01-01", periods=3),
        )
        rate = engine._fetch_risk_free_rate()
        # 4.55 / 100 = 0.0455
        assert abs(rate - 0.0455) < 1e-6

    @patch("yfinance.download")
    def test_fallback_on_failure(self, mock_yf, engine):
        mock_yf.side_effect = Exception("Network error")
        rate = engine._fetch_risk_free_rate()
        assert rate == engine.risk_free_rate_fallback

    @patch("yfinance.download")
    def test_fallback_on_unreasonable_rate(self, mock_yf, engine):
        # Rate of 20% should be rejected (> 0.15)
        mock_yf.return_value = pd.DataFrame(
            {"Close": [20.0]},
            index=pd.date_range("2023-01-01", periods=1),
        )
        rate = engine._fetch_risk_free_rate()
        assert rate == engine.risk_free_rate_fallback

    @patch("yfinance.download")
    def test_fallback_on_negative_rate(self, mock_yf, engine):
        mock_yf.return_value = pd.DataFrame(
            {"Close": [-1.0]},
            index=pd.date_range("2023-01-01", periods=1),
        )
        rate = engine._fetch_risk_free_rate()
        assert rate == engine.risk_free_rate_fallback

    @patch("yfinance.download")
    def test_multiindex_columns(self, mock_yf, engine):
        """Handle yfinance returning MultiIndex columns."""
        dates = pd.date_range("2023-01-01", periods=3)
        data = pd.DataFrame(
            [[4.5], [4.6], [4.55]],
            index=dates,
            columns=pd.MultiIndex.from_tuples([("Close", "^IRX")]),
        )
        mock_yf.return_value = data
        rate = engine._fetch_risk_free_rate()
        assert abs(rate - 0.0455) < 1e-6


# ══════════════════════════════════════════════════════════════
#  _compute_betas (single-factor)
# ══════════════════════════════════════════════════════════════


class TestComputeBetas:

    @patch("yfinance.download")
    def test_known_beta(self, mock_yf, engine, sample_returns):
        """Inject a benchmark whose returns are known, compute betas."""
        dates = sample_returns.index
        np.random.seed(99)
        bench_prices = pd.Series(
            np.exp(np.cumsum(np.random.randn(len(dates)) * 0.01)) * 100,
            index=dates,
        )
        mock_yf.return_value = pd.DataFrame({"Close": bench_prices})
        engine.dp.start_date = dates[0]
        engine.dp.end_date = dates[-1]

        betas = engine._compute_betas(sample_returns, "SPY")
        assert isinstance(betas, dict)
        assert set(betas.keys()) == set(sample_returns.columns)
        for val in betas.values():
            assert isinstance(val, float)

    @patch("yfinance.download")
    def test_beta_download_failure(self, mock_yf, engine, sample_returns):
        mock_yf.side_effect = Exception("Network error")
        engine.dp.start_date = sample_returns.index[0]
        engine.dp.end_date = sample_returns.index[-1]

        betas = engine._compute_betas(sample_returns, "SPY")
        # All betas should be NaN
        for val in betas.values():
            assert np.isnan(val)

    @patch("yfinance.download")
    def test_insufficient_data(self, mock_yf, engine, sample_returns):
        """When benchmark has fewer than 30 aligned points, beta should be NaN."""
        dates = sample_returns.index[:10]
        bench_prices = pd.Series(
            np.exp(np.cumsum(np.random.randn(10) * 0.01)) * 100,
            index=dates,
        )
        mock_yf.return_value = pd.DataFrame({"Close": bench_prices})
        engine.dp.start_date = dates[0]
        engine.dp.end_date = dates[-1]

        betas = engine._compute_betas(sample_returns, "SPY")
        for val in betas.values():
            assert np.isnan(val)


# ══════════════════════════════════════════════════════════════
#  _compute_macro_betas
# ══════════════════════════════════════════════════════════════


class TestComputeMacroBetas:

    def test_successful_macro_betas(self, engine, sample_returns, sample_weights):
        """Test macro beta calculation with mock macro data."""
        np.random.seed(42)
        macro_ret = pd.DataFrame(
            {
                "US10Y Rate": np.random.randn(252) * 0.005,
                "USD Index": np.random.randn(252) * 0.003,
                "Crude Oil": np.random.randn(252) * 0.015,
            },
            index=sample_returns.index,
        )
        engine.dp.get_macro_returns.return_value = macro_ret

        result = engine._compute_macro_betas(sample_returns, sample_weights)
        assert "betas" in result
        assert "r_squared" in result
        assert "alpha" in result
        assert "residual_vol" in result
        assert "t_stats" in result
        assert "per_asset" in result
        assert isinstance(result["betas"], dict)
        assert len(result["betas"]) == 3
        assert 0 <= result["r_squared"] <= 1

    def test_macro_data_unavailable(self, engine, sample_returns, sample_weights):
        engine.dp.get_macro_returns.side_effect = Exception("No data")
        result = engine._compute_macro_betas(sample_returns, sample_weights)
        assert result["betas"] == {}
        assert result["r_squared"] == 0.0

    def test_insufficient_aligned_data(self, engine, sample_returns, sample_weights):
        """When fewer than 60 aligned rows, should return empty result."""
        macro_ret = pd.DataFrame(
            {
                "US10Y Rate": np.random.randn(30) * 0.005,
                "USD Index": np.random.randn(30) * 0.003,
                "Crude Oil": np.random.randn(30) * 0.015,
            },
            index=pd.date_range("2025-06-01", periods=30),
        )
        engine.dp.get_macro_returns.return_value = macro_ret
        result = engine._compute_macro_betas(sample_returns, sample_weights)
        assert result["betas"] == {}

    def test_per_asset_shape(self, engine, sample_returns, sample_weights):
        np.random.seed(42)
        macro_ret = pd.DataFrame(
            {
                "US10Y Rate": np.random.randn(252) * 0.005,
                "USD Index": np.random.randn(252) * 0.003,
                "Crude Oil": np.random.randn(252) * 0.015,
            },
            index=sample_returns.index,
        )
        engine.dp.get_macro_returns.return_value = macro_ret
        result = engine._compute_macro_betas(sample_returns, sample_weights)
        per_asset = result["per_asset"]
        assert isinstance(per_asset, pd.DataFrame)
        assert set(per_asset.index) == set(sample_returns.columns)
        assert set(per_asset.columns) == {"US10Y Rate", "USD Index", "Crude Oil"}


# ══════════════════════════════════════════════════════════════
#  _empty_macro_result
# ══════════════════════════════════════════════════════════════


class TestEmptyMacroResult:

    def test_structure(self, engine):
        result = engine._empty_macro_result()
        assert result["betas"] == {}
        assert result["r_squared"] == 0.0
        assert result["alpha"] == 0.0
        assert result["residual_vol"] == 0.0
        assert result["t_stats"] == {}
        assert isinstance(result["per_asset"], pd.DataFrame)
        assert result["per_asset"].empty


# ══════════════════════════════════════════════════════════════
#  _compute_liquidity_risk
# ══════════════════════════════════════════════════════════════


class TestComputeLiquidityRisk:

    def test_with_holdings(self, engine):
        """Test liquidity risk with normal holdings data."""
        adv = pd.Series(
            [1_000_000, 500_000, 800_000],
            index=["AAPL", "GOOGL", "MSFT"],
        )
        engine.dp.get_adv_30d.return_value = adv

        result = engine._compute_liquidity_risk()
        assert isinstance(result, pd.DataFrame)
        assert "ADV_30d" in result.columns
        assert "Days_to_Liquidate" in result.columns
        assert "Liquidity_Tier" in result.columns
        assert "Shares" in result.columns
        assert len(result) == 3

    def test_liquidity_tiers(self, engine):
        """Test that tiers are correctly assigned based on days_to_liquidate."""
        engine.dp.holdings = {
            "A": {"shares": 1},         # tiny position => Instant
            "B": {"shares": 500},        # moderate
            "C": {"shares": 100_000},    # large position
        }
        engine.dp.tickers = ["A", "B", "C"]
        engine.dp.weights = {"A": 0.33, "B": 0.34, "C": 0.33}
        adv = pd.Series([1_000_000, 100_000, 10_000], index=["A", "B", "C"])
        engine.dp.get_adv_30d.return_value = adv

        result = engine._compute_liquidity_risk()
        # A: 1 / (1_000_000 * 0.10) = 0.00001 => Instant
        assert result.loc["A", "Liquidity_Tier"] == "Instant"
        # B: 500 / (100_000 * 0.10) = 0.05 => High (< 0.1)
        assert result.loc["B", "Liquidity_Tier"] == "High"

    def test_no_holdings(self, engine):
        """When holdings is empty, should still return ADV info."""
        engine.dp.holdings = {}
        adv = pd.Series([1_000_000], index=["AAPL"])
        engine.dp.get_adv_30d.return_value = adv

        result = engine._compute_liquidity_risk()
        assert isinstance(result, pd.DataFrame)
        assert "ADV_30d" in result.columns

    def test_adv_failure(self, engine):
        """When ADV data fails to load, should return empty DataFrame."""
        engine.dp.get_adv_30d.side_effect = Exception("No volume data")
        result = engine._compute_liquidity_risk()
        assert isinstance(result, pd.DataFrame)
        assert result.empty

    def test_zero_adv(self, engine):
        """Zero ADV should yield Unknown tier."""
        engine.dp.holdings = {"AAPL": {"shares": 100}}
        engine.dp.tickers = ["AAPL"]
        engine.dp.weights = {"AAPL": 1.0}
        adv = pd.Series([0], index=["AAPL"])
        engine.dp.get_adv_30d.return_value = adv

        result = engine._compute_liquidity_risk()
        assert result.loc["AAPL", "Liquidity_Tier"] == "Unknown"


# ══════════════════════════════════════════════════════════════
#  compute_efficient_frontier
# ══════════════════════════════════════════════════════════════


class TestEfficientFrontier:

    def test_basic_frontier(self, engine):
        """Test efficient frontier with synthetic returns."""
        np.random.seed(42)
        dates = pd.date_range("2022-01-01", periods=252)
        returns = pd.DataFrame(
            {
                "A": np.random.randn(252) * 0.02 + 0.0004,
                "B": np.random.randn(252) * 0.01 + 0.0002,
            },
            index=dates,
        )
        result = engine.compute_efficient_frontier(returns, risk_free=0.04, n_points=10)

        assert "frontier_vols" in result
        assert "frontier_rets" in result
        assert "frontier_weights" in result
        assert "max_sharpe_weights" in result
        assert "max_sharpe_ret" in result
        assert "max_sharpe_vol" in result
        assert "max_sharpe_ratio" in result
        assert "min_var_weights" in result
        assert "min_var_ret" in result
        assert "min_var_vol" in result
        assert "tickers" in result
        assert result["tickers"] == ["A", "B"]

    def test_frontier_weights_sum_to_one(self, engine):
        np.random.seed(42)
        returns = pd.DataFrame(
            {
                "A": np.random.randn(252) * 0.02 + 0.0004,
                "B": np.random.randn(252) * 0.01 + 0.0002,
            },
        )
        result = engine.compute_efficient_frontier(returns, risk_free=0.04, n_points=10)

        # Max sharpe weights sum to 1
        max_w = result["max_sharpe_weights"]
        assert abs(sum(max_w.values()) - 1.0) < 0.01

        # Min var weights sum to 1
        min_w = result["min_var_weights"]
        assert abs(sum(min_w.values()) - 1.0) < 0.01

        # Each frontier point weights sum to 1
        for w in result["frontier_weights"]:
            assert abs(sum(w) - 1.0) < 0.01

    def test_min_var_lower_vol(self, engine):
        """Min variance portfolio should have lower vol than max sharpe."""
        np.random.seed(42)
        returns = pd.DataFrame(
            {
                "A": np.random.randn(252) * 0.03 + 0.0006,
                "B": np.random.randn(252) * 0.01 + 0.0001,
            },
        )
        result = engine.compute_efficient_frontier(returns, risk_free=0.02, n_points=20)
        assert result["min_var_vol"] <= result["max_sharpe_vol"] + 1e-6


# ══════════════════════════════════════════════════════════════
#  compute_factor_risk_attribution (PCA-based)
# ══════════════════════════════════════════════════════════════


class TestFactorRiskAttribution:

    @patch("yfinance.download")
    def test_basic_attribution(self, mock_yf, engine, sample_returns, sample_weights):
        """Test PCA factor risk attribution returns correct structure."""
        mock_yf.side_effect = Exception("No network in tests")

        result = engine.compute_factor_risk_attribution(
            sample_returns, sample_weights, n_factors=3
        )

        assert "factor_names" in result
        assert "factor_var_contrib" in result
        assert "factor_pnl" in result
        assert "r_squared" in result
        assert "factor_exposures" in result
        assert "explained_variance_ratio" in result
        assert "portfolio_exposures" in result

    @patch("yfinance.download")
    def test_variance_contrib_sums_to_one(self, mock_yf, engine, sample_returns, sample_weights):
        mock_yf.side_effect = Exception("No network")
        result = engine.compute_factor_risk_attribution(
            sample_returns, sample_weights, n_factors=3
        )
        total = sum(result["factor_var_contrib"].values())
        assert abs(total - 1.0) < 0.05

    @patch("yfinance.download")
    def test_r_squared_range(self, mock_yf, engine, sample_returns, sample_weights):
        mock_yf.side_effect = Exception("No network")
        result = engine.compute_factor_risk_attribution(
            sample_returns, sample_weights, n_factors=3
        )
        assert 0 <= result["r_squared"] <= 1

    @patch("yfinance.download")
    def test_n_factors_capped(self, mock_yf, engine, sample_returns, sample_weights):
        """Requesting more factors than assets should be capped."""
        mock_yf.side_effect = Exception("No network")
        result = engine.compute_factor_risk_attribution(
            sample_returns, sample_weights, n_factors=10
        )
        # Only 3 assets, so at most 3 factors
        assert len(result["factor_names"]) == 3

    @patch("yfinance.download")
    def test_exposures_shape(self, mock_yf, engine, sample_returns, sample_weights):
        mock_yf.side_effect = Exception("No network")
        result = engine.compute_factor_risk_attribution(
            sample_returns, sample_weights, n_factors=2
        )
        exposure_df = result["factor_exposures"]
        assert isinstance(exposure_df, pd.DataFrame)
        assert exposure_df.shape == (3, 2)  # 3 assets, 2 factors


# ══════════════════════════════════════════════════════════════
#  compute_historical_scenarios
# ══════════════════════════════════════════════════════════════


class TestHistoricalScenarios:

    @patch("yfinance.download")
    def test_returns_dataframe(self, mock_yf, engine):
        """Even when yfinance fails, should return a DataFrame with scenario names."""
        mock_yf.side_effect = Exception("No network")
        weights_dict = {"AAPL": 0.5, "GOOGL": 0.5}
        result = engine.compute_historical_scenarios(weights_dict)
        assert isinstance(result, pd.DataFrame)
        assert "Scenario" in result.columns
        assert "Portfolio Return" in result.columns
        assert "Coverage" in result.columns
        assert len(result) == 5  # 5 preset scenarios

    @patch("yfinance.download")
    def test_successful_scenario(self, mock_yf, engine):
        """Test with mock data that produces valid scenario results."""
        dates = pd.date_range("2020-02-18", "2020-03-23", freq="B")
        prices = pd.DataFrame(
            {
                "AAPL": np.linspace(100, 70, len(dates)),
                "GOOGL": np.linspace(100, 75, len(dates)),
            },
            index=dates,
        )
        prices.columns = pd.MultiIndex.from_product([["Close"], ["AAPL", "GOOGL"]])
        mock_yf.return_value = prices

        weights_dict = {"AAPL": 0.5, "GOOGL": 0.5}
        result = engine.compute_historical_scenarios(weights_dict)
        assert isinstance(result, pd.DataFrame)


# ══════════════════════════════════════════════════════════════
#  Preset scenarios
# ══════════════════════════════════════════════════════════════


class TestPresetScenarios:

    def test_preset_scenarios_defined(self):
        presets = RiskEngine.PRESET_SCENARIOS
        assert "Taiwan Conflict" in presets
        assert "Rate Shock (+200bp)" in presets
        assert "Crypto Winter" in presets
        assert "Tech Meltdown" in presets
        assert "Oil Crisis (Proxy via Energy)" in presets


# ══════════════════════════════════════════════════════════════
#  Full run() pipeline
# ══════════════════════════════════════════════════════════════


class TestRunPipeline:

    @patch("yfinance.download")
    def test_run_returns_risk_report(self, mock_yf, engine, sample_returns, sample_weights):
        """Test that run() returns a fully populated RiskReport."""
        engine.dp.get_daily_returns.return_value = sample_returns
        engine.dp.get_weight_array.return_value = sample_weights

        dates = sample_returns.index
        engine.dp.start_date = dates[0]
        engine.dp.end_date = dates[-1]

        np.random.seed(42)
        bench_prices = pd.Series(
            np.exp(np.cumsum(np.random.randn(len(dates)) * 0.01)) * 100,
            index=dates,
        )

        def mock_download(tickers_arg, **kwargs):
            if tickers_arg == "^IRX":
                return pd.DataFrame(
                    {"Close": [4.5, 4.6, 4.55]},
                    index=pd.date_range("2023-01-01", periods=3),
                )
            elif isinstance(tickers_arg, str):
                return pd.DataFrame({"Close": bench_prices})
            else:
                factor_prices_data = {}
                for ft in tickers_arg:
                    factor_prices_data[ft] = pd.Series(
                        np.exp(np.cumsum(np.random.randn(len(dates)) * 0.01)) * 100,
                        index=dates,
                    )
                df = pd.DataFrame(factor_prices_data)
                df.columns = pd.MultiIndex.from_product([["Close"], df.columns])
                return df

        mock_yf.side_effect = mock_download

        macro_ret = pd.DataFrame(
            {
                "US10Y Rate": np.random.randn(len(dates)) * 0.005,
                "USD Index": np.random.randn(len(dates)) * 0.003,
                "Crude Oil": np.random.randn(len(dates)) * 0.015,
            },
            index=dates,
        )
        engine.dp.get_macro_returns.return_value = macro_ret

        adv = pd.Series([1_000_000, 500_000, 800_000], index=["AAPL", "GOOGL", "MSFT"])
        engine.dp.get_adv_30d.return_value = adv

        report = engine.run()

        assert isinstance(report, RiskReport)
        assert report.var_95 > 0
        assert report.var_99 > 0
        assert report.var_99 > report.var_95
        assert report.cvar_95 > 0
        assert isinstance(report.annual_return, float)
        assert isinstance(report.annual_volatility, float)
        assert report.annual_volatility > 0
        assert isinstance(report.sharpe_ratio, float)
        assert report.max_drawdown <= 0
        assert isinstance(report.betas, dict)
        assert report.cov_matrix is not None
        assert report.cov_matrix_ewma is not None
        assert report.corr_matrix is not None
        assert report.corr_matrix_ewma is not None
        assert report.mc_portfolio_returns is not None
        assert report.drawdown_series is not None
        assert report.component_var_pct is not None
        assert report.rolling_corr_with_port is not None
        assert report.drawdown_stats is not None
        assert report.factor_betas is not None
        assert report.factor_betas_significance is not None
        assert report.macro_betas is not None
        assert report.liquidity_risk is not None

    @patch("yfinance.download")
    def test_run_caches_result(self, mock_yf, engine, sample_returns, sample_weights):
        """Second call to run() should return cached report."""
        engine.dp.get_daily_returns.return_value = sample_returns
        engine.dp.get_weight_array.return_value = sample_weights
        engine.dp.start_date = sample_returns.index[0]
        engine.dp.end_date = sample_returns.index[-1]

        def mock_download(tickers_arg, **kwargs):
            dates = sample_returns.index
            if isinstance(tickers_arg, str):
                return pd.DataFrame(
                    {"Close": pd.Series(np.ones(len(dates)) * 100, index=dates)}
                )
            else:
                data = {}
                for t in tickers_arg:
                    data[t] = pd.Series(np.ones(len(dates)) * 100, index=dates)
                df = pd.DataFrame(data)
                df.columns = pd.MultiIndex.from_product([["Close"], df.columns])
                return df

        mock_yf.side_effect = mock_download

        macro_ret = pd.DataFrame(
            {
                "US10Y Rate": np.zeros(len(sample_returns)),
                "USD Index": np.zeros(len(sample_returns)),
                "Crude Oil": np.zeros(len(sample_returns)),
            },
            index=sample_returns.index,
        )
        engine.dp.get_macro_returns.return_value = macro_ret
        adv = pd.Series([1e6, 5e5, 8e5], index=["AAPL", "GOOGL", "MSFT"])
        engine.dp.get_adv_30d.return_value = adv

        report1 = engine.run()
        report2 = engine.run()
        assert report1 is report2

    @patch("yfinance.download")
    def test_run_ewma_corr_matrix_diagonal_is_one(
        self, mock_yf, engine, sample_returns, sample_weights
    ):
        """EWMA correlation matrix diagonal should be 1."""
        engine.dp.get_daily_returns.return_value = sample_returns
        engine.dp.get_weight_array.return_value = sample_weights
        engine.dp.start_date = sample_returns.index[0]
        engine.dp.end_date = sample_returns.index[-1]

        def mock_download(tickers_arg, **kwargs):
            dates = sample_returns.index
            if isinstance(tickers_arg, str):
                return pd.DataFrame(
                    {"Close": pd.Series(
                        np.exp(np.cumsum(np.random.randn(len(dates)) * 0.01)) * 100,
                        index=dates,
                    )}
                )
            else:
                data = {}
                for t in tickers_arg:
                    data[t] = pd.Series(
                        np.exp(np.cumsum(np.random.randn(len(dates)) * 0.01)) * 100,
                        index=dates,
                    )
                df = pd.DataFrame(data)
                df.columns = pd.MultiIndex.from_product([["Close"], df.columns])
                return df

        mock_yf.side_effect = mock_download
        np.random.seed(42)
        macro_ret = pd.DataFrame(
            {
                "US10Y Rate": np.random.randn(len(sample_returns)) * 0.005,
                "USD Index": np.random.randn(len(sample_returns)) * 0.003,
                "Crude Oil": np.random.randn(len(sample_returns)) * 0.015,
            },
            index=sample_returns.index,
        )
        engine.dp.get_macro_returns.return_value = macro_ret
        adv = pd.Series([1e6, 5e5, 8e5], index=["AAPL", "GOOGL", "MSFT"])
        engine.dp.get_adv_30d.return_value = adv

        report = engine.run()
        diag = np.diag(report.corr_matrix_ewma.values)
        np.testing.assert_array_almost_equal(diag, np.ones(len(diag)), decimal=5)


# ══════════════════════════════════════════════════════════════
#  Monte Carlo additional edge cases
# ══════════════════════════════════════════════════════════════


class TestMonteCarloEdgeCases:

    def test_cholesky_ridge_fallback(self):
        """Test that near-singular covariance triggers ridge fix."""
        np.random.seed(42)
        base = np.random.randn(252) * 0.02
        returns = pd.DataFrame({
            "A": base,
            "B": base,  # Perfectly correlated => singular cov
        })
        weights = np.array([0.5, 0.5])
        cov = returns.cov().values

        engine = RiskEngine(None, mc_simulations=500, mc_horizon=5)
        result = engine._monte_carlo_var(returns, weights, cov)
        assert len(result) == 500
        assert not np.isnan(result).any()

    def test_horizon_one(self):
        """Test MC with single-day horizon."""
        np.random.seed(42)
        returns = pd.DataFrame(np.random.randn(252, 2) * 0.01, columns=["A", "B"])
        weights = np.array([0.6, 0.4])
        cov = returns.cov().values

        engine = RiskEngine(None, mc_simulations=1000, mc_horizon=1)
        result = engine._monte_carlo_var(returns, weights, cov)
        assert len(result) == 1000


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
