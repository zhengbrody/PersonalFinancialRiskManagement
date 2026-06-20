"""
tests/unit/test_regime.py
Unit tests for regime_detector.py
Covers: detect_regime_vol, detect_regime_trend, get_regime_transitions
All tests use synthetic data -- no network calls.
"""

import numpy as np
import pandas as pd
import pytest

import regime_detector as rd
from regime_detector import (
    REGIME_BEAR,
    REGIME_BULL,
    REGIME_HIGH_VOL,
    REGIME_LOW_VOL,
    REGIME_NORMAL_VOL,
    REGIME_RISK_ON,
    REGIME_TRANSITION,
    detect_regime_trend,
    detect_regime_vol,
    get_composite_regime,
    get_regime_transitions,
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
    labels = ["A"] * 10 + ["B"] * 5 + ["A"] * 8 + ["C"] * 7
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
        assert (
            bull_count / total > 0.5
        ), f"Expected >50% BULL in uptrend, got {bull_count/total:.1%}"

    def test_downtrend_mostly_bear(self, downtrend_prices):
        """A clear downtrend should produce majority BEAR classifications."""
        result = detect_regime_trend(downtrend_prices, sma_short=50, sma_long=200)
        regime_counts = result["regime"].value_counts()
        bear_count = regime_counts.get(REGIME_BEAR, 0)
        total = len(result)
        assert (
            bear_count / total > 0.5
        ), f"Expected >50% BEAR in downtrend, got {bear_count/total:.1%}"

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


# ══════════════════════════════════════════════════════════════
#  Composite regime v2 — signal-strength weighting (desk model)
# ══════════════════════════════════════════════════════════════


class TestVolScoreOneSided:
    """The headline fix: low realized vol is NEUTRAL, never bullish."""

    def test_low_vol_ratio_is_neutral_not_bullish(self):
        # ratio < 1 (calm) must score exactly 0 — NOT a positive/bullish signal.
        assert rd._vol_score(0.5) == 0.0
        assert rd._vol_score(0.95) == 0.0
        assert rd._vol_score(1.0) == 0.0

    def test_high_vol_ratio_is_risk_off(self):
        assert rd._vol_score(1.5) < 0
        assert rd._vol_score(1.5) == pytest.approx(-1.0, abs=1e-9)
        # monotonic: hotter vol -> more negative (saturating at -1)
        assert rd._vol_score(1.2) > rd._vol_score(1.4)

    def test_nan_safe(self):
        assert rd._vol_score(float("nan")) == 0.0
        assert rd._vol_score(None) == 0.0


class TestTrendScore:
    def test_above_below_sma(self):
        assert rd._trend_score(110, 100) == pytest.approx(1.0)  # 10% above -> full +1
        assert rd._trend_score(90, 100) == pytest.approx(-1.0)
        assert rd._trend_score(105, 100) == pytest.approx(0.5, abs=1e-6)
        assert rd._trend_score(100, 100) == pytest.approx(0.0, abs=1e-9)

    def test_clip_and_guards(self):
        assert rd._trend_score(200, 100) == 1.0  # clipped
        assert rd._trend_score(100, 0) == 0.0  # bad denom
        assert rd._trend_score(None, 100) == 0.0


class TestVixScore:
    def test_term_structure_sign(self):
        # contango (VIX < VIX3M, ratio < 1) = risk-on (+); backwardation = risk-off (-)
        assert rd._vix_score(0.9, 16) > 0
        assert rd._vix_score(1.1, 28) < 0

    def test_level_fallback_when_no_term(self):
        # no term ratio -> pure level: calm VIX positive, stressed negative
        assert rd._vix_score(None, 12) > 0
        assert rd._vix_score(None, 30) < 0
        assert rd._vix_score(None, 20) == pytest.approx(0.0, abs=1e-9)


class TestScoreRowAggregation:
    def test_vix_renormalizes_when_absent(self):
        # Same price/vol/hmm inputs; absent VIX must renormalize over 3 detectors,
        # never NaN, and stay in [-1, 1].
        s_no_vix, parts = rd._score_row(110, 100, 0.8, REGIME_RISK_ON)
        assert parts["vix"] is None
        assert -1.0 <= s_no_vix <= 1.0
        s_with_vix, parts2 = rd._score_row(110, 100, 0.8, REGIME_RISK_ON, 0.85, 15)
        assert parts2["vix"] is not None
        # risk-on VIX term pulls the composite further bullish than without it
        assert s_with_vix > s_no_vix

    def test_calm_uptrend_not_overbullish_from_low_vol(self):
        # A calm (low-vol) uptrend: vol contributes 0, NOT a bonus. The score comes
        # from trend (+) only, so it can't exceed the trend's own weighted ceiling.
        s, parts = rd._score_row(110, 100, 0.6, rd.REGIME_NORMAL)
        assert parts["vol"] == 0.0
        assert s > 0  # bullish from trend
        # equals trend weight share since vol/hmm are 0 (no vix): 0.35*1 / (0.35+0.15+0.20)
        assert s == pytest.approx(0.35 / 0.70, abs=1e-6)


class TestBandsAndDebounce:
    def test_band_label_thresholds(self):
        assert rd._band_label(0.6) == "Bullish"
        assert rd._band_label(0.3) == "Leaning Bullish"
        assert rd._band_label(0.0) == "Mixed / Transitional"
        assert rd._band_label(-0.3) == "Leaning Bearish"
        assert rd._band_label(-0.6) == "Bearish"

    def test_ribbon_vocab_backward_compatible(self):
        # ribbon stays {Bullish, Bearish, Mixed} so _find_regime_start_date matches
        assert rd._ribbon_label(0.5) == "Bullish"
        assert rd._ribbon_label(-0.5) == "Bearish"
        assert rd._ribbon_label(0.05) == "Mixed"

    def test_debounce_suppresses_one_day_blip(self):
        labels = ["Bullish", "Bullish", "Bearish", "Bullish", "Bullish"]
        out = rd._debounce_labels(labels, confirm_days=2)
        assert out[2] == "Bullish"  # single contrary day did NOT flip the headline
        assert out[-1] == "Bullish"

    def test_debounce_flips_after_confirmation(self):
        labels = ["Bullish", "Bearish", "Bearish", "Bearish"]
        out = rd._debounce_labels(labels, confirm_days=2)
        assert out[1] == "Bullish"  # not yet confirmed
        assert out[2] == "Bearish"  # confirmed after 2 consecutive


class TestCompositeV2EndToEnd:
    """get_composite_regime on synthetic data — no network."""

    def _synthetic(self, drift, n=420, seed=7):
        dates = pd.date_range("2022-01-03", periods=n, freq="B")
        rng = np.random.RandomState(seed)
        log_prices = np.cumsum(drift + rng.randn(n) * 0.004)
        prices = pd.Series(100.0 * np.exp(log_prices), index=dates)
        returns = np.log(prices / prices.shift(1)).dropna()
        return prices, returns

    def test_uptrend_is_bullish_with_continuous_confidence(self):
        prices, returns = self._synthetic(drift=0.0025)
        out = get_composite_regime(returns, prices)  # no vix_term -> price-only
        # backward-compatible keys all present
        for k in (
            "current_regime",
            "confidence",
            "vol_regime",
            "trend_regime",
            "hmm_regime",
            "history",
        ):
            assert k in out
        # new additive fields
        assert "composite_score" in out and "signal_breakdown" in out
        assert -1.0 <= out["composite_score"] <= 1.0
        assert "Bullish" in out["current_regime"]
        # confidence is now CONTINUOUS — not pinned to the old {0,.33,.67,1} set
        assert 0.0 <= out["confidence"] <= 1.0
        # history carries the additive score col + backward-compatible ribbon vocab
        h = out["history"]
        assert "composite_score" in h.columns and "composite_signal" in h.columns
        assert set(h["composite_signal"].unique()) <= {"Bullish", "Bearish", "Mixed"}

    def test_vix_term_folds_into_score(self):
        prices, returns = self._synthetic(drift=0.0015)
        # risk-on term structure (deep contango) over the whole window
        vix_term = pd.DataFrame({"ts_ratio": 0.85, "vix_level": 14.0}, index=prices.index)
        base = get_composite_regime(returns, prices)
        with_vix = get_composite_regime(returns, prices, vix_term=vix_term)
        assert with_vix["signal_breakdown"]["vix"] is not None
        assert base["signal_breakdown"]["vix"] is None
        # a risk-on VIX term structure should not reduce the bullish score
        assert with_vix["composite_score"] >= base["composite_score"] - 1e-9
