"""
tests/unit/test_volatility_scanner.py
Comprehensive tests for volatility_scanner.py
"""

import hashlib
import os
import time
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from volatility_scanner import (
    CACHE_DIR,
    CACHE_MAX_AGE_SECONDS,
    SECTOR_ETFS,
    SP500_LIQUID_100,
    _cache_key,
    _read_cache,
    _safe_float,
    _write_cache,
    get_sector_performance,
    scan_portfolio_movers,
    scan_sp500_movers,
)

# ══════════════════════════════════════════════════════════════
#  Helpers / Fixtures
# ══════════════════════════════════════════════════════════════


def _make_ticker_data(
    ticker, change_pct, close=100.0, volume=1_000_000, avg_volume_ratio=1.0, name=None
):
    """Build a dict matching _fetch_ticker_day_data return shape."""
    return {
        "ticker": ticker,
        "name": name or f"{ticker} Inc",
        "change_pct": change_pct,
        "close": close,
        "volume": volume,
        "avg_volume_ratio": avg_volume_ratio,
    }


@pytest.fixture
def sample_movers_data():
    """A list of mocked mover dicts with varied change_pct and volume ratios."""
    return [
        _make_ticker_data("AAPL", 5.0, close=180.0, avg_volume_ratio=1.2),
        _make_ticker_data("MSFT", -3.5, close=400.0, avg_volume_ratio=0.9),
        _make_ticker_data("TSLA", 12.0, close=250.0, avg_volume_ratio=3.5),
        _make_ticker_data("NVDA", 8.0, close=900.0, avg_volume_ratio=2.1),
        _make_ticker_data("META", -7.0, close=500.0, avg_volume_ratio=4.0),
        _make_ticker_data("AMZN", 1.0, close=185.0, avg_volume_ratio=0.5),
        _make_ticker_data("GOOGL", 0.5, close=170.0, avg_volume_ratio=1.0),
        _make_ticker_data("JPM", -1.0, close=195.0, avg_volume_ratio=1.8),
    ]


# ══════════════════════════════════════════════════════════════
#  1. _safe_float
# ══════════════════════════════════════════════════════════════


class TestSafeFloat:
    """Tests for _safe_float conversion helper."""

    def test_valid_int(self):
        assert _safe_float(42) == 42.0

    def test_valid_float(self):
        assert _safe_float(3.14) == 3.14

    def test_valid_negative(self):
        assert _safe_float(-99.5) == -99.5

    def test_zero(self):
        assert _safe_float(0) == 0.0

    def test_string_numeric(self):
        assert _safe_float("2.718") == 2.718

    def test_nan_returns_none(self):
        assert _safe_float(float("nan")) is None

    def test_numpy_nan_returns_none(self):
        assert _safe_float(np.nan) is None

    def test_inf_returns_none(self):
        assert _safe_float(float("inf")) is None

    def test_negative_inf_returns_none(self):
        assert _safe_float(float("-inf")) is None

    def test_numpy_inf_returns_none(self):
        assert _safe_float(np.inf) is None

    def test_none_returns_none(self):
        assert _safe_float(None) is None

    def test_non_numeric_string_returns_none(self):
        assert _safe_float("hello") is None

    def test_empty_string_returns_none(self):
        assert _safe_float("") is None

    def test_bool_true(self):
        # float(True) == 1.0 -- valid
        assert _safe_float(True) == 1.0

    def test_bool_false(self):
        assert _safe_float(False) == 0.0

    def test_numpy_float64(self):
        assert _safe_float(np.float64(7.7)) == pytest.approx(7.7)

    def test_list_returns_none(self):
        assert _safe_float([1, 2, 3]) is None


# ══════════════════════════════════════════════════════════════
#  2. _cache_key
# ══════════════════════════════════════════════════════════════


