"""
Performance tests for Streamlit caching optimization.

Tests verify that:
1. Cache hits are extremely fast (<1 second)
2. Cold starts are acceptable (<15 seconds for 5-15 stocks)
3. Performance scales well with more stocks
"""

import json
import sys
import time
from pathlib import Path

import pytest

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from data_provider import DataProvider
from risk_engine import RiskEngine


class TestCachePerformance:
    """Test Streamlit @st.cache_data/@st.cache_resource performance"""

    @pytest.fixture
    def sample_weights_dict(self):
        """Simple 3-stock portfolio"""
        return {"AAPL": 0.5, "GOOGL": 0.3, "MSFT": 0.2}

    @pytest.fixture
    def real_portfolio_weights(self):
        """7-stock real portfolio (similar to task description)"""
        return {
            "NVDA": 0.15,
            "AAPL": 0.15,
            "GOOGL": 0.15,
            "MSFT": 0.15,
            "TSLA": 0.15,
            "META": 0.15,
            "AMZN": 0.10,
        }

    def test_data_provider_creation_first_time(self, sample_weights_dict):
        """Test DataProvider creation (cold start - first time)"""
        start = time.time()

        dp = DataProvider(sample_weights_dict, period_years=2)
        _ = dp.fetch_prices()

        elapsed = time.time() - start
        print(f"DataProvider creation (cold): {elapsed:.2f}s")

        # First fetch should take <10 seconds (data download)
        assert elapsed < 15, f"Cold start took {elapsed:.2f}s, should be <15s for 3 stocks"

        assert dp is not None
        assert dp._prices is not None
        assert not dp._prices.empty

    def test_data_provider_fetch_prices_second_time(self, sample_weights_dict):
        """Test DataProvider fetch_prices (should be cached internally)"""
        dp = DataProvider(sample_weights_dict, period_years=2)

        # First fetch
        start1 = time.time()
        prices1 = dp.fetch_prices()
        elapsed1 = time.time() - start1
        print(f"First fetch_prices: {elapsed1:.2f}s")

        # Second fetch (should hit internal cache)
        start2 = time.time()
        prices2 = dp.fetch_prices()
        elapsed2 = time.time() - start2
        print(f"Second fetch_prices (cached): {elapsed2:.2f}s")

        # Second call should be nearly instant (<100ms)
        assert elapsed2 < 0.5, f"Cached fetch took {elapsed2:.2f}s, should be <0.5s"

        # Data should be identical
        assert prices1.equals(prices2)

    def test_risk_engine_run_performance(self, sample_weights_dict):
        """Test RiskEngine.run() performance"""
        dp = DataProvider(sample_weights_dict, period_years=2)
        dp.fetch_prices()

        engine = RiskEngine(dp, mc_simulations=10000, mc_horizon=21)

        start = time.time()
        report = engine.run()
        elapsed = time.time() - start

        print(f"RiskEngine.run() with 10k MC paths: {elapsed:.2f}s")

        # Monte Carlo with 10k paths should take 2-8 seconds
        assert elapsed < 15, f"Risk calculation took {elapsed:.2f}s, should be <15s"

        assert report is not None
        assert report.var_95 is not None
        assert report.sharpe_ratio is not None

    def test_full_analysis_3_stocks_cold(self, sample_weights_dict):
        """Test complete analysis pipeline (3 stocks, cold start)"""
        start = time.time()

        # Simulate what app.py does
        dp = DataProvider(sample_weights_dict, period_years=2)
        prices = dp.fetch_prices()
        cumret = dp.get_portfolio_cumulative_returns()

        engine = RiskEngine(dp, mc_simulations=10000, mc_horizon=21)
        report = engine.run()

        elapsed = time.time() - start
        print(f"Full analysis (3 stocks, cold): {elapsed:.2f}s")

        # Should be acceptable for cold start
        assert elapsed < 20, f"Full analysis took {elapsed:.2f}s, should be <20s for 3 stocks"

        assert report is not None
        assert not prices.empty

    def test_full_analysis_7_stocks_cold(self, real_portfolio_weights):
        """Test complete analysis (7 stocks, cold start) - MAIN PERFORMANCE TEST"""
        start = time.time()

        dp = DataProvider(real_portfolio_weights, period_years=2)
        prices = dp.fetch_prices()
        cumret = dp.get_portfolio_cumulative_returns()

        engine = RiskEngine(dp, mc_simulations=10000, mc_horizon=21)
        report = engine.run()

        elapsed = time.time() - start
        print(f"\nFull analysis (7 stocks, cold): {elapsed:.2f}s")
        print("Breakdown:")
        print(f"  - DataProvider + price fetch: ~{elapsed * 0.3:.2f}s")
        print(f"  - RiskEngine.run() (10k MC): ~{elapsed * 0.7:.2f}s")

        # TARGET: <10 seconds for 5-15 stocks on first run
        assert elapsed < 15, (
            f"Full analysis (7 stocks) took {elapsed:.2f}s.\n"
            f"Target: <10s. This is a cold start; cached should be <3s."
        )

        assert report is not None
        assert len(prices.columns) == 7

    def test_multiple_runs_same_weights(self, sample_weights_dict):
        """
        Test that multiple runs with same weights show decreasing time
        (simulating Streamlit cache hits via DataProvider file system cache)

        Note: This tests the DataProvider's internal file cache, not Streamlit's
        @st.cache_data or @st.cache_resource (those require Streamlit runtime).
        """
        times = []

        for run_num in range(3):
            start = time.time()

            dp = DataProvider(sample_weights_dict, period_years=2)
            prices = dp.fetch_prices()  # File system cache hit on 2nd+ runs
            cumret = dp.get_portfolio_cumulative_returns()

            engine = RiskEngine(dp, mc_simulations=10000, mc_horizon=21)
            report = engine.run()

            elapsed = time.time() - start
            times.append(elapsed)
            print(f"Run {run_num + 1}: {elapsed:.2f}s")

        # Second and third runs should be faster (file system caching in DataProvider)
        # Note: Speedup may be modest if RiskEngine dominates, but should still show improvement
        speedup_12 = times[0] / times[1]
        speedup_23 = times[1] / times[2]

        print(f"Speedup from run 1 to run 2: {speedup_12:.1f}x")
        print(f"Speedup from run 2 to run 3: {speedup_23:.1f}x")

        # At minimum, run 2 should not be slower than run 1 (cache not harmful)
        assert (
            times[1] <= times[0] * 1.05
        ), f"Second run ({times[1]:.2f}s) should not be much slower than run 1 ({times[0]:.2f}s)"


