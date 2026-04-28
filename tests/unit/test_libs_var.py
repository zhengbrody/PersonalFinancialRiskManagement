"""Unit tests for libs.mindmarket_core.var (EWMA + Monte Carlo)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from libs.mindmarket_core import var


@pytest.fixture
def synthetic_returns():
    """3 assets, 2 years of trading days, low correlation."""
    rng = np.random.default_rng(42)
    days, n = 504, 3
    rets = rng.normal(0, 0.012, size=(days, n))
    return pd.DataFrame(rets, columns=["A", "B", "C"])


def test_ewma_covariance_shape_and_symmetry(synthetic_returns):
    cov = var.ewma_covariance(synthetic_returns)
    n = synthetic_returns.shape[1]
    assert cov.shape == (n, n)
    # Covariance must be symmetric
    np.testing.assert_allclose(cov, cov.T, atol=1e-12)
    # Diagonal must be non-negative (variances)
    assert np.all(np.diag(cov) >= 0)


def test_ewma_recovers_known_low_correlation(synthetic_returns):
    """Independent normal series → off-diagonal correlations are small.
    Sample correlation noise on 504 obs ~ 1/sqrt(504) ≈ 0.045, so ~0.2
    is a comfortable upper bound that catches real bugs without flaking."""
    cov = var.ewma_covariance(synthetic_returns)
    diag_sqrt = np.sqrt(np.diag(cov))
    corr = cov / np.outer(diag_sqrt, diag_sqrt)
    assert abs(corr[0, 1]) < 0.2
    assert abs(corr[0, 2]) < 0.2


def test_ewma_handles_short_series():
    rets = pd.DataFrame(np.array([[0.01, 0.02]]), columns=["A", "B"])
    cov = var.ewma_covariance(rets)
    # < 2 obs → identity per spec
    assert cov.shape == (2, 2)
    assert np.allclose(cov, np.eye(2))


def test_monte_carlo_returns_count_and_range(synthetic_returns):
    weights = np.array([0.5, 0.3, 0.2])
    cov = var.ewma_covariance(synthetic_returns)
    out = var.monte_carlo_returns(synthetic_returns, weights, cov, n_simulations=5000, horizon_days=21)
    assert out.shape == (5000,)
    # Realistic 21-day return distribution: mostly within ±50%
    assert -0.5 < np.percentile(out, 1) < 0.5
    assert -0.5 < np.percentile(out, 99) < 0.5


def test_monte_carlo_is_seed_deterministic(synthetic_returns):
    weights = np.array([0.5, 0.3, 0.2])
    cov = var.ewma_covariance(synthetic_returns)
    a = var.monte_carlo_returns(synthetic_returns, weights, cov, n_simulations=1000, seed=7)
    b = var.monte_carlo_returns(synthetic_returns, weights, cov, n_simulations=1000, seed=7)
    np.testing.assert_array_equal(a, b)


def test_var_cvar_signs_and_ordering(synthetic_returns):
    """VaR must be positive (it's a loss). CVaR >= VaR (CVaR is the
    average loss in the tail, by definition >= the threshold)."""
    weights = np.array([0.5, 0.3, 0.2])
    cov = var.ewma_covariance(synthetic_returns)
    mc = var.monte_carlo_returns(synthetic_returns, weights, cov, n_simulations=5000)
    v95, c95 = var.percentile_var_cvar(mc, 0.95)
    v99, c99 = var.percentile_var_cvar(mc, 0.99)
    assert v95 > 0
    assert v99 > 0
    assert c95 >= v95
    assert c99 >= v99
    # 99% VaR > 95% VaR (deeper into tail = bigger loss)
    assert v99 >= v95


def test_component_var_sums_to_one(synthetic_returns):
    weights = np.array([0.5, 0.3, 0.2])
    cov = var.ewma_covariance(synthetic_returns)
    cv = var.component_var(cov, weights, list(synthetic_returns.columns))
    assert abs(cv.sum() - 1.0) < 1e-9


def test_component_var_handles_zero_variance():
    cov = np.zeros((3, 3))
    weights = np.array([0.5, 0.3, 0.2])
    cv = var.component_var(cov, weights, ["A", "B", "C"])
    assert (cv == 0).all()


def test_monte_carlo_handles_non_psd_cov(synthetic_returns):
    """Pre-conditioner should add ridge if cov is singular."""
    weights = np.array([0.5, 0.3, 0.2])
    # Construct a singular cov (rank 1) and see Cholesky retry with ridge
    bad_cov = np.outer([1, 1, 1], [1, 1, 1]) * 0.0001
    out = var.monte_carlo_returns(synthetic_returns, weights, bad_cov, n_simulations=1000)
    assert out.shape == (1000,)
    assert not np.isnan(out).any()
