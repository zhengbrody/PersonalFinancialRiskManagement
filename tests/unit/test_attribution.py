"""
tests/unit/test_attribution.py
Unit tests for performance_attribution.py
Covers: brinson_attribution, factor_attribution,
        _tracking_error, _information_ratio
"""

import pytest
import numpy as np
import pandas as pd

from performance_attribution import (
    brinson_attribution,
    factor_attribution,
    _tracking_error,
    _information_ratio,
    _hit_ratio,
    TRADING_DAYS,
)


# ══════════════════════════════════════════════════════════════
#  Fixtures
# ══════════════════════════════════════════════════════════════

@pytest.fixture
def two_sector_data():
    """Simple 2-sector portfolio vs benchmark for Brinson attribution.

    Sector map: A -> "Tech", B -> "Energy"
    Portfolio: A=60%, B=40%  returns: A=+10%, B=-5%
    Benchmark: A=50%, B=50%  returns: A=+8%,  B=-2%
    """
    sector_map = {"A": "Tech", "B": "Energy"}
    portfolio_weights = {"A": 0.60, "B": 0.40}
    benchmark_weights = {"A": 0.50, "B": 0.50}
    portfolio_returns = {"A": 0.10, "B": -0.05}
    benchmark_returns = {"A": 0.08, "B": -0.02}
    return {
        "sector_map": sector_map,
        "portfolio_weights": portfolio_weights,
        "benchmark_weights": benchmark_weights,
        "portfolio_returns": portfolio_returns,
        "benchmark_returns": benchmark_returns,
    }


@pytest.fixture
def synthetic_factor_data():
    """Synthetic portfolio returns driven by a known factor.

    R_port = 0.0001 + 1.2 * F_market + 0.5 * F_size + noise
    252 observations.
    """
    np.random.seed(55)
    n = 252
    dates = pd.date_range("2023-01-03", periods=n, freq="B")

    f_market = np.random.randn(n) * 0.01
    f_size = np.random.randn(n) * 0.005
    noise = np.random.randn(n) * 0.001

    alpha_daily = 0.0001
    returns = alpha_daily + 1.2 * f_market + 0.5 * f_size + noise

    factor_df = pd.DataFrame(
        {"market": f_market, "size": f_size},
        index=dates,
    )
    port_returns = pd.Series(returns, index=dates)

    return port_returns, factor_df


@pytest.fixture
def active_returns_known():
    """Known active return series for tracking error / IR tests.

    252 observations, mean = 0.0002, std = 0.005 (daily).
    """
    np.random.seed(77)
    n = 252
    active = np.random.normal(0.0002, 0.005, n)
    return pd.Series(active, index=pd.date_range("2023-01-03", periods=n, freq="B"))


# ══════════════════════════════════════════════════════════════
#  Brinson attribution tests
# ══════════════════════════════════════════════════════════════

class TestBrinsonAttribution:
    """Brinson-Hood-Beebower sector attribution."""

    def test_returns_expected_keys(self, two_sector_data):
        """Result dict has the required keys."""
        result = brinson_attribution(
            portfolio_weights=two_sector_data["portfolio_weights"],
            benchmark_weights=two_sector_data["benchmark_weights"],
            portfolio_returns=two_sector_data["portfolio_returns"],
            benchmark_returns=two_sector_data["benchmark_returns"],
            sector_map=two_sector_data["sector_map"],
        )
        assert "total_active_return" in result
        assert "allocation_effect" in result
        assert "selection_effect" in result
        assert "interaction_effect" in result
        assert "sector_detail" in result

    def test_total_active_return_decomposition(self, two_sector_data):
        """allocation + selection + interaction = total active return."""
        result = brinson_attribution(
            portfolio_weights=two_sector_data["portfolio_weights"],
            benchmark_weights=two_sector_data["benchmark_weights"],
            portfolio_returns=two_sector_data["portfolio_returns"],
            benchmark_returns=two_sector_data["benchmark_returns"],
            sector_map=two_sector_data["sector_map"],
        )
        total = result["allocation_effect"] + result["selection_effect"] + result["interaction_effect"]
        assert total == pytest.approx(result["total_active_return"], abs=1e-10)

    def test_active_return_matches_direct_calculation(self, two_sector_data):
        """Total active return = port_return - bench_return."""
        pw = two_sector_data["portfolio_weights"]
        bw = two_sector_data["benchmark_weights"]
        pr = two_sector_data["portfolio_returns"]
        br = two_sector_data["benchmark_returns"]

        port_total = sum(pw[t] * pr[t] for t in pw)
        bench_total = sum(bw[t] * br[t] for t in bw)
        expected_active = port_total - bench_total

        result = brinson_attribution(
            portfolio_weights=pw,
            benchmark_weights=bw,
            portfolio_returns=pr,
            benchmark_returns=br,
            sector_map=two_sector_data["sector_map"],
        )
        assert result["total_active_return"] == pytest.approx(expected_active, abs=1e-10)

    def test_sector_detail_has_correct_sectors(self, two_sector_data):
        """sector_detail DataFrame should have both sectors."""
        result = brinson_attribution(
            portfolio_weights=two_sector_data["portfolio_weights"],
            benchmark_weights=two_sector_data["benchmark_weights"],
            portfolio_returns=two_sector_data["portfolio_returns"],
            benchmark_returns=two_sector_data["benchmark_returns"],
            sector_map=two_sector_data["sector_map"],
        )
        df = result["sector_detail"]
        assert set(df.index) == {"Tech", "Energy"}

    def test_identical_portfolios_zero_active(self):
        """When portfolio == benchmark, total active return is 0."""
        weights = {"X": 0.5, "Y": 0.5}
        returns = {"X": 0.10, "Y": -0.05}
        result = brinson_attribution(
            portfolio_weights=weights,
            benchmark_weights=weights,
            portfolio_returns=returns,
            benchmark_returns=returns,
            sector_map={"X": "A", "Y": "B"},
        )
        assert result["total_active_return"] == pytest.approx(0.0, abs=1e-10)