class TestCacheKey:
    """Tests for _cache_key deterministic key generation."""

    def test_returns_string(self):
        key = _cache_key("my_func", "arg1")
        assert isinstance(key, str)

    def test_contains_func_name(self):
        key = _cache_key("scan_sp500_movers", "20")
        assert "scan_sp500_movers" in key

    def test_ends_with_json(self):
        key = _cache_key("foo", "bar")
        assert key.endswith(".json")

    def test_deterministic(self):
        """Same inputs must always produce the same key."""
        key1 = _cache_key("test_func", "some_args")
        key2 = _cache_key("test_func", "some_args")
        assert key1 == key2

    def test_different_args_produce_different_keys(self):
        key1 = _cache_key("func", "a")
        key2 = _cache_key("func", "b")
        assert key1 != key2

    def test_different_funcs_produce_different_keys(self):
        key1 = _cache_key("func_a", "x")
        key2 = _cache_key("func_b", "x")
        assert key1 != key2

    def test_key_uses_sha256(self):
        """Verify the key embeds a truncated sha256 hash."""
        raw = "my_func:args123"
        expected_digest = hashlib.sha256(raw.encode()).hexdigest()[:16]
        key = _cache_key("my_func", "args123")
        assert expected_digest in key

    def test_key_lives_under_cache_dir(self):
        key = _cache_key("fn", "arg")
        assert key.startswith(CACHE_DIR)


# ══════════════════════════════════════════════════════════════
#  3. _read_cache / _write_cache roundtrip
# ══════════════════════════════════════════════════════════════


class TestCacheReadWrite:
    """Tests for file-based JSON cache roundtrip."""

    def test_write_then_read(self, tmp_path):
        """Data written to cache can be immediately read back."""
        cache_file = str(tmp_path / "test_cache.json")
        data = {"top_gainers": [{"ticker": "AAPL", "change_pct": 3.5}], "scan_date": "2026-04-07"}

        with patch("volatility_scanner.CACHE_DIR", str(tmp_path)):
            _write_cache(cache_file, data)
            result = _read_cache(cache_file)

        assert result is not None
        assert result["scan_date"] == "2026-04-07"
        assert result["top_gainers"][0]["ticker"] == "AAPL"

    def test_read_nonexistent_returns_none(self, tmp_path):
        """Reading a path that does not exist returns None."""
        result = _read_cache(str(tmp_path / "does_not_exist.json"))
        assert result is None

    def test_write_creates_cache_dir(self, tmp_path):
        """_write_cache creates CACHE_DIR if it does not exist."""
        nested = str(tmp_path / "sub" / "dir")
        cache_file = os.path.join(nested, "data.json")

        with patch("volatility_scanner.CACHE_DIR", nested):
            _write_cache(cache_file, {"key": "value"})

        assert os.path.isdir(nested)
        assert os.path.isfile(cache_file)

    def test_write_handles_non_serializable_via_default_str(self, tmp_path):
        """json.dump uses default=str so datetime objects do not crash."""
        from datetime import datetime

        cache_file = str(tmp_path / "dt_cache.json")

        with patch("volatility_scanner.CACHE_DIR", str(tmp_path)):
            _write_cache(cache_file, {"ts": datetime(2026, 4, 7, 12, 0, 0)})

        result = _read_cache(cache_file)
        assert result is not None
        assert "2026" in result["ts"]

    def test_read_corrupt_json_returns_none(self, tmp_path):
        """If the cache file contains invalid JSON, return None."""
        cache_file = str(tmp_path / "corrupt.json")
        with open(cache_file, "w") as fh:
            fh.write("{this is not valid json!!!")

        result = _read_cache(cache_file)
        assert result is None


# ══════════════════════════════════════════════════════════════
#  4. Cache expiry
# ══════════════════════════════════════════════════════════════


