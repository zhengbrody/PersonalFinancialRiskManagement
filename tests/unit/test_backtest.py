"""
tests/unit/test_backtest.py
Unit tests for backtest_engine.py
Covers: BacktestResult, _sharpe_ratio, _sortino_ratio, _calmar_ratio,
        _max_drawdown, _alpha_beta, run_backtest (mocked yfinance)
"""

import pytest
import numpy as np
import pandas as pd
from unittest.mock import patch, MagicMock

from backtest_engine import (
    BacktestResult,
    _sharpe_ratio,
    _sortino_ratio,
    _calmar_ratio,
    _max_drawdown,
    _alpha_beta,
    _win_rate,
    run_backtest,
    TRADING_DAYS_PER_YEAR,
)


# ══════════════════════════════════════════════════════════════
#  Fixtures
# ══════════════════════════════════════════════════════════════

@pytest.fixture
def flat_returns():
    """252 days of zero returns."""
    return pd.Series(np.zeros(252), index=pd.date_range("2023-01-03", periods=252, freq="B"))


@pytest.fixture
def positive_returns():
    """252 days of constant +0.1% daily return."""
    return pd.Series(
        np.full(252, 0.001),
        index=pd.date_range("2023-01-03", periods=252, freq="B"),
    )


@pytest.fixture
def mixed_returns():
    """Alternating +1% / -1% returns with a slight positive bias."""
    np.random.seed(42)
    ret = np.random.randn(252) * 0.01
    return pd.Series(ret, index=pd.date_range("2023-01-03", periods=252, freq="B"))


@pytest.fixture
def simple_equity():
    """Equity curve that rises from 100 to 80 (drawdown) then to 120."""
    values = np.concatenate([
        np.linspace(100, 80, 50),   # drawdown
        np.linspace(80, 120, 50),   # recovery
    ])
    dates = pd.date_range("2023-01-03", periods=100, freq="B")
    return pd.Series(values, index=dates)


# ══════════════════════════════════════════════════════════════
#  BacktestResult dataclass
# ══════════════════════════════════════════════════════════════

class TestBacktestResult:
    """BacktestResult construction and defaults."""

    def test_default_values(self):
        """All scalar defaults should be zero or None."""
        r = BacktestResult()
        assert r.total_return == 0.0
        assert r.annual_return == 0.0
        assert r.sharpe_ratio == 0.0
        assert r.max_drawdown == 0.0
        assert r.equity_curve is None
        assert r.strategy_name == ""
        assert r.weights is None
        assert r.benchmark_total_return is None

    def test_custom_values(self):
        """Custom values are stored correctly."""
        r = BacktestResult(
            total_return=0.15,
            sharpe_ratio=1.5,
            strategy_name="test_strategy",
        )
        assert r.total_return == 0.15
        assert r.sharpe_ratio == 1.5
        assert r.strategy_name == "test_strategy"


# ══════════════════════════════════════════════════════════════
#  Performance metric helpers
# ══════════════════════════════════════════════════════════════

class TestSharpeRatio:
    """_sharpe_ratio tests."""

    def test_zero_returns_zero_sharpe(self, flat_returns):
        """Zero returns -> zero Sharpe (zero std)."""
        assert _sharpe_ratio(flat_returns) == 0.0

    def test_positive_returns_positive_sharpe(self):
        """Varied positive-biased returns yield positive Sharpe."""
        np.random.seed(99)
        returns = pd.Series(np.random.normal(0.001, 0.01, 252))
        sharpe = _sharpe_ratio(returns, rf=0.0)
        assert sharpe > 0.0

    def test_known_sharpe(self):
        """Verify Sharpe with known numbers."""
        # 252 days of returns with mean 0.001, std 0.01
        np.random.seed(123)
        returns = pd.Series(np.random.normal(0.001, 0.01, 252))
        sharpe = _sharpe_ratio(returns, rf=0.0)
        # Annualized sharpe ~ sqrt(252) * mean / std
        expected = np.sqrt(252) * returns.mean() / returns.std()
        assert sharpe == pytest.approx(expected, rel=0.01)

    def test_short_series(self):
        """Series with < 2 values returns 0."""
        assert _sharpe_ratio(pd.Series([0.01])) == 0.0


class TestSortinoRatio:
    """_sortino_ratio tests."""

    def test_all_positive_returns(self):
        """All positive returns -> no downside -> sortino = inf (all upside)."""
        ret = pd.Series(np.full(100, 0.01))
        # rf = 0, excess = 0.01, no negative excess -> sortino = inf
        assert _sortino_ratio(ret, rf=0.0) == float("inf")

    def test_mixed_returns_nonzero(self, mixed_returns):
        """Mixed returns should yield a non-zero Sortino ratio."""
        sortino = _sortino_ratio(mixed_returns, rf=0.0)
        assert isinstance(sortino, float)
        # Not zero because there are negative returns
        assert sortino != 0.0