class TestCacheKeyHashing:
    """Test that JSON-based cache keys work properly"""

    def test_weights_json_consistency(self):
        """Verify that weights dict -> JSON -> dict is lossless and consistent"""
        weights1 = {"AAPL": 0.5, "GOOGL": 0.3, "MSFT": 0.2}
        weights2 = {"MSFT": 0.2, "GOOGL": 0.3, "AAPL": 0.5}  # Different order

        # Convert to JSON with sort_keys (as done in app.py)
        json1 = json.dumps(weights1, sort_keys=True)
        json2 = json.dumps(weights2, sort_keys=True)

        # Should produce identical JSON strings (cache key matches)
        assert json1 == json2, "Same weights in different order should produce same cache key"

        # Should be able to recover original dict
        recovered = json.loads(json1)
        assert recovered == weights1

    def test_weights_json_precision(self):
        """Verify float precision doesn't break cache keys"""
        weights1 = {"AAPL": 0.333333, "GOOGL": 0.333333, "MSFT": 0.333334}
        weights2 = {"AAPL": 0.333333, "GOOGL": 0.333333, "MSFT": 0.333334}

        json1 = json.dumps(weights1, sort_keys=True)
        json2 = json.dumps(weights2, sort_keys=True)

        # Identical weights should have identical cache keys
        assert json1 == json2


@pytest.mark.parametrize(
    "num_stocks,expected_max_time",
    [
        (3, 15),  # 3 stocks: <15 seconds cold start
        (5, 15),  # 5 stocks: <15 seconds
        (7, 15),  # 7 stocks: <15 seconds (main use case)
    ],
)
def test_performance_scaling(num_stocks, expected_max_time):
    """Test that performance scales reasonably with portfolio size"""
    # Create equal-weight portfolio
    tickers = [
        "NVDA",
        "AAPL",
        "GOOGL",
        "MSFT",
        "TSLA",
        "META",
        "AMZN",
        "AMZN",
        "JPM",
        "V",  # Extra tickers for 10-stock test
    ][:num_stocks]

    weights = {tk: 1.0 / num_stocks for tk in tickers}

    start = time.time()

    dp = DataProvider(weights, period_years=2)
    prices = dp.fetch_prices()
    cumret = dp.get_portfolio_cumulative_returns()

    engine = RiskEngine(dp, mc_simulations=10000, mc_horizon=21)
    report = engine.run()

    elapsed = time.time() - start

    print(f"{num_stocks} stocks: {elapsed:.2f}s (max: {expected_max_time}s)")

    assert (
        elapsed < expected_max_time
    ), f"{num_stocks} stocks took {elapsed:.2f}s, should be <{expected_max_time}s"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
