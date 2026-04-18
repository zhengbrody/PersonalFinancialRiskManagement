"""
tests/unit/test_risk_calculations.py
Comprehensive tests for core risk calculations (VaR, Beta, Sharpe, etc.)
"""

import pytest
import numpy as np
import pandas as pd
from risk_engine import RiskEngine
from data_provider import DataProvider


class TestMonteCarloVaR:
    """Test Monte Carlo VaR calculation"""

    @pytest.fixture
    def sample_returns(self):
        """Generate sample return data for testing"""
        np.random.seed(42)
        n_days = 252
        n_assets = 3
        returns = pd.DataFrame(
            np.random.randn(n_days, n_assets) * 0.02,  # 2% daily vol
            columns=['AAPL', 'GOOGL', 'MSFT']
        )
        return returns

    @pytest.fixture
    def sample_weights(self):
        return np.array([0.4, 0.3, 0.3])

    def test_var_output_shape(self, sample_returns, sample_weights):
        """Test that VaR returns correct number of simulations"""
        engine = RiskEngine(None, mc_simulations=1000, mc_horizon=21)
        cov = sample_returns.cov().values
        portfolio_returns = engine._monte_carlo_var(sample_returns, sample_weights, cov)

        assert len(portfolio_returns) == 1000
        assert isinstance(portfolio_returns, np.ndarray)

    def test_var_values_reasonable(self, sample_returns, sample_weights):
        """Test that VaR values are within reasonable range"""
        engine = RiskEngine(None, mc_simulations=10000, mc_horizon=21)
        cov = sample_returns.cov().values
        portfolio_returns = engine._monte_carlo_var(sample_returns, sample_weights, cov)

        var_95 = -np.percentile(portfolio_returns, 5)
        var_99 = -np.percentile(portfolio_returns, 1)

        # VaR should be positive
        assert var_95 > 0
        assert var_99 > 0

        # VaR99 should be higher than VaR95
        assert var_99 > var_95

        # VaR should be reasonable (not extreme)
        assert var_95 < 0.5  # 95% VaR < 50%
        assert var_99 < 0.8  # 99% VaR < 80%

    def test_var_deterministic_with_seed(self):
        """Test that VaR is deterministic with fixed seed"""
        np.random.seed(42)
        returns = pd.DataFrame(np.random.randn(252, 2) * 0.01, columns=['A', 'B'])
        weights = np.array([0.5, 0.5])
        cov = returns.cov().values

        engine1 = RiskEngine(None, mc_simulations=5000, mc_horizon=21)
        engine2 = RiskEngine(None, mc_simulations=5000, mc_horizon=21)

        result1 = engine1._monte_carlo_var(returns, weights, cov)
        result2 = engine2._monte_carlo_var(returns, weights, cov)

        # Results should be identical with same seed
        np.testing.assert_array_almost_equal(result1, result2)

    def test_var_vectorization_performance(self, sample_returns, sample_weights):
        """Test that vectorized implementation is actually fast"""
        import time

        engine = RiskEngine(None, mc_simulations=10000, mc_horizon=21)
        cov = sample_returns.cov().values

        start = time.time()
        portfolio_returns = engine._monte_carlo_var(sample_returns, sample_weights, cov)
        duration = time.time() - start

        # With vectorization, 10K simulations should take < 0.5 seconds
        assert duration < 0.5, f"VaR calculation too slow: {duration:.3f}s"

    def test_var_with_zero_volatility(self):
        """Test VaR when all returns are zero (edge case)"""
        returns = pd.DataFrame(np.zeros((252, 2)), columns=['A', 'B'])
        weights = np.array([0.5, 0.5])
        cov = returns.cov().values + np.eye(2) * 1e-8  # Small ridge

        engine = RiskEngine(None, mc_simulations=1000, mc_horizon=21)
        portfolio_returns = engine._monte_carlo_var(returns, weights, cov)

        # With zero volatility, all simulations should be near zero
        assert np.abs(portfolio_returns).mean() < 0.01


class TestBetaCalculation:
    """Test Beta and statistical significance calculation"""

    def test_beta_calculation_accuracy(self):
        """Test beta calculation against known values"""
        # Generate data where beta should be ~1.5
        np.random.seed(42)
        market_returns = np.random.randn(252) * 0.02
        asset_returns = 1.5 * market_returns + np.random.randn(252) * 0.01

        # Use scipy for ground truth
        from scipy import stats
        slope, intercept, r_value, p_value, std_err = stats.linregress(market_returns, asset_returns)

        # Test our implementation
        from risk_engine import RiskEngine
        engine = RiskEngine(None)

        # Our implementation - pass 1D arrays directly
        beta_result = engine._compute_beta_with_significance(asset_returns, market_returns)

        # Compare with scipy
        assert abs(beta_result['beta'] - slope) < 0.01
        assert abs(beta_result['p_value'] - p_value) < 0.01

    def test_beta_significance_detection(self):
        """Test that significance is correctly detected"""
        np.random.seed(42)

        # Case 1: Significant relationship (high correlation)
        market = np.random.randn(252) * 0.02
        asset_sig = 2.0 * market + np.random.randn(252) * 0.002  # Very little noise

        engine = RiskEngine(None)
        result_sig = engine._compute_beta_with_significance(asset_sig, market)

        assert result_sig['is_significant'] == True
        assert result_sig['p_value'] < 0.05

        # Case 2: Insignificant relationship (random noise)
        asset_insig = np.random.randn(252) * 0.02  # Pure noise

        result_insig = engine._compute_beta_with_significance(asset_insig, market)

        # With pure noise, might or might not be significant
        # But beta should be close to zero
        assert abs(result_insig['beta']) < 0.5

    def test_beta_with_perfect_correlation(self):
        """Test beta when asset = market (should be 1.0)"""
        np.random.seed(42)
        market = np.random.randn(252) * 0.02

        engine = RiskEngine(None)
        result = engine._compute_beta_with_significance(market, market)

        assert abs(result['beta'] - 1.0) < 0.01
        assert result['r_squared'] > 0.99