class TestCalmarRatio:
    """_calmar_ratio tests."""

    def test_known_calmar(self):
        """annual_return=0.10 and max_drawdown=-0.20 -> calmar=0.5."""
        assert _calmar_ratio(0.10, -0.20) == pytest.approx(0.5)

    def test_zero_drawdown(self):
        """Zero drawdown -> calmar = 0 (guard clause)."""
        assert _calmar_ratio(0.10, 0.0) == 0.0


class TestMaxDrawdown:
    """_max_drawdown tests."""

    def test_known_drawdown(self, simple_equity):
        """Equity curve drops from 100 to 80 -> -20% drawdown."""
        mdd = _max_drawdown(simple_equity)
        assert mdd == pytest.approx(-0.20, abs=0.01)

    def test_monotonic_increase(self):
        """Monotonically increasing equity has zero drawdown."""
        eq = pd.Series(np.linspace(100, 200, 100))
        assert _max_drawdown(eq) == 0.0

    def test_short_series(self):
        """Single-element equity returns 0."""
        assert _max_drawdown(pd.Series([100.0])) == 0.0


class TestAlphaBeta:
    """_alpha_beta regression test."""

    def test_perfect_tracking(self):
        """Portfolio = benchmark -> alpha ~ 0, beta ~ 1."""
        np.random.seed(0)
        bench = pd.Series(
            np.random.randn(252) * 0.01,
            index=pd.date_range("2023-01-03", periods=252, freq="B"),
        )
        alpha, beta = _alpha_beta(bench, bench)
        assert alpha == pytest.approx(0.0, abs=0.01)
        assert beta == pytest.approx(1.0, abs=0.01)

    def test_double_beta(self):
        """Portfolio = 2x benchmark -> beta ~ 2."""
        np.random.seed(0)
        bench = pd.Series(
            np.random.randn(252) * 0.01,
            index=pd.date_range("2023-01-03", periods=252, freq="B"),
        )
        port = bench * 2.0
        alpha, beta = _alpha_beta(port, bench)
        assert beta == pytest.approx(2.0, abs=0.05)

    def test_insufficient_data(self):
        """Fewer than 10 aligned points returns (0, 0)."""
        short = pd.Series([0.01] * 5, index=pd.date_range("2023-01-03", periods=5, freq="B"))
        alpha, beta = _alpha_beta(short, short)
        assert alpha == 0.0
        assert beta == 0.0


class TestWinRate:
    """_win_rate tests."""

    def test_all_positive(self):
        """All positive returns -> 100% win rate."""
        ret = pd.Series([0.01, 0.02, 0.005])
        assert _win_rate(ret) == pytest.approx(1.0)

    def test_empty(self):
        """Empty series -> 0."""
        assert _win_rate(pd.Series(dtype=float)) == 0.0


# ══════════════════════════════════════════════════════════════
#  run_backtest with mocked yfinance
# ══════════════════════════════════════════════════════════════

class TestRunBacktest:
    """End-to-end backtest with mocked data download."""

    @patch("backtest_engine._download_prices")
    def test_run_backtest_basic(self, mock_download):
        """run_backtest produces a valid BacktestResult with synthetic data."""
        np.random.seed(42)
        dates = pd.date_range("2023-01-03", periods=252, freq="B")
        # Build synthetic price data (geometric random walk)
        aapl = 100.0 * np.cumprod(1 + np.random.randn(252) * 0.015)
        msft = 200.0 * np.cumprod(1 + np.random.randn(252) * 0.012)
        spy = 400.0 * np.cumprod(1 + np.random.randn(252) * 0.010)

        mock_download.return_value = pd.DataFrame(
            {"AAPL": aapl, "MSFT": msft, "SPY": spy},
            index=dates,
        )

        result = run_backtest(
            weights={"AAPL": 0.6, "MSFT": 0.4},
            start_date="2023-01-03",
            end_date="2024-01-03",
            rebalance_freq="M",
            benchmark="SPY",
        )

        assert isinstance(result, BacktestResult)
        assert result.equity_curve is not None
        assert len(result.equity_curve) == 252
        assert result.start_date is not None
        assert result.end_date is not None
        assert result.strategy_name == "static_weight"
        # Sharpe and drawdown are computed
        assert isinstance(result.sharpe_ratio, float)
        assert result.max_drawdown <= 0.0
        # Benchmark comparison is present
        assert result.benchmark_total_return is not None

    @patch("backtest_engine._download_prices")
    def test_run_backtest_no_valid_tickers_raises(self, mock_download):
        """run_backtest raises when no portfolio tickers are in downloaded data."""
        dates = pd.date_range("2023-01-03", periods=50, freq="B")
        mock_download.return_value = pd.DataFrame(
            {"SPY": np.linspace(400, 420, 50)},
            index=dates,
        )

        with pytest.raises(ValueError, match="None of the portfolio tickers"):
            run_backtest(
                weights={"AAPL": 0.5, "MSFT": 0.5},
                start_date="2023-01-03",
                end_date="2023-03-15",
                benchmark="SPY",
            )