class TestCacheExpiry:
    """Tests for TTL-based cache expiration."""

    def test_fresh_cache_is_valid(self, tmp_path):
        """Cache younger than CACHE_MAX_AGE_SECONDS is returned."""
        cache_file = str(tmp_path / "fresh.json")
        data = {"status": "fresh"}

        with patch("volatility_scanner.CACHE_DIR", str(tmp_path)):
            _write_cache(cache_file, data)

        result = _read_cache(cache_file)
        assert result is not None
        assert result["status"] == "fresh"

    def test_expired_cache_returns_none(self, tmp_path):
        """Cache older than CACHE_MAX_AGE_SECONDS is treated as expired."""
        cache_file = str(tmp_path / "old.json")
        data = {"status": "stale"}

        with patch("volatility_scanner.CACHE_DIR", str(tmp_path)):
            _write_cache(cache_file, data)

        # Simulate the file being old by mocking time.time to return
        # a value far in the future relative to the file's mtime.
        future_time = time.time() + CACHE_MAX_AGE_SECONDS + 100
        with patch("volatility_scanner.time") as mock_time:
            mock_time.time.return_value = future_time
            result = _read_cache(cache_file)

        assert result is None

    def test_cache_just_within_ttl(self, tmp_path):
        """Cache exactly at the boundary (age == max) is still expired (strict >)."""
        cache_file = str(tmp_path / "boundary.json")
        data = {"status": "boundary"}

        with patch("volatility_scanner.CACHE_DIR", str(tmp_path)):
            _write_cache(cache_file, data)

        mtime = os.path.getmtime(cache_file)
        # age == CACHE_MAX_AGE_SECONDS => condition is >, so this is NOT expired
        at_boundary = mtime + CACHE_MAX_AGE_SECONDS
        with patch("volatility_scanner.time") as mock_time:
            mock_time.time.return_value = at_boundary
            result = _read_cache(cache_file)

        assert result is not None

    def test_cache_one_second_past_ttl(self, tmp_path):
        """Cache one second past the TTL boundary is expired."""
        cache_file = str(tmp_path / "past_boundary.json")
        data = {"status": "past"}

        with patch("volatility_scanner.CACHE_DIR", str(tmp_path)):
            _write_cache(cache_file, data)

        mtime = os.path.getmtime(cache_file)
        one_past = mtime + CACHE_MAX_AGE_SECONDS + 1
        with patch("volatility_scanner.time") as mock_time:
            mock_time.time.return_value = one_past
            result = _read_cache(cache_file)

        assert result is None


# ══════════════════════════════════════════════════════════════
#  5. scan_sp500_movers
# ══════════════════════════════════════════════════════════════


