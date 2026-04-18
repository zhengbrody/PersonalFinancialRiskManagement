"""
tests/unit/test_regime.py
Unit tests for regime_detector.py
Covers: detect_regime_vol, detect_regime_trend, get_regime_transitions
All tests use synthetic data -- no network calls.
"""

import pytest
import numpy as np
import pandas as pd

from regime_detector import (
    detect_regime_vol,
    detect_regime_trend,
    get_regime_transitions,
    REGIME_HIGH_VOL,
    REGIME_LOW_VOL,
    REGIME_NORMAL_VOL,
    REGIME_BULL,
    REGIME_BEAR,
    REGIME_TRANSITION,
)


# ══════════════════════════════════════════════════════════════
#  Fixtures
# ══════════════════════════════════════════════════════════════

@pytest.fixture
def low_vol_returns():
    """500 days of very low volatility log returns (std ~ 0.002)."""
    np.random.seed(10)
    dates = pd.date_range("2021-01-04", periods=500, freq="B")
    return pd.Series(np.random.randn(500) * 0.002, index=dates)


@pytest.fixture
def high_vol_burst_returns():
    """Returns with a calm period followed by a high-vol burst.

    First 300 days: std ~ 0.005
    Last 200 days: std ~ 0.03 (6x increase)
    This ensures short_vol >> long_vol at the end.
    """
    np.random.seed(20)
    dates = pd.date_range("2021-01-04", periods=500, freq="B")
    calm = np.random.randn(300) * 0.005
    burst = np.random.randn(200) * 0.03
    returns = np.concatenate([calm, burst])
    return pd.Series(returns, index=dates)


@pytest.fixture
def uptrend_prices():
    """500 days of steadily rising prices (clear uptrend)."""
    dates = pd.date_range("2021-01-04", periods=500, freq="B")
    # Geometric growth with small noise, enough for SMA crossovers
    np.random.seed(30)
    noise = np.random.randn(500) * 0.002
    log_prices = np.cumsum(0.003 + noise)  # positive drift
    prices = 100.0 * np.exp(log_prices)
    return pd.Series(prices, index=dates)


@pytest.fixture
def downtrend_prices():
    """500 days of steadily falling prices (clear downtrend)."""
    dates = pd.date_range("2021-01-04", periods=500, freq="B")
    np.random.seed(40)
    noise = np.random.randn(500) * 0.002
    log_prices = np.cumsum(-0.003 + noise)  # negative drift
    prices = 100.0 * np.exp(log_prices)
    return pd.Series(prices, index=dates)


@pytest.fixture
def known_regime_series():
    """A simple hand-crafted regime series for transition testing."""
    labels = (
        ["A"] * 10 +
        ["B"] * 5 +
        ["A"] * 8 +
        ["C"] * 7
    )
    dates = pd.date_range("2023-01-02", periods=len(labels), freq="B")
    return pd.Series(labels, index=dates)


# ══════════════════════════════════════════════════════════════
#  detect_regime_vol tests
# ══════════════════════════════════════════════════════════════

class TestDetectRegimeVol:
    """Volatility-based regime detection."""

    def test_returns_dataframe(self, low_vol_returns):
        """detect_regime_vol returns a DataFrame with expected columns."""
        result = detect_regime_vol(low_vol_returns, short_window=21, long_window=252)
        assert isinstance(result, pd.DataFrame)
        assert "regime" in result.columns
        assert "short_vol" in result.columns
        assert "long_vol" in result.columns
        assert "vol_ratio" in result.columns

    def test_low_vol_regimes_present(self, low_vol_returns):
        """Constant low volatility should yield mostly NORMAL or LOW_VOL regimes."""
        result = detect_regime_vol(low_vol_returns, short_window=21, long_window=252)
        regime_counts = result["regime"].value_counts()
        # Should NOT have HIGH_VOL in a uniformly calm series
        high_vol_count = regime_counts.get(REGIME_HIGH_VOL, 0)
        total = len(result)
        assert high_vol_count / total < 0.1, "Expected very few HIGH_VOL in calm data"

    def test_high_vol_burst_detected(self, high_vol_burst_returns):
        """A sudden vol increase should produce HIGH_VOL classifications."""
        result = detect_regime_vol(high_vol_burst_returns, short_window=21, long_window=252)
        regime_counts = result["regime"].value_counts()
        # After the burst, recent short_vol >> long_vol, so HIGH_VOL should appear
        assert REGIME_HIGH_VOL in regime_counts.index, "Expected HIGH_VOL after volatility burst"
        assert regime_counts[REGIME_HIGH_VOL] >= 10, "Expected at least 10 HIGH_VOL days"

    def test_regime_values_valid(self, low_vol_returns):
        """All regime labels must be one of the valid constants."""
        result = detect_regime_vol(low_vol_returns, short_window=21, long_window=252)
        valid_regimes = {REGIME_HIGH_VOL, REGIME_LOW_VOL, REGIME_NORMAL_VOL}
        assert set(result["regime"].unique()).issubset(valid_regimes)


