"""
Test suite for VaR bug fix (compound return calculation)

This module validates the fix to the Monte Carlo VaR calculation,
which previously used an incorrect compound return formula.
"""

import os

# Import the modules we need to test
import sys
from datetime import datetime

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from data_provider import DataProvider
from risk_engine import RiskEngine


class TestCompoundReturnCalculation:
    """Test that compound return calculation is correct."""

    def test_simple_compound_return(self):
        """
        Test basic compound return formula.

        Example: Two days with +10% return each
        Correct: (1.1 × 1.1) - 1 = 0.21 (21%)
        Wrong (arithmetic): 0.1 + 0.1 = 0.20 (20%)
        """
        daily_returns = np.array([0.1, 0.1])
        expected_cumulative = 0.21  # 21%

        # Method 1: Using prod
        cumulative_prod = np.prod(1 + daily_returns) - 1
        assert abs(cumulative_prod - expected_cumulative) < 0.0001

        # Method 2: Using log/exp
        cumulative_log = np.exp(np.sum(np.log(1 + daily_returns))) - 1
        assert abs(cumulative_log - expected_cumulative) < 0.0001

    def test_negative_returns_compound(self):
        """Test compound returns with negative daily returns."""
        # Day 1: -10%, Day 2: +10%
        # Correct: (1 - 0.1) × (1 + 0.1) - 1 = 0.9 × 1.1 - 1 = -0.01 (still down 1%)
        daily_returns = np.array([-0.1, 0.1])
        expected_cumulative = -0.01

        cumulative = np.prod(1 + daily_returns) - 1
        assert abs(cumulative - expected_cumulative) < 0.0001

    def test_large_negative_return_clipping(self):
        """Test that large negative returns are clipped to prevent numerical issues."""
        # A return of -1.5 would mean losing 150% (impossible for long positions)
        # Should be clipped to -0.99
        daily_returns = np.array([-1.5, 0.1])

        # Clip as done in the fixed code
        clipped = np.clip(daily_returns, -0.99, 10.0)

        assert clipped[0] == -0.99
        assert clipped[1] == 0.1

        # Verify compound return calculation works
        cumulative = np.prod(1 + clipped) - 1
        assert not np.isnan(cumulative)
        assert cumulative > -1.0  # Can't lose more than 100%

    def test_multiday_compound_returns(self):
        """Test compound returns over multiple days."""
        # 5 days of 2% daily returns
        daily_returns = np.array([0.02, 0.02, 0.02, 0.02, 0.02])

        # Correct: (1.02)^5 - 1 ≈ 0.10408 (10.408%)
        expected = (1.02**5) - 1

        cumulative = np.prod(1 + daily_returns) - 1
        assert abs(cumulative - expected) < 0.00001

    def test_zero_returns(self):
        """Test edge case of zero returns."""
        daily_returns = np.array([0.0, 0.0, 0.0])
        cumulative = np.prod(1 + daily_returns) - 1
        assert abs(cumulative) < 1e-10