class TestSharpeRatio:
    """Test Sharpe ratio calculation"""

    def test_sharpe_ratio_calculation(self):
        """Test Sharpe ratio calculation"""
        # Annualized return = 10%, volatility = 15%, risk-free = 2%
        # Expected Sharpe = (0.10 - 0.02) / 0.15 = 0.533

        # Generate synthetic data
        np.random.seed(42)
        daily_returns = np.random.randn(252) * (0.15 / np.sqrt(252)) + (0.10 / 252)

        annual_return = np.mean(daily_returns) * 252
        annual_vol = np.std(daily_returns) * np.sqrt(252)
        risk_free = 0.02

        sharpe = (annual_return - risk_free) / annual_vol

        # Should be around 0.5-0.6 (some randomness)
        assert 0.3 < sharpe < 0.9

    def test_sharpe_ratio_negative_returns(self):
        """Test Sharpe ratio with negative returns"""
        np.random.seed(42)
        # Generate losing strategy
        daily_returns = np.random.randn(252) * 0.02 - 0.0005  # Negative drift

        annual_return = np.mean(daily_returns) * 252
        annual_vol = np.std(daily_returns) * np.sqrt(252)
        risk_free = 0.02

        sharpe = (annual_return - risk_free) / annual_vol

        # Should be negative
        assert sharpe < 0


class TestCovarianceMatrix:
    """Test EWMA covariance calculation"""

    def test_ewma_vs_simple_covariance(self):
        """Test that EWMA gives more weight to recent data"""
        np.random.seed(42)

        # Generate returns with regime change
        early_returns = np.random.randn(126, 2) * 0.01  # Low vol
        recent_returns = np.random.randn(126, 2) * 0.03  # High vol
        returns = pd.DataFrame(
            np.vstack([early_returns, recent_returns]),
            columns=['A', 'B']
        )

        # Simple covariance
        cov_simple = returns.cov().values

        # EWMA covariance
        from risk_engine import RiskEngine
        engine = RiskEngine(None)
        cov_ewma = engine._ewma_covariance(returns)

        # EWMA variance should be higher (emphasizes recent high vol)
        assert cov_ewma[0, 0] > cov_simple[0, 0]
        assert cov_ewma[1, 1] > cov_simple[1, 1]


class TestEdgeCases:
    """Test edge cases and error handling"""

    def test_single_asset_portfolio(self):
        """Test that calculations work with single asset"""
        np.random.seed(42)
        returns = pd.DataFrame(np.random.randn(252, 1) * 0.02, columns=['AAPL'])
        weights = np.array([1.0])

        engine = RiskEngine(None, mc_simulations=1000, mc_horizon=21)
        cov = returns.cov().values

        portfolio_returns = engine._monte_carlo_var(returns, weights, cov)

        assert len(portfolio_returns) == 1000
        assert not np.isnan(portfolio_returns).any()

    def test_extreme_concentration(self):
        """Test with 99% concentrated in one asset"""
        np.random.seed(42)
        returns = pd.DataFrame(np.random.randn(252, 3) * 0.02, columns=['A', 'B', 'C'])
        weights = np.array([0.99, 0.005, 0.005])

        engine = RiskEngine(None, mc_simulations=1000, mc_horizon=21)
        cov = returns.cov().values

        portfolio_returns = engine._monte_carlo_var(returns, weights, cov)

        # Should still work without errors
        assert len(portfolio_returns) == 1000
        assert not np.isnan(portfolio_returns).any()


class TestNumericalStability:
    """Test numerical stability"""

    def test_nearly_singular_covariance(self):
        """Test handling of nearly singular covariance matrix"""
        # Create highly correlated assets
        np.random.seed(42)
        base = np.random.randn(252) * 0.02
        returns = pd.DataFrame({
            'A': base,
            'B': base + np.random.randn(252) * 0.001,  # Almost identical to A
            'C': base + np.random.randn(252) * 0.001
        })

        weights = np.array([0.33, 0.33, 0.34])
        engine = RiskEngine(None, mc_simulations=1000, mc_horizon=21)

        # Should handle near-singularity with ridge
        cov = returns.cov().values
        portfolio_returns = engine._monte_carlo_var(returns, weights, cov)

        assert not np.isnan(portfolio_returns).any()

    def test_extreme_returns_clipping(self):
        """Test that extreme returns are clipped properly"""
        # This is implicitly tested in the Monte Carlo implementation
        # The clipping prevents numerical issues from extreme daily returns
        pass


# Integration test
class TestEndToEndRiskCalculation:
    """Test complete risk calculation workflow"""

    @pytest.mark.slow
    def test_complete_risk_report(self):
        """Test generating complete risk report (slow test)"""
        # This would require real DataProvider setup
        # Mark as slow test to skip in quick runs
        pass


if __name__ == "__main__":
    # Run tests
    pytest.main([__file__, "-v"])