class TestScanSP500Movers:
    """Tests for scan_sp500_movers with mocked fetch layer."""

    @patch("volatility_scanner._read_cache", return_value=None)
    @patch("volatility_scanner._write_cache")
    @patch("volatility_scanner._batch_fetch_movers")
    def test_returns_expected_keys(self, mock_fetch, mock_write, mock_read, sample_movers_data):
        mock_fetch.return_value = sample_movers_data

        result = scan_sp500_movers(top_n=3)

        assert "top_gainers" in result
        assert "top_losers" in result
        assert "highest_volume" in result
        assert "scan_date" in result

    @patch("volatility_scanner._read_cache", return_value=None)
    @patch("volatility_scanner._write_cache")
    @patch("volatility_scanner._batch_fetch_movers")
    def test_calls_batch_fetch_with_sp500_list(
        self, mock_fetch, mock_write, mock_read, sample_movers_data
    ):
        mock_fetch.return_value = sample_movers_data

        scan_sp500_movers(top_n=3)

        mock_fetch.assert_called_once_with(SP500_LIQUID_100)

    @patch("volatility_scanner._read_cache", return_value=None)
    @patch("volatility_scanner._write_cache")
    @patch("volatility_scanner._batch_fetch_movers")
    def test_top_n_limits_results(self, mock_fetch, mock_write, mock_read, sample_movers_data):
        mock_fetch.return_value = sample_movers_data

        result = scan_sp500_movers(top_n=2)

        assert len(result["top_gainers"]) == 2
        assert len(result["top_losers"]) == 2

    @patch("volatility_scanner._read_cache", return_value=None)
    @patch("volatility_scanner._write_cache")
    @patch("volatility_scanner._batch_fetch_movers")
    def test_gainers_sorted_descending(self, mock_fetch, mock_write, mock_read, sample_movers_data):
        mock_fetch.return_value = sample_movers_data

        result = scan_sp500_movers(top_n=3)
        gainers = result["top_gainers"]

        changes = [g["change_pct"] for g in gainers]
        assert changes == sorted(changes, reverse=True)

    @patch("volatility_scanner._read_cache", return_value=None)
    @patch("volatility_scanner._write_cache")
    @patch("volatility_scanner._batch_fetch_movers")
    def test_losers_sorted_ascending(self, mock_fetch, mock_write, mock_read, sample_movers_data):
        """Top losers should have worst (most negative) first."""
        mock_fetch.return_value = sample_movers_data

        result = scan_sp500_movers(top_n=3)
        losers = result["top_losers"]

        changes = [l["change_pct"] for l in losers]
        # losers are reversed: worst first = ascending
        assert changes == sorted(changes)

    @patch("volatility_scanner._read_cache", return_value=None)
    @patch("volatility_scanner._write_cache")
    @patch("volatility_scanner._batch_fetch_movers")
    def test_highest_volume_filters_ratio_above_2(
        self, mock_fetch, mock_write, mock_read, sample_movers_data
    ):
        mock_fetch.return_value = sample_movers_data

        result = scan_sp500_movers(top_n=5)
        high_vol = result["highest_volume"]

        # Only items with avg_volume_ratio > 2.0 should be included
        for entry in high_vol:
            assert entry["avg_volume_ratio"] > 2.0

        # From fixture: TSLA (3.5), NVDA (2.1), META (4.0) => 3 items
        tickers = {e["ticker"] for e in high_vol}
        assert tickers == {"TSLA", "NVDA", "META"}

    @patch("volatility_scanner._read_cache", return_value=None)
    @patch("volatility_scanner._write_cache")
    @patch("volatility_scanner._batch_fetch_movers")
    def test_highest_volume_sorted_descending(
        self, mock_fetch, mock_write, mock_read, sample_movers_data
    ):
        mock_fetch.return_value = sample_movers_data

        result = scan_sp500_movers(top_n=5)
        high_vol = result["highest_volume"]

        ratios = [e["avg_volume_ratio"] for e in high_vol]
        assert ratios == sorted(ratios, reverse=True)

    @patch("volatility_scanner._read_cache", return_value=None)
    @patch("volatility_scanner._write_cache")
    @patch("volatility_scanner._batch_fetch_movers")
    def test_scan_date_format(self, mock_fetch, mock_write, mock_read, sample_movers_data):
        mock_fetch.return_value = sample_movers_data

        result = scan_sp500_movers(top_n=3)

        # scan_date should be YYYY-MM-DD format
        from datetime import datetime

        datetime.strptime(result["scan_date"], "%Y-%m-%d")

    @patch("volatility_scanner._read_cache", return_value=None)
    @patch("volatility_scanner._write_cache")
    @patch("volatility_scanner._batch_fetch_movers")
    def test_writes_result_to_cache(self, mock_fetch, mock_write, mock_read, sample_movers_data):
        mock_fetch.return_value = sample_movers_data

        result = scan_sp500_movers(top_n=3)

        mock_write.assert_called_once()
        written_data = mock_write.call_args[0][1]
        assert written_data == result

    @patch("volatility_scanner._read_cache")
    @patch("volatility_scanner._batch_fetch_movers")
    def test_returns_cached_data_on_hit(self, mock_fetch, mock_read):
        cached = {
            "top_gainers": [],
            "top_losers": [],
            "highest_volume": [],
            "scan_date": "2026-04-07",
        }
        mock_read.return_value = cached

        result = scan_sp500_movers(top_n=5)

        assert result == cached
        mock_fetch.assert_not_called()

    @patch("volatility_scanner._read_cache", return_value=None)
    @patch("volatility_scanner._write_cache")
    @patch("volatility_scanner._batch_fetch_movers")
    def test_empty_fetch_results(self, mock_fetch, mock_write, mock_read):
        """When no tickers return data, result lists should be empty."""
        mock_fetch.return_value = []

        result = scan_sp500_movers(top_n=5)

        assert result["top_gainers"] == []
        assert result["top_losers"] == []
        assert result["highest_volume"] == []


# ══════════════════════════════════════════════════════════════
#  6. scan_portfolio_movers
# ══════════════════════════════════════════════════════════════