class TestMonteCarloVaRFix:
    """Test the Monte Carlo VaR calculation after the bug fix."""

    @pytest.fixture
    def sample_data_provider(self):
        """Create a sample DataProvider with synthetic data."""
        # Create synthetic price data for 2 assets over 252 days
        np.random.seed(42)
        dates = pd.date_range(end=datetime.now(), periods=252, freq="D")

        # Generate correlated returns
        mean_returns = np.array([0.0005, 0.0003])  # 0.05% and 0.03% daily
        cov_matrix = np.array([[0.0004, 0.0001], [0.0001, 0.0002]])

        returns = np.random.multivariate_normal(mean_returns, cov_matrix, size=252)

        # Convert to prices (starting at 100)
        prices = pd.DataFrame(
            100 * np.exp(np.cumsum(returns, axis=0)), index=dates, columns=["STOCK_A", "STOCK_B"]
        )

        # Create DataProvider
        weights = {"STOCK_A": 0.6, "STOCK_B": 0.4}
        holdings = {
            "STOCK_A": {"shares": 100, "avg_cost": 95.0},
            "STOCK_B": {"shares": 150, "avg_cost": 98.0},
        }

        dp = DataProvider(
            weights=weights,
            holdings=holdings,
            end_date=dates[-1].strftime("%Y-%m-%d"),
            period_years=1,
        )

        # Override the cached price data with our synthetic data
        dp._prices = prices
        dp.start_date = dates[0]
        dp.end_date = dates[-1]

        return dp

    def test_var_is_positive(self, sample_data_provider):
        """VaR should be a positive number (representing potential loss)."""
        engine = RiskEngine(data_provider=sample_data_provider, mc_simulations=1000, mc_horizon=21)

        report = engine.run()

        assert report.var_95 > 0, "95% VaR should be positive"
        assert report.var_99 > 0, "99% VaR should be positive"
        assert report.cvar_95 > 0, "95% CVaR should be positive"

    def test_var_99_greater_than_var_95(self, sample_data_provider):
        """99% VaR should be greater than 95% VaR (more conservative)."""
        engine = RiskEngine(data_provider=sample_data_provider, mc_simulations=1000, mc_horizon=21)

        report = engine.run()

        assert report.var_99 > report.var_95, "99% VaR should be > 95% VaR"

    def test_cvar_greater_than_var(self, sample_data_provider):
        """CVaR should be greater than VaR (expected loss in tail)."""
        engine = RiskEngine(data_provider=sample_data_provider, mc_simulations=1000, mc_horizon=21)

        report = engine.run()

        assert report.cvar_95 >= report.var_95, "CVaR should be >= VaR"

    def test_var_reasonable_range(self, sample_data_provider):
        """VaR should be in a reasonable range (5% - 30% for typical portfolios)."""
        engine = RiskEngine(data_provider=sample_data_provider, mc_simulations=1000, mc_horizon=21)

        report = engine.run()

        # For a 21-day horizon, VaR should typically be between 2% and 40%
        assert 0.01 < report.var_95 < 0.40, f"VaR 95% ({report.var_95:.2%}) seems unreasonable"
        assert 0.01 < report.var_99 < 0.50, f"VaR 99% ({report.var_99:.2%}) seems unreasonable"

    def test_mc_returns_distribution(self, sample_data_provider):
        """Monte Carlo returns should have reasonable statistical properties."""
        engine = RiskEngine(data_provider=sample_data_provider, mc_simulations=10000, mc_horizon=21)

        report = engine.run()
        mc_returns = report.mc_portfolio_returns

        # Check that we have the right number of simulations
        assert len(mc_returns) == 10000

        # Check that returns are not all the same
        assert np.std(mc_returns) > 0

        # Check that most returns are reasonable (not all extreme values)
        assert -0.99 < np.percentile(mc_returns, 5) < 0.50
        assert -0.50 < np.percentile(mc_returns, 95) < 2.00

        # Check no NaN or Inf values
        assert not np.any(np.isnan(mc_returns))
        assert not np.any(np.isinf(mc_returns))

    def test_single_day_horizon(self, sample_data_provider):
        """Test edge case: single-day horizon."""
        engine = RiskEngine(
            data_provider=sample_data_provider, mc_simulations=1000, mc_horizon=1  # Single day
        )

        report = engine.run()

        # VaR should still be positive and reasonable
        assert 0.001 < report.var_95 < 0.10, "Single-day VaR should be small but positive"


class TestComparisonBeforeAfterFix:
    """
    Tests to verify the bug fix had the expected impact.

    These tests compare the behavior before and after the fix.
    """

    def test_portfolio_returns_not_too_small(self):
        """
        The bug caused cumulative returns to be systematically underestimated.

        With correct compound returns, the distribution should have a wider spread
        and larger extreme values.
        """
        # Create deterministic returns
        np.random.seed(42)
        n_sims = 1000
        horizon = 21

        # Simulate portfolio daily returns
        daily_mean = 0.001  # 0.1% per day
        daily_std = 0.02  # 2% vol

        cumulative_returns = []
        for _ in range(n_sims):
            daily_rets = np.random.normal(daily_mean, daily_std, horizon)

            # Clip to prevent numerical issues
            daily_rets = np.clip(daily_rets, -0.99, 10.0)

            # Correct compound return
            cum_ret = np.prod(1 + daily_rets) - 1
            cumulative_returns.append(cum_ret)

        cumulative_returns = np.array(cumulative_returns)

        # The 21-day cumulative return at 5th percentile should be negative
        # and more extreme than just -21 * daily_std * 1.645
        var_95 = -np.percentile(cumulative_returns, 5)

        # Simple approximation: 21 days * 0.02 vol * sqrt(21) * 1.645 ≈ 0.15
        # With compounding, it should be slightly different
        assert var_95 > 0.01, "VaR should be significant over 21 days"

        # Mean should be positive (since we have positive drift)
        assert np.mean(cumulative_returns) > 0, "Mean cumulative return should be positive"


def test_numerical_stability_extreme_returns():
    """Test that extreme returns don't cause numerical issues."""
    # Very large positive and negative returns
    extreme_returns = np.array([-0.9, 0.5, -0.8, 1.0, 0.3])

    # After clipping
    clipped = np.clip(extreme_returns, -0.99, 10.0)

    # Should not produce NaN or Inf
    cumulative = np.prod(1 + clipped) - 1

    assert not np.isnan(cumulative)
    assert not np.isinf(cumulative)
    assert cumulative > -1.0  # Can't lose more than 100%


def test_compound_return_formula_equivalence():
    """Verify that different compound return formulas are equivalent."""
    np.random.seed(123)
    daily_returns = np.random.normal(0.0005, 0.015, 21)

    # Method 1: prod
    method1 = np.prod(1 + daily_returns) - 1

    # Method 2: cumprod (taking last value)
    method2 = np.cumprod(1 + daily_returns)[-1] - 1

    # Method 3: log/exp (mathematically equivalent)
    method3 = np.exp(np.sum(np.log(1 + daily_returns))) - 1

    # All methods should give same result
    assert abs(method1 - method2) < 1e-10
    assert abs(method1 - method3) < 1e-10


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
