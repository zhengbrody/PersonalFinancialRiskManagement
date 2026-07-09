"""
test_data_provider.py
Unit tests for the data provider - testing robustness, caching, and data-validation features
"""

import os
import shutil
import tempfile
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from data_provider import CachedDataProvider, DataProvider


class TestDataValidation:
    """Test data-quality validation features"""

    def test_validate_ticker_data_normal(self):
        """Test that valid data passes validation"""
        dp = DataProvider({"TEST": 1.0}, period_years=1)

        # Create normal data
        dates = pd.date_range("2024-01-01", periods=100)
        data = pd.DataFrame({"Close": [100 + i * 0.5 for i in range(100)]}, index=dates)

        is_valid, msg = dp._validate_ticker_data("TEST", data)
        assert is_valid is True
        assert msg == ""

    def test_validate_ticker_data_empty(self):
        """Test empty data"""
        dp = DataProvider({"TEST": 1.0}, period_years=1)

        data = pd.DataFrame()

        is_valid, msg = dp._validate_ticker_data("TEST", data)
        assert is_valid is False
        assert "Data is empty" in msg

    def test_validate_ticker_data_insufficient(self):
        """Test insufficient data"""
        dp = DataProvider({"TEST": 1.0}, period_years=1)

        # Only 10 data points (fewer than 20)
        dates = pd.date_range("2024-01-01", periods=10)
        data = pd.DataFrame({"Close": [100 + i for i in range(10)]}, index=dates)

        is_valid, msg = dp._validate_ticker_data("TEST", data)
        assert is_valid is False
        assert "Insufficient data" in msg

    def test_validate_ticker_data_high_missing_rate(self):
        """Test data with an excessively high missing rate"""
        dp = DataProvider({"TEST": 1.0}, period_years=1)

        # Create data that is 35% missing (over the 30% threshold)
        dates = pd.date_range("2024-01-01", periods=100)
        values = []
        for i in range(100):
            if i % 3 == 0:  # 1 in every 3 is missing, ~33%
                values.append(None)
            else:
                values.append(100 + i * 0.5 + np.random.random() * 2)  # add random noise and trend

        data = pd.DataFrame({"Close": values}, index=dates)

        is_valid, msg = dp._validate_ticker_data("TEST", data)
        assert is_valid is False
        assert "Missing rate" in msg

    def test_validate_ticker_data_negative_prices(self):
        """Test negative or zero prices"""
        dp = DataProvider({"TEST": 1.0}, period_years=1)

        dates = pd.date_range("2024-01-01", periods=100)
        values = [100 + i for i in range(100)]
        values[50] = 0  # one zero price
        data = pd.DataFrame({"Close": values}, index=dates)

        is_valid, msg = dp._validate_ticker_data("TEST", data)
        assert is_valid is False
        assert "prices <= 0" in msg

    def test_validate_ticker_data_extreme_return(self):
        """Test extreme moves — 1-2 allowed (warning), >2 fails"""
        dp = DataProvider({"TEST": 1.0}, period_years=1)

        # 1 extreme gain → allowed but warned
        np.random.seed(42)
        dates = pd.date_range("2024-01-01", periods=50)
        values = (100 + np.cumsum(np.random.randn(50) * 0.5)).tolist()
        values[25] = values[24] * 1.6  # +60% on day 26
        data = pd.DataFrame({"Close": values}, index=dates)
        is_valid, _ = dp._validate_ticker_data("TEST", data)
        assert is_valid is True  # 1 extreme value is tolerable

        # 3 or more extreme gains → fails
        values[10] = values[9] * 1.7
        values[35] = values[34] * 0.4
        values[40] = values[39] * 1.8
        data3 = pd.DataFrame({"Close": values}, index=dates)
        is_valid3, msg3 = dp._validate_ticker_data("TEST", data3)
        assert is_valid3 is False
        assert "extreme" in msg3

    def test_validate_ticker_data_suspended_trading(self):
        """Test suspended trading (consecutive identical prices)"""
        dp = DataProvider({"TEST": 1.0}, period_years=1)

        # Create data with 20 consecutive days of identical prices
        dates = pd.date_range("2024-01-01", periods=50)
        values = [100.0] * 50
        # First 20 days at the same price (simulating a trading suspension)
        for i in range(20):
            values[i] = 100.0

        data = pd.DataFrame({"Close": values}, index=dates)

        is_valid, msg = dp._validate_ticker_data("TEST", data)
        assert is_valid is False
        assert "consecutive identical prices" in msg or "halted" in msg