class TestScanPortfolioMovers:
    """Tests for scan_portfolio_movers with mocked fetch layer."""

    @patch("volatility_scanner._read_cache", return_value=None)
    @patch("volatility_scanner._write_cache")
    @patch("volatility_scanner._batch_fetch_movers")
    def test_returns_expected_keys(self, mock_fetch, mock_write, mock_read, sample_movers_data):
        mock_fetch.return_value = sample_movers_data

        result = scan_portfolio_movers(["AAPL", "MSFT", "TSLA"], top_n=2)

        assert "top_gainers" in result
        assert "top_losers" in result
        assert "highest_volume" in result
        assert "scan_date" in result

    @patch("volatility_scanner._read_cache", return_value=None)
    @patch("volatility_scanner._write_cache")
    @patch("volatility_scanner._batch_fetch_movers")
    def test_calls_batch_fetch_with_user_tickers(
        self, mock_fetch, mock_write, mock_read, sample_movers_data
    ):
        tickers = ["AAPL", "MSFT", "TSLA"]
        mock_fetch.return_value = sample_movers_data

        scan_portfolio_movers(tickers, top_n=2)

        mock_fetch.assert_called_once_with(tickers)

    @patch("volatility_scanner._read_cache", return_value=None)
    @patch("volatility_scanner._write_cache")
    @patch("volatility_scanner._batch_fetch_movers")
    def test_top_n_limits_results(self, mock_fetch, mock_write, mock_read, sample_movers_data):
        mock_fetch.return_value = sample_movers_data

        result = scan_portfolio_movers(["AAPL", "MSFT"], top_n=2)

        assert len(result["top_gainers"]) == 2
        assert len(result["top_losers"]) == 2

    @patch("volatility_scanner._read_cache", return_value=None)
    @patch("volatility_scanner._write_cache")
    @patch("volatility_scanner._batch_fetch_movers")
    def test_gainers_sorted_descending(self, mock_fetch, mock_write, mock_read, sample_movers_data):
        mock_fetch.return_value = sample_movers_data

        result = scan_portfolio_movers(["AAPL"], top_n=5)
        gainers = result["top_gainers"]

        changes = [g["change_pct"] for g in gainers]
        assert changes == sorted(changes, reverse=True)

    @patch("volatility_scanner._read_cache", return_value=None)
    @patch("volatility_scanner._write_cache")
    @patch("volatility_scanner._batch_fetch_movers")
    def test_losers_sorted_ascending(self, mock_fetch, mock_write, mock_read, sample_movers_data):
        mock_fetch.return_value = sample_movers_data

        result = scan_portfolio_movers(["AAPL"], top_n=5)
        losers = result["top_losers"]

        changes = [l["change_pct"] for l in losers]
        assert changes == sorted(changes)

    @patch("volatility_scanner._read_cache", return_value=None)
    @patch("volatility_scanner._write_cache")
    @patch("volatility_scanner._batch_fetch_movers")
    def test_unusual_volume_filtering(self, mock_fetch, mock_write, mock_read, sample_movers_data):
        mock_fetch.return_value = sample_movers_data

        result = scan_portfolio_movers(["AAPL"], top_n=10)
        high_vol = result["highest_volume"]

        for entry in high_vol:
            assert entry["avg_volume_ratio"] > 2.0

    @patch("volatility_scanner._read_cache")
    @patch("volatility_scanner._batch_fetch_movers")
    def test_returns_cached_data_on_hit(self, mock_fetch, mock_read):
        cached = {
            "top_gainers": [],
            "top_losers": [],
            "highest_volume": [],
            "scan_date": "2026-04-07",
        }
        mock_read.return_value = cached

        result = scan_portfolio_movers(["AAPL", "MSFT"], top_n=5)

        assert result == cached
        mock_fetch.assert_not_called()

    @patch("volatility_scanner._read_cache", return_value=None)
    @patch("volatility_scanner._write_cache")
    @patch("volatility_scanner._batch_fetch_movers")
    def test_cache_key_includes_sorted_tickers(self, mock_fetch, mock_write, mock_read):
        """Cache key should be based on sorted ticker list, so order doesn't matter."""
        mock_fetch.return_value = []

        scan_portfolio_movers(["MSFT", "AAPL"], top_n=5)
        call1_cache_path = mock_write.call_args[0][0]

        mock_write.reset_mock()
        scan_portfolio_movers(["AAPL", "MSFT"], top_n=5)
        call2_cache_path = mock_write.call_args[0][0]

        assert call1_cache_path == call2_cache_path

    @patch("volatility_scanner._read_cache", return_value=None)
    @patch("volatility_scanner._write_cache")
    @patch("volatility_scanner._batch_fetch_movers")
    def test_none_avg_volume_ratio_excluded_from_high_volume(
        self, mock_fetch, mock_write, mock_read
    ):
        """Items with avg_volume_ratio=None should not appear in highest_volume."""
        data = [
            _make_ticker_data("A", 1.0, avg_volume_ratio=None),
            _make_ticker_data("B", 2.0, avg_volume_ratio=3.0),
        ]
        # Set None explicitly (helper sets it to a value by default)
        data[0]["avg_volume_ratio"] = None
        mock_fetch.return_value = data

        result = scan_portfolio_movers(["A", "B"], top_n=5)

        tickers = [e["ticker"] for e in result["highest_volume"]]
        assert "A" not in tickers
        assert "B" in tickers


# ══════════════════════════════════════════════════════════════
#  7. Sorting logic edge cases
# ══════════════════════════════════════════════════════════════