# ══════════════════════════════════════════════════════════════
#  detect_regime_trend tests
# ══════════════════════════════════════════════════════════════

class TestDetectRegimeTrend:
    """Trend-based (SMA crossover) regime detection."""

    def test_returns_dataframe(self, uptrend_prices):
        """detect_regime_trend returns DataFrame with expected columns."""
        result = detect_regime_trend(uptrend_prices, sma_short=50, sma_long=200)
        assert isinstance(result, pd.DataFrame)
        assert "regime" in result.columns
        assert "sma_short" in result.columns
        assert "sma_long" in result.columns

    def test_uptrend_mostly_bull(self, uptrend_prices):
        """A clear uptrend should produce majority BULL classifications."""
        result = detect_regime_trend(uptrend_prices, sma_short=50, sma_long=200)
        regime_counts = result["regime"].value_counts()
        bull_count = regime_counts.get(REGIME_BULL, 0)
        total = len(result)
        assert bull_count / total > 0.5, f"Expected >50% BULL in uptrend, got {bull_count/total:.1%}"

    def test_downtrend_mostly_bear(self, downtrend_prices):
        """A clear downtrend should produce majority BEAR classifications."""
        result = detect_regime_trend(downtrend_prices, sma_short=50, sma_long=200)
        regime_counts = result["regime"].value_counts()
        bear_count = regime_counts.get(REGIME_BEAR, 0)
        total = len(result)
        assert bear_count / total > 0.5, f"Expected >50% BEAR in downtrend, got {bear_count/total:.1%}"

    def test_regime_values_valid(self, uptrend_prices):
        """All trend regime labels must be valid."""
        result = detect_regime_trend(uptrend_prices, sma_short=50, sma_long=200)
        valid_regimes = {REGIME_BULL, REGIME_BEAR, REGIME_TRANSITION}
        assert set(result["regime"].unique()).issubset(valid_regimes)


# ══════════════════════════════════════════════════════════════
#  get_regime_transitions tests
# ══════════════════════════════════════════════════════════════

class TestGetRegimeTransitions:
    """Transition analysis on a known regime series."""

    def test_transition_matrix_shape(self, known_regime_series):
        """Transition matrix is square with unique regime labels."""
        result = get_regime_transitions(known_regime_series)
        tm = result["transition_matrix"]
        assert isinstance(tm, pd.DataFrame)
        assert set(tm.index) == {"A", "B", "C"}
        assert set(tm.columns) == {"A", "B", "C"}

    def test_transition_counts(self, known_regime_series):
        """Verify exact transition counts from the hand-crafted series.

        Transitions: A->B at index 10, B->A at index 15, A->C at index 23
        """
        result = get_regime_transitions(known_regime_series)
        tm = result["transition_matrix"]
        assert tm.loc["A", "B"] == 1
        assert tm.loc["B", "A"] == 1
        assert tm.loc["A", "C"] == 1
        # No C->anything, B->C, etc.
        assert tm.loc["C", "A"] == 0
        assert tm.loc["B", "C"] == 0

    def test_avg_duration(self, known_regime_series):
        """Check average duration per regime.

        Durations: A: [10, 8], B: [5], C: [7]
        """
        result = get_regime_transitions(known_regime_series)
        avg = result["avg_duration"]
        assert avg["A"] == pytest.approx(9.0, abs=0.1)  # (10+8)/2
        assert avg["B"] == pytest.approx(5.0, abs=0.1)
        assert avg["C"] == pytest.approx(7.0, abs=0.1)

    def test_current_duration(self, known_regime_series):
        """Current regime (C) has been active for 7 days."""
        result = get_regime_transitions(known_regime_series)
        assert result["current_duration_days"] == 7

    def test_insufficient_data(self):
        """Single-element series returns empty results."""
        short = pd.Series(["A"], index=pd.date_range("2023-01-02", periods=1))
        result = get_regime_transitions(short)
        assert result["current_duration_days"] == 0
        assert len(result["transition_matrix"]) == 0