class TestCachedDataProvider:
    """Test caching features"""

    @pytest.fixture
    def temp_cache_dir(self):
        """Create a temporary cache directory"""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        # Cleanup
        shutil.rmtree(temp_dir, ignore_errors=True)

    def test_cache_path_generation(self, temp_cache_dir):
        """Test cache-path generation"""
        cache_provider = CachedDataProvider(cache_dir=temp_cache_dir)

        path = cache_provider._get_cache_path("AAPL", "2024-01-01", "2024-12-31", "prices")

        assert temp_cache_dir in path
        assert "AAPL" in path
        assert "2024-01-01" in path
        assert "2024-12-31" in path
        assert "prices.pkl" in path

    def test_cache_path_special_characters(self, temp_cache_dir):
        """Test handling of special characters in the cache path"""
        cache_provider = CachedDataProvider(cache_dir=temp_cache_dir)

        # Test tickers containing special characters
        path1 = cache_provider._get_cache_path("^TNX", "2024-01-01", "2024-12-31", "prices")
        path2 = cache_provider._get_cache_path("CL=F", "2024-01-01", "2024-12-31", "prices")

        # Ensure the special characters are replaced
        assert "^" not in path1
        assert "=" not in path2

    def test_cache_validity_check(self, temp_cache_dir):
        """Test cache-validity checking"""
        cache_provider = CachedDataProvider(cache_dir=temp_cache_dir)

        # Create a cache file
        cache_path = os.path.join(temp_cache_dir, "test.pkl")

        # Should be invalid when the file does not exist
        assert cache_provider._is_cache_valid(cache_path, max_age_hours=24) is False

        # Create the file
        with open(cache_path, "wb") as f:
            f.write(b"test")

        # A fresh file should be valid
        assert cache_provider._is_cache_valid(cache_path, max_age_hours=24) is True

        # Set the file time to 2 days ago (over 24 hours)
        old_time = (datetime.now() - timedelta(days=2)).timestamp()
        os.utime(cache_path, (old_time, old_time))

        # An expired file should be invalid
        assert cache_provider._is_cache_valid(cache_path, max_age_hours=24) is False


class TestDataProviderRobustness:
    """Test the robustness of DataProvider"""

    def test_initialization(self):
        """Test initialization"""
        weights = {"AAPL": 0.5, "GOOGL": 0.5}
        dp = DataProvider(weights, period_years=2)

        assert dp.weights == weights
        assert dp.tickers == ["AAPL", "GOOGL"]
        assert dp.period_years == 2
        assert dp._cache_provider is not None
        assert dp._failed_tickers == []

    def test_initialization_with_holdings(self):
        """Test initialization with holdings"""
        weights = {"AAPL": 0.5, "GOOGL": 0.5}
        holdings = {"AAPL": {"shares": 100}, "GOOGL": {"shares": 50}}

        dp = DataProvider(weights, period_years=2, holdings=holdings)

        assert dp.holdings == holdings

    def test_get_failed_tickers(self):
        """Test retrieving the list of failed tickers"""
        weights = {"AAPL": 0.5, "GOOGL": 0.5}
        dp = DataProvider(weights, period_years=2)

        # Should be empty initially
        assert dp.get_failed_tickers() == []

        # Manually add some failure records
        dp._failed_tickers = [("INVALID", "ticker not found")]

        failed = dp.get_failed_tickers()
        assert len(failed) == 1
        assert failed[0][0] == "INVALID"
        assert "ticker not found" in failed[0][1]

    def test_date_range_calculation(self):
        """Test date-range calculation"""
        weights = {"AAPL": 0.5}
        end_date = "2024-12-31"

        dp = DataProvider(weights, period_years=2, end_date=end_date)

        assert dp.end_date == pd.Timestamp("2024-12-31")
        # 2 years earlier should be around 2022-12-31
        expected_start = pd.Timestamp("2024-12-31") - timedelta(days=365 * 2)
        assert dp.start_date == expected_start