# ══════════════════════════════════════════════════════════════
#  Factor attribution tests
# ══════════════════════════════════════════════════════════════

class TestFactorAttribution:
    """Multi-factor regression attribution."""

    def test_factor_betas_recovery(self, synthetic_factor_data):
        """Factor betas should be close to the true betas (1.2, 0.5)."""
        port_returns, factor_df = synthetic_factor_data
        result = factor_attribution(port_returns, factor_df)

        assert result["factor_betas"]["market"] == pytest.approx(1.2, abs=0.15)
        assert result["factor_betas"]["size"] == pytest.approx(0.5, abs=0.15)

    def test_r_squared_high(self, synthetic_factor_data):
        """With low noise, R-squared should be high (>0.90)."""
        port_returns, factor_df = synthetic_factor_data
        result = factor_attribution(port_returns, factor_df)
        assert result["r_squared"] > 0.90

    def test_alpha_close_to_true(self, synthetic_factor_data):
        """Annualized alpha should be near 0.0001 * 252 ~ 0.0252."""
        port_returns, factor_df = synthetic_factor_data
        result = factor_attribution(port_returns, factor_df)
        expected_alpha = 0.0001 * TRADING_DAYS
        assert result["alpha"] == pytest.approx(expected_alpha, abs=0.05)

    def test_attribution_df_present(self, synthetic_factor_data):
        """Result should include an attribution DataFrame with Alpha and Residual rows."""
        port_returns, factor_df = synthetic_factor_data
        result = factor_attribution(port_returns, factor_df)
        df = result["attribution_df"]
        assert "Alpha" in df.index
        assert "Residual" in df.index
        assert "market" in df.index
        assert "size" in df.index

    def test_insufficient_data(self):
        """Very short data returns zero betas and 0 R-squared."""
        ret = pd.Series([0.01, 0.02], index=pd.date_range("2023-01-03", periods=2, freq="B"))
        factors = pd.DataFrame(
            {"f1": [0.005, 0.01]},
            index=ret.index,
        )
        result = factor_attribution(ret, factors)
        assert result["r_squared"] == 0.0
        assert result["factor_betas"]["f1"] == 0.0


# ══════════════════════════════════════════════════════════════
#  Tracking error and information ratio tests
# ══════════════════════════════════════════════════════════════

class TestTrackingError:
    """_tracking_error tests."""

    def test_known_tracking_error(self, active_returns_known):
        """TE = std(active) * sqrt(252).  Verify against known values."""
        te = _tracking_error(active_returns_known)
        expected = float(np.std(active_returns_known.values, ddof=1) * np.sqrt(TRADING_DAYS))
        assert te == pytest.approx(expected, rel=0.01)

    def test_zero_active_returns(self):
        """Zero active returns -> tracking error = 0."""
        active = np.zeros(100)
        # std of zeros with ddof=1 is 0
        assert _tracking_error(active) == 0.0

    def test_single_observation(self):
        """Single observation -> 0 (insufficient data)."""
        assert _tracking_error(np.array([0.01])) == 0.0


class TestInformationRatio:
    """_information_ratio tests."""

    def test_known_ir(self, active_returns_known):
        """IR = mean(active) / std(active) * sqrt(252)."""
        ir = _information_ratio(active_returns_known)
        vals = active_returns_known.values
        expected = float(np.mean(vals) / np.std(vals, ddof=1) * np.sqrt(TRADING_DAYS))
        assert ir == pytest.approx(expected, rel=0.01)

    def test_zero_std_returns_zero(self):
        """Constant active returns (std ~ 0) -> IR = 0."""
        active = np.full(100, 0.001)
        assert _information_ratio(active) == 0.0

    def test_positive_mean_positive_ir(self):
        """Positive mean active return yields positive IR."""
        np.random.seed(200)
        # Large positive mean to ensure sign stability
        active = np.random.normal(0.001, 0.005, 252)
        ir = _information_ratio(active)
        assert ir > 0.0


class TestHitRatio:
    """_hit_ratio tests."""

    def test_all_positive(self):
        """All positive active returns -> hit ratio = 1.0."""
        active = np.array([0.01, 0.02, 0.005])
        assert _hit_ratio(active) == pytest.approx(1.0)

    def test_half_positive(self):
        """Half positive, half negative -> hit ratio ~ 0.5."""
        active = np.array([0.01, -0.01, 0.01, -0.01])
        assert _hit_ratio(active) == pytest.approx(0.5)

    def test_empty(self):
        """Empty array -> 0."""
        assert _hit_ratio(np.array([])) == 0.0