class TestSortingLogic:
    """Edge cases for the mover sorting logic."""

    @patch("volatility_scanner._read_cache", return_value=None)
    @patch("volatility_scanner._write_cache")
    @patch("volatility_scanner._batch_fetch_movers")
    def test_single_item(self, mock_fetch, mock_write, mock_read):
        """With a single item, it appears in both gainers and losers."""
        data = [_make_ticker_data("SOLO", 2.5)]
        mock_fetch.return_value = data

        result = scan_sp500_movers(top_n=5)

        assert len(result["top_gainers"]) == 1
        assert result["top_gainers"][0]["ticker"] == "SOLO"
        assert len(result["top_losers"]) == 1
        assert result["top_losers"][0]["ticker"] == "SOLO"

    @patch("volatility_scanner._read_cache", return_value=None)
    @patch("volatility_scanner._write_cache")
    @patch("volatility_scanner._batch_fetch_movers")
    def test_all_same_change_pct(self, mock_fetch, mock_write, mock_read):
        """All items with same change_pct should not cause errors."""
        data = [_make_ticker_data(f"T{i}", 1.0) for i in range(5)]
        mock_fetch.return_value = data

        result = scan_sp500_movers(top_n=3)

        assert len(result["top_gainers"]) == 3
        assert len(result["top_losers"]) == 3
        assert all(g["change_pct"] == 1.0 for g in result["top_gainers"])

    @patch("volatility_scanner._read_cache", return_value=None)
    @patch("volatility_scanner._write_cache")
    @patch("volatility_scanner._batch_fetch_movers")
    def test_top_n_larger_than_data(self, mock_fetch, mock_write, mock_read):
        """When top_n > len(data), return all available data without error."""
        data = [
            _make_ticker_data("X", 5.0),
            _make_ticker_data("Y", -3.0),
        ]
        mock_fetch.return_value = data

        result = scan_sp500_movers(top_n=100)

        assert len(result["top_gainers"]) == 2
        assert len(result["top_losers"]) == 2

    @patch("volatility_scanner._read_cache", return_value=None)
    @patch("volatility_scanner._write_cache")
    @patch("volatility_scanner._batch_fetch_movers")
    def test_top_gainer_is_best(self, mock_fetch, mock_write, mock_read, sample_movers_data):
        """The first gainer must be the one with the highest change_pct."""
        mock_fetch.return_value = sample_movers_data

        result = scan_sp500_movers(top_n=1)

        # TSLA has 12.0 -- highest in fixture
        assert result["top_gainers"][0]["ticker"] == "TSLA"
        assert result["top_gainers"][0]["change_pct"] == 12.0

    @patch("volatility_scanner._read_cache", return_value=None)
    @patch("volatility_scanner._write_cache")
    @patch("volatility_scanner._batch_fetch_movers")
    def test_top_loser_is_worst(self, mock_fetch, mock_write, mock_read, sample_movers_data):
        """The first loser must be the one with the most negative change_pct."""
        mock_fetch.return_value = sample_movers_data

        result = scan_sp500_movers(top_n=1)

        # META has -7.0 -- worst in fixture
        assert result["top_losers"][0]["ticker"] == "META"
        assert result["top_losers"][0]["change_pct"] == -7.0


# ══════════════════════════════════════════════════════════════
#  8. Unusual volume filtering edge cases
# ══════════════════════════════════════════════════════════════