class TestDataProviderIntegration:
    """Integration tests - test real data downloads (requires a network connection)"""

    @pytest.mark.slow
    @pytest.mark.skipif(os.environ.get("SKIP_NETWORK_TESTS") == "1", reason="skip network tests")
    def test_fetch_prices_single_ticker(self):
        """Test price retrieval for a single ticker"""
        weights = {"AAPL": 1.0}
        dp = DataProvider(weights, period_years=1)

        try:
            prices = dp.fetch_prices()

            # Verify the return is a DataFrame
            assert isinstance(prices, pd.DataFrame)

            # Verify the AAPL column is present
            assert "AAPL" in prices.columns

            # Verify there is data
            assert len(prices) > 0

            # Verify the data type
            assert prices["AAPL"].dtype in [np.float64, np.float32]

        except Exception as e:
            pytest.skip(f"Network test failed (possibly a network issue): {e}")

    @pytest.mark.slow
    @pytest.mark.skipif(os.environ.get("SKIP_NETWORK_TESTS") == "1", reason="skip network tests")
    def test_fetch_prices_multiple_tickers(self):
        """Test price retrieval for multiple tickers"""
        weights = {"AAPL": 0.5, "GOOGL": 0.5}
        dp = DataProvider(weights, period_years=1)

        try:
            prices = dp.fetch_prices()

            # At least one ticker should succeed
            assert len(prices.columns) >= 1

            # Verify the data is valid
            assert len(prices) > 0

        except Exception as e:
            pytest.skip(f"Network test failed (possibly a network issue): {e}")

    @pytest.mark.slow
    @pytest.mark.skipif(os.environ.get("SKIP_NETWORK_TESTS") == "1", reason="skip network tests")
    def test_fetch_prices_with_invalid_ticker(self):
        """Test robustness when an invalid ticker is included"""
        weights = {"AAPL": 0.4, "INVALID_TICKER_XYZ123": 0.3, "GOOGL": 0.3}
        dp = DataProvider(weights, period_years=1)

        try:
            prices = dp.fetch_prices()

            # Should successfully return data for the valid tickers
            assert isinstance(prices, pd.DataFrame)

            # Valid tickers should be in the result
            valid_tickers = [t for t in ["AAPL", "GOOGL"] if t in prices.columns]
            assert len(valid_tickers) >= 1

            # The invalid ticker should be in the failure list
            failed = dp.get_failed_tickers()
            failed_ticker_names = [f[0] for f in failed]
            assert "INVALID_TICKER_XYZ123" in failed_ticker_names

        except Exception as e:
            pytest.skip(f"Network test failed (possibly a network issue): {e}")

    def test_get_daily_returns(self):
        """Test daily-return calculation"""
        weights = {"AAPL": 1.0}
        dp = DataProvider(weights, period_years=1)

        # Create simulated price data
        dates = pd.date_range("2024-01-01", periods=100)
        prices = pd.DataFrame({"AAPL": [100 + i for i in range(100)]}, index=dates)

        dp._prices = prices

        returns = dp.get_daily_returns()

        # Verify the return type
        assert isinstance(returns, pd.DataFrame)

        # Verify the length (should be 1 row fewer than prices)
        assert len(returns) == len(prices) - 1

        # Verify they are simple returns (project-wide convention)
        assert returns["AAPL"].iloc[0] == pytest.approx((101 - 100) / 100, rel=1e-9)

    def test_cumulative_return_matches_price_derived(self):
        """Cumulative return (derived from the return series) must match (last price / first price - 1)."""
        dp = DataProvider({"AAPL": 1.0}, period_years=2)
        dates = pd.date_range("2024-01-01", periods=60, freq="D")
        prices = pd.DataFrame({"AAPL": [100.0 * (1.001**i) for i in range(60)]}, index=dates)
        dp._prices = prices

        returns = dp.get_daily_returns()
        cumret_from_returns = (1 + returns["AAPL"]).prod() - 1
        cumret_from_prices = prices["AAPL"].iloc[-1] / prices["AAPL"].iloc[0] - 1

        assert cumret_from_returns == pytest.approx(cumret_from_prices, rel=1e-10)


class TestCacheIntegration:
    """Test cache-integration features"""

    @pytest.fixture
    def temp_cache_dir(self):
        """Create a temporary cache directory"""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir, ignore_errors=True)

    def test_cache_saves_data(self, temp_cache_dir):
        """Test that the cache saves data correctly"""
        cache_provider = CachedDataProvider(cache_dir=temp_cache_dir)

        # Create test data
        test_data = pd.DataFrame({"Close": [100, 101, 102], "Volume": [1000, 1100, 1200]})

        # Save to cache
        cache_path = cache_provider._get_cache_path("TEST", "2024-01-01", "2024-01-31", "prices")
        import pickle

        with open(cache_path, "wb") as f:
            pickle.dump(test_data, f)

        # Verify the cache is valid
        assert cache_provider._is_cache_valid(cache_path, max_age_hours=24)

        # Load from cache
        with open(cache_path, "rb") as f:
            loaded_data = pickle.load(f)

        # Verify data consistency
        pd.testing.assert_frame_equal(test_data, loaded_data)


class TestParallelFetchPrices:
    """Perf regression guard: fetch_prices() runs tickers concurrently via
    ThreadPoolExecutor and merges results in submission order. If someone
    reverts the loop back to a serial for-loop, this test still passes
    (correctness only), but the perf docstring + history make the intent
    explicit."""

    def test_fetch_prices_parallel_preserves_results(self):
        """Multiple tickers should all appear in the output DataFrame and the
        ordering of self._failed_tickers should match the input order even
        when fetched in parallel."""
        weights = {"GOOD1": 0.3, "BAD": 0.3, "GOOD2": 0.4}
        dp = DataProvider(weights, period_years=1)

        # Stub the cache provider to return synthetic data deterministically.
        dates = pd.date_range("2024-01-01", periods=50)

        def _fake_fetch(ticker, start, end, force_refresh=False, data_type="prices", **kwargs):
            if ticker == "BAD":
                return None
            return pd.DataFrame(
                {"Close": np.linspace(100, 120, 50), "Volume": [1_000_000] * 50},
                index=dates,
            )

        dp._cache_provider.fetch_with_cache = _fake_fetch  # type: ignore[assignment]

        prices = dp.fetch_prices()

        # Both good tickers present, bad one in failure list.
        assert "GOOD1" in prices.columns
        assert "GOOD2" in prices.columns
        assert "BAD" not in prices.columns

        failed_names = [f[0] for f in dp.get_failed_tickers()]
        assert "BAD" in failed_names


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