class TestUnusualVolumeFiltering:
    """Tests for the highest_volume (avg_volume_ratio > 2.0) filter."""

    @patch("volatility_scanner._read_cache", return_value=None)
    @patch("volatility_scanner._write_cache")
    @patch("volatility_scanner._batch_fetch_movers")
    def test_ratio_exactly_2_excluded(self, mock_fetch, mock_write, mock_read):
        """avg_volume_ratio == 2.0 is NOT > 2.0, so it should be excluded."""
        data = [_make_ticker_data("EDGE", 1.0, avg_volume_ratio=2.0)]
        mock_fetch.return_value = data

        result = scan_sp500_movers(top_n=5)

        assert result["highest_volume"] == []

    @patch("volatility_scanner._read_cache", return_value=None)
    @patch("volatility_scanner._write_cache")
    @patch("volatility_scanner._batch_fetch_movers")
    def test_ratio_just_above_2_included(self, mock_fetch, mock_write, mock_read):
        """avg_volume_ratio == 2.01 should be included."""
        data = [_make_ticker_data("ABOVE", 1.0, avg_volume_ratio=2.01)]
        mock_fetch.return_value = data

        result = scan_sp500_movers(top_n=5)

        assert len(result["highest_volume"]) == 1
        assert result["highest_volume"][0]["ticker"] == "ABOVE"

    @patch("volatility_scanner._read_cache", return_value=None)
    @patch("volatility_scanner._write_cache")
    @patch("volatility_scanner._batch_fetch_movers")
    def test_no_unusual_volume(self, mock_fetch, mock_write, mock_read):
        """When no ticker has ratio > 2.0, highest_volume is empty."""
        data = [
            _make_ticker_data("A", 1.0, avg_volume_ratio=1.5),
            _make_ticker_data("B", -1.0, avg_volume_ratio=0.8),
        ]
        mock_fetch.return_value = data

        result = scan_sp500_movers(top_n=5)

        assert result["highest_volume"] == []

    @patch("volatility_scanner._read_cache", return_value=None)
    @patch("volatility_scanner._write_cache")
    @patch("volatility_scanner._batch_fetch_movers")
    def test_high_volume_includes_all_above_threshold(self, mock_fetch, mock_write, mock_read):
        """All items above 2.0 should be included, not just top_n."""
        data = [_make_ticker_data(f"T{i}", 1.0, avg_volume_ratio=2.5 + i) for i in range(10)]
        mock_fetch.return_value = data

        # top_n=3 limits gainers/losers but NOT highest_volume
        result = scan_sp500_movers(top_n=3)

        assert len(result["highest_volume"]) == 10
        assert len(result["top_gainers"]) == 3


# ══════════════════════════════════════════════════════════════
#  9. get_sector_performance
# ══════════════════════════════════════════════════════════════


class TestGetSectorPerformance:
    """Tests for get_sector_performance with mocked sector ETF fetch."""

    @patch("volatility_scanner._read_cache", return_value=None)
    @patch("volatility_scanner._write_cache")
    @patch("volatility_scanner._fetch_sector_etf")
    def test_returns_list(self, mock_fetch_etf, mock_write, mock_read):
        mock_fetch_etf.return_value = {
            "sector": "Technology",
            "ticker": "XLK",
            "change_pct": 1.5,
            "ytd_return": 8.0,
        }

        with patch("volatility_scanner.ThreadPoolExecutor") as mock_pool_cls:
            # Simulate the executor returning our mock data for each sector
            mock_pool = MagicMock()
            mock_pool_cls.return_value.__enter__ = MagicMock(return_value=mock_pool)
            mock_pool_cls.return_value.__exit__ = MagicMock(return_value=False)

            mock_future = MagicMock()
            mock_future.result.return_value = {
                "sector": "Technology",
                "ticker": "XLK",
                "change_pct": 1.5,
                "ytd_return": 8.0,
            }

            mock_pool.submit.return_value = mock_future

            with patch(
                "volatility_scanner.as_completed", return_value=[mock_future] * len(SECTOR_ETFS)
            ):
                result = get_sector_performance()

        assert isinstance(result, list)

    @patch("volatility_scanner._read_cache")
    def test_cache_hit_returns_cached(self, mock_read):
        cached = [{"sector": "Tech", "ticker": "XLK", "change_pct": 1.0, "ytd_return": 5.0}]
        mock_read.return_value = cached

        result = get_sector_performance()

        assert result == cached


# ══════════════════════════════════════════════════════════════
#  10. Constants sanity checks
# ══════════════════════════════════════════════════════════════


class TestConstants:
    """Basic sanity checks on module constants."""

    def test_sp500_liquid_100_has_entries(self):
        assert len(SP500_LIQUID_100) > 50

    def test_sp500_liquid_100_contains_known_tickers(self):
        for t in ["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA"]:
            assert t in SP500_LIQUID_100

    def test_sp500_liquid_100_no_duplicates(self):
        assert len(SP500_LIQUID_100) == len(set(SP500_LIQUID_100))

    def test_sector_etfs_has_11_sectors(self):
        assert len(SECTOR_ETFS) == 11

    def test_sector_etfs_values_are_strings(self):
        for sector, ticker in SECTOR_ETFS.items():
            assert isinstance(sector, str)
            assert isinstance(ticker, str)

    def test_cache_max_age_is_3600(self):
        assert CACHE_MAX_AGE_SECONDS == 3600

    def test_cache_dir_path(self):
        assert CACHE_DIR == ".cache/volatility_scanner"
