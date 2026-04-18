"""
tests/unit/test_options_flow.py
Unit tests for options_flow.py
Covers: _safe_float, _classify_moneyness, _process_chain_for_unusual_volume,
        get_put_call_ratio, scan_unusual_volume, scan_large_premium,
        cache helpers (_cache_key, _read_cache, _write_cache).
"""

import json
import math
import os
import time
import tempfile
import shutil

import numpy as np
import pandas as pd
import pytest
from unittest.mock import patch, MagicMock
from types import SimpleNamespace

from options_flow import (
    _safe_float,
    _classify_moneyness,
    _process_chain_for_unusual_volume,
    get_put_call_ratio,
    scan_unusual_volume,
    scan_large_premium,
    _cache_key,
    _read_cache,
    _write_cache,
    CACHE_DIR,
    CACHE_MAX_AGE_SECONDS,
)


# ======================================================================
#  Helpers
# ======================================================================

def _make_chain(calls_data: list, puts_data: list):
    """Build a mock option chain object with .calls and .puts DataFrames."""
    cols = ["strike", "volume", "openInterest", "bid", "ask"]
    calls_df = pd.DataFrame(calls_data, columns=cols) if calls_data else pd.DataFrame(columns=cols)
    puts_df = pd.DataFrame(puts_data, columns=cols) if puts_data else pd.DataFrame(columns=cols)
    return SimpleNamespace(calls=calls_df, puts=puts_df)


# ======================================================================
#  _safe_float
# ======================================================================

class TestSafeFloat:
    """Tests for the _safe_float helper."""

    def test_normal_int(self):
        assert _safe_float(42) == 42.0

    def test_normal_float(self):
        assert _safe_float(3.14) == 3.14

    def test_string_number(self):
        assert _safe_float("123.45") == 123.45

    def test_zero(self):
        assert _safe_float(0) == 0.0

    def test_negative(self):
        assert _safe_float(-7.5) == -7.5

    def test_nan_returns_none(self):
        assert _safe_float(float("nan")) is None

    def test_numpy_nan_returns_none(self):
        assert _safe_float(np.nan) is None

    def test_inf_returns_none(self):
        assert _safe_float(float("inf")) is None

    def test_neg_inf_returns_none(self):
        assert _safe_float(float("-inf")) is None

    def test_numpy_inf_returns_none(self):
        assert _safe_float(np.inf) is None

    def test_none_returns_none(self):
        assert _safe_float(None) is None

    def test_non_numeric_string_returns_none(self):
        assert _safe_float("abc") is None

    def test_empty_string_returns_none(self):
        assert _safe_float("") is None

    def test_list_returns_none(self):
        assert _safe_float([1, 2]) is None

    def test_dict_returns_none(self):
        assert _safe_float({"a": 1}) is None

    def test_bool_true(self):
        # float(True) == 1.0 in Python
        assert _safe_float(True) == 1.0

    def test_bool_false(self):
        assert _safe_float(False) == 0.0

    def test_numpy_float64(self):
        assert _safe_float(np.float64(9.81)) == pytest.approx(9.81)

    def test_numpy_int32(self):
        assert _safe_float(np.int32(100)) == 100.0


# ======================================================================
#  _classify_moneyness
# ======================================================================

class TestClassifyMoneyness:
    """Tests for moneyness classification with 2% ATM threshold."""

    # --- Call options ---

    def test_call_itm(self):
        # strike < spot by more than 2%
        assert _classify_moneyness(spot=100.0, strike=95.0, option_type="call") == "ITM"

    def test_call_otm(self):
        # strike > spot by more than 2%
        assert _classify_moneyness(spot=100.0, strike=110.0, option_type="call") == "OTM"

    def test_call_atm_exact(self):
        # strike == spot
        assert _classify_moneyness(spot=100.0, strike=100.0, option_type="call") == "ATM"

    def test_call_atm_within_2pct_above(self):
        # strike 1.5% above spot -> within 2% threshold
        assert _classify_moneyness(spot=100.0, strike=101.5, option_type="call") == "ATM"

    def test_call_atm_within_2pct_below(self):
        # strike 1.5% below spot -> within 2% threshold
        assert _classify_moneyness(spot=100.0, strike=98.5, option_type="call") == "ATM"

    def test_call_atm_at_boundary(self):
        # strike exactly 2% away -> ATM (<=0.02)
        assert _classify_moneyness(spot=100.0, strike=102.0, option_type="call") == "ATM"

    def test_call_otm_just_beyond_boundary(self):
        # strike 2.01% above spot -> OTM
        assert _classify_moneyness(spot=100.0, strike=102.01, option_type="call") == "OTM"

    def test_call_itm_just_beyond_boundary(self):
        # strike 2.01% below spot -> ITM
        assert _classify_moneyness(spot=100.0, strike=97.99, option_type="call") == "ITM"

    # --- Put options ---

    def test_put_itm(self):
        # For puts: ITM when strike > spot
        assert _classify_moneyness(spot=100.0, strike=110.0, option_type="put") == "ITM"

    def test_put_otm(self):
        # For puts: OTM when strike < spot
        assert _classify_moneyness(spot=100.0, strike=90.0, option_type="put") == "OTM"

    def test_put_atm_exact(self):
        assert _classify_moneyness(spot=100.0, strike=100.0, option_type="put") == "ATM"

    def test_put_atm_within_2pct_above(self):
        assert _classify_moneyness(spot=100.0, strike=101.5, option_type="put") == "ATM"

    def test_put_atm_within_2pct_below(self):
        assert _classify_moneyness(spot=100.0, strike=98.5, option_type="put") == "ATM"

    def test_put_atm_at_boundary(self):
        assert _classify_moneyness(spot=100.0, strike=98.0, option_type="put") == "ATM"

    def test_put_itm_just_beyond_boundary(self):
        # strike 2.01% above spot -> ITM for put
        assert _classify_moneyness(spot=100.0, strike=102.01, option_type="put") == "ITM"

    def test_put_otm_just_beyond_boundary(self):
        # strike 2.01% below spot -> OTM for put
        assert _classify_moneyness(spot=100.0, strike=97.99, option_type="put") == "OTM"

    # --- Edge cases ---

    def test_high_spot_price(self):
        # Verify percentage-based logic works at high prices
        assert _classify_moneyness(spot=5000.0, strike=5000.0, option_type="call") == "ATM"
        assert _classify_moneyness(spot=5000.0, strike=4800.0, option_type="call") == "ITM"
        assert _classify_moneyness(spot=5000.0, strike=5200.0, option_type="call") == "OTM"

    def test_small_spot_price(self):
        # Verify at penny-stock-like prices
        assert _classify_moneyness(spot=2.0, strike=2.0, option_type="put") == "ATM"
        assert _classify_moneyness(spot=2.0, strike=2.5, option_type="put") == "ITM"
        assert _classify_moneyness(spot=2.0, strike=1.5, option_type="put") == "OTM"


# ======================================================================
#  _process_chain_for_unusual_volume
# ======================================================================

class TestProcessChainForUnusualVolume:
    """Tests for processing option chains and flagging unusual volume."""

    def test_basic_call_flagged_by_vol_oi_ratio(self):
        """A call with vol/OI >= min ratio should be flagged."""
        chain = _make_chain(
            calls_data=[
                # strike, volume, openInterest, bid, ask
                [150.0, 500, 100, 2.0, 2.5],
            ],
            puts_data=[],
        )
        results = _process_chain_for_unusual_volume(
            ticker="AAPL", expiry="2026-04-17", chain=chain,
            spot=155.0, min_vol_oi_ratio=2.0,
        )
        assert len(results) == 1
        entry = results[0]
        assert entry["ticker"] == "AAPL"
        assert entry["expiry"] == "2026-04-17"
        assert entry["strike"] == 150.0
        assert entry["type"] == "call"
        assert entry["volume"] == 500
        assert entry["oi"] == 100
        assert entry["vol_oi_ratio"] == 5.0
        assert entry["sentiment"] == "BULLISH"
        assert entry["moneyness"] == "ITM"  # strike 150 < spot 155

    def test_basic_put_flagged(self):
        """A put with high vol/OI should be flagged with BEARISH sentiment."""
        chain = _make_chain(
            calls_data=[],
            puts_data=[
                [160.0, 300, 50, 3.0, 3.5],
            ],
        )
        results = _process_chain_for_unusual_volume(
            ticker="TSLA", expiry="2026-05-15", chain=chain,
            spot=155.0, min_vol_oi_ratio=2.0,
        )
        assert len(results) == 1
        entry = results[0]
        assert entry["type"] == "put"
        assert entry["sentiment"] == "BEARISH"
        assert entry["moneyness"] == "ITM"  # put: strike 160 > spot 155

    def test_not_flagged_when_below_threshold(self):
        """Options with low vol/OI and not exceeding 5x OI are skipped."""
        chain = _make_chain(
            calls_data=[
                [150.0, 100, 200, 2.0, 2.5],  # vol/oi=0.5, vol < 5*oi
            ],
            puts_data=[],
        )
        results = _process_chain_for_unusual_volume(
            ticker="AAPL", expiry="2026-04-17", chain=chain,
            spot=155.0, min_vol_oi_ratio=2.0,
        )
        assert len(results) == 0

    def test_flagged_by_5x_oi_even_below_ratio(self):
        """Volume > 5x OI should trigger flagging even if vol/oi < min_ratio."""
        # min_vol_oi_ratio = 10.0 (very high), but volume (60) > 5 * OI (10)
        chain = _make_chain(
            calls_data=[
                [150.0, 60, 10, 1.0, 1.5],  # vol/oi=6.0 < 10, but 60 > 5*10=50
            ],
            puts_data=[],
        )
        results = _process_chain_for_unusual_volume(
            ticker="AAPL", expiry="2026-04-17", chain=chain,
            spot=155.0, min_vol_oi_ratio=10.0,
        )
        assert len(results) == 1
        assert results[0]["vol_oi_ratio"] == 6.0

    def test_zero_oi_treated_as_1(self):
        """When OI is 0, effective OI should be 1 to avoid division by zero."""
        chain = _make_chain(
            calls_data=[
                [150.0, 100, 0, 2.0, 2.5],
            ],
            puts_data=[],
        )
        results = _process_chain_for_unusual_volume(
            ticker="AAPL", expiry="2026-04-17", chain=chain,
            spot=155.0, min_vol_oi_ratio=2.0,
        )
        assert len(results) == 1
        assert results[0]["vol_oi_ratio"] == 100.0  # 100/1
        assert results[0]["oi"] == 0  # reported as 0 even though effective was 1

    def test_none_oi_treated_as_1(self):
        """When OI is NaN, effective OI should be 1."""
        chain = _make_chain(
            calls_data=[
                [150.0, 100, float("nan"), 2.0, 2.5],
            ],
            puts_data=[],
        )
        results = _process_chain_for_unusual_volume(
            ticker="AAPL", expiry="2026-04-17", chain=chain,
            spot=155.0, min_vol_oi_ratio=2.0,
        )
        assert len(results) == 1
        assert results[0]["vol_oi_ratio"] == 100.0
        assert results[0]["oi"] == 0

    def test_premium_estimation_with_bid_ask(self):
        """Premium est = midpoint(bid, ask) * volume * 100."""
        chain = _make_chain(
            calls_data=[
                [150.0, 1000, 100, 2.0, 4.0],  # midpoint=3.0
            ],
            puts_data=[],
        )
        results = _process_chain_for_unusual_volume(
            ticker="AAPL", expiry="2026-04-17", chain=chain,
            spot=155.0, min_vol_oi_ratio=2.0,
        )
        assert len(results) == 1
        # premium = 3.0 * 1000 * 100 = 300,000
        assert results[0]["premium_est"] == 300000.0

    def test_premium_estimation_ask_only(self):
        """When bid is None/missing, fall back to ask * volume * 100."""
        chain_data = pd.DataFrame([{
            "strike": 150.0,
            "volume": 200,
            "openInterest": 10,
            "bid": float("nan"),
            "ask": 5.0,
        }])
        chain = SimpleNamespace(
            calls=chain_data,
            puts=pd.DataFrame(columns=["strike", "volume", "openInterest", "bid", "ask"]),
        )
        results = _process_chain_for_unusual_volume(
            ticker="AAPL", expiry="2026-04-17", chain=chain,
            spot=155.0, min_vol_oi_ratio=2.0,
        )
        assert len(results) == 1
        # premium = 5.0 * 200 * 100 = 100,000
        assert results[0]["premium_est"] == 100000.0

    def test_premium_zero_when_no_bid_no_ask(self):
        """When both bid and ask are NaN, premium should be 0."""
        chain_data = pd.DataFrame([{
            "strike": 150.0,
            "volume": 200,
            "openInterest": 10,
            "bid": float("nan"),
            "ask": float("nan"),
        }])
        chain = SimpleNamespace(
            calls=chain_data,
            puts=pd.DataFrame(columns=["strike", "volume", "openInterest", "bid", "ask"]),
        )
        results = _process_chain_for_unusual_volume(
            ticker="AAPL", expiry="2026-04-17", chain=chain,
            spot=155.0, min_vol_oi_ratio=2.0,
        )
        assert len(results) == 1
        assert results[0]["premium_est"] == 0.0

    def test_skip_zero_volume(self):
        """Rows with volume == 0 are skipped."""
        chain = _make_chain(
            calls_data=[
                [150.0, 0, 100, 2.0, 2.5],
            ],
            puts_data=[],
        )
        results = _process_chain_for_unusual_volume(
            ticker="AAPL", expiry="2026-04-17", chain=chain,
            spot=155.0, min_vol_oi_ratio=2.0,
        )
        assert len(results) == 0

    def test_skip_nan_volume(self):
        """Rows with NaN volume are skipped."""
        chain = _make_chain(
            calls_data=[
                [150.0, float("nan"), 100, 2.0, 2.5],
            ],
            puts_data=[],
        )
        results = _process_chain_for_unusual_volume(
            ticker="AAPL", expiry="2026-04-17", chain=chain,
            spot=155.0, min_vol_oi_ratio=2.0,
        )
        assert len(results) == 0

    def test_skip_missing_strike(self):
        """Rows with NaN strike are skipped."""
        chain = _make_chain(
            calls_data=[
                [float("nan"), 500, 100, 2.0, 2.5],
            ],
            puts_data=[],
        )
        results = _process_chain_for_unusual_volume(
            ticker="AAPL", expiry="2026-04-17", chain=chain,
            spot=155.0, min_vol_oi_ratio=2.0,
        )
        assert len(results) == 0

    def test_both_calls_and_puts(self):
        """Both calls and puts can appear in the results."""
        chain = _make_chain(
            calls_data=[
                [150.0, 500, 100, 2.0, 2.5],
            ],
            puts_data=[
                [160.0, 400, 50, 3.0, 3.5],
            ],
        )
        results = _process_chain_for_unusual_volume(
            ticker="AAPL", expiry="2026-04-17", chain=chain,
            spot=155.0, min_vol_oi_ratio=2.0,
        )
        assert len(results) == 2
        types = {r["type"] for r in results}
        assert types == {"call", "put"}

    def test_empty_chain(self):
        """Empty calls and puts produce no results."""
        chain = _make_chain(calls_data=[], puts_data=[])
        results = _process_chain_for_unusual_volume(
            ticker="AAPL", expiry="2026-04-17", chain=chain,
            spot=155.0, min_vol_oi_ratio=2.0,
        )
        assert len(results) == 0

    def test_multiple_strikes_mixed_flagging(self):
        """Only options meeting criteria are flagged; others are excluded."""
        chain = _make_chain(
            calls_data=[
                [140.0, 500, 100, 2.0, 2.5],   # vol/oi=5.0 -> flagged
                [145.0, 50, 200, 1.0, 1.5],     # vol/oi=0.25, 50 < 5*200 -> not flagged
                [155.0, 1000, 100, 5.0, 5.5],   # vol/oi=10.0 -> flagged
            ],
            puts_data=[],
        )
        results = _process_chain_for_unusual_volume(
            ticker="AAPL", expiry="2026-04-17", chain=chain,
            spot=150.0, min_vol_oi_ratio=2.0,
        )
        assert len(results) == 2
        strikes = {r["strike"] for r in results}
        assert strikes == {140.0, 155.0}


# ======================================================================
#  get_put_call_ratio
# ======================================================================

class TestGetPutCallRatio:
    """Tests for put/call ratio calculation and signal classification."""

    @patch("options_flow._read_cache", return_value=None)
    @patch("options_flow._write_cache")
    @patch("options_flow._get_all_chain_volumes")
    def test_bearish_signal(self, mock_volumes, mock_write, mock_read):
        """P/C ratio > 1.2 -> BEARISH."""
        mock_volumes.return_value = {
            "call_volume": 1000,
            "put_volume": 1500,  # P/C = 1.5
            "call_oi": 5000,
            "put_oi": 6000,
        }
        result = get_put_call_ratio("AAPL")
        assert result["ticker"] == "AAPL"
        assert result["volume_pc_ratio"] == 1.5
        assert result["signal"] == "BEARISH"

    @patch("options_flow._read_cache", return_value=None)
    @patch("options_flow._write_cache")
    @patch("options_flow._get_all_chain_volumes")
    def test_bullish_signal(self, mock_volumes, mock_write, mock_read):
        """P/C ratio < 0.7 -> BULLISH."""
        mock_volumes.return_value = {
            "call_volume": 2000,
            "put_volume": 1000,  # P/C = 0.5
            "call_oi": 10000,
            "put_oi": 5000,
        }
        result = get_put_call_ratio("AAPL")
        assert result["volume_pc_ratio"] == 0.5
        assert result["signal"] == "BULLISH"

    @patch("options_flow._read_cache", return_value=None)
    @patch("options_flow._write_cache")
    @patch("options_flow._get_all_chain_volumes")
    def test_neutral_signal(self, mock_volumes, mock_write, mock_read):
        """P/C ratio between 0.7 and 1.2 -> NEUTRAL."""
        mock_volumes.return_value = {
            "call_volume": 1000,
            "put_volume": 1000,  # P/C = 1.0
            "call_oi": 5000,
            "put_oi": 5000,
        }
        result = get_put_call_ratio("AAPL")
        assert result["volume_pc_ratio"] == 1.0
        assert result["signal"] == "NEUTRAL"

    @patch("options_flow._read_cache", return_value=None)
    @patch("options_flow._write_cache")
    @patch("options_flow._get_all_chain_volumes")
    def test_no_data_signal_when_volumes_none(self, mock_volumes, mock_write, mock_read):
        """When _get_all_chain_volumes returns None -> NO_DATA."""
        mock_volumes.return_value = None
        result = get_put_call_ratio("AAPL")
        assert result["signal"] == "NO_DATA"
        assert result["volume_pc_ratio"] is None
        assert result["oi_pc_ratio"] is None
        assert result["call_volume"] == 0
        assert result["put_volume"] == 0

    @patch("options_flow._read_cache", return_value=None)
    @patch("options_flow._write_cache")
    @patch("options_flow._get_all_chain_volumes")
    def test_no_data_when_zero_call_volume(self, mock_volumes, mock_write, mock_read):
        """When call volume is 0, P/C ratio is None -> NO_DATA."""
        mock_volumes.return_value = {
            "call_volume": 0,
            "put_volume": 500,
            "call_oi": 0,
            "put_oi": 1000,
        }
        result = get_put_call_ratio("AAPL")
        assert result["volume_pc_ratio"] is None
        assert result["signal"] == "NO_DATA"

    @patch("options_flow._read_cache", return_value=None)
    @patch("options_flow._write_cache")
    @patch("options_flow._get_all_chain_volumes")
    def test_oi_pc_ratio_computed(self, mock_volumes, mock_write, mock_read):
        """OI P/C ratio is separately computed."""
        mock_volumes.return_value = {
            "call_volume": 1000,
            "put_volume": 900,
            "call_oi": 5000,
            "put_oi": 8000,
        }
        result = get_put_call_ratio("AAPL")
        assert result["oi_pc_ratio"] == 1.6

    @patch("options_flow._read_cache", return_value=None)
    @patch("options_flow._write_cache")
    @patch("options_flow._get_all_chain_volumes")
    def test_boundary_bearish_at_1_2(self, mock_volumes, mock_write, mock_read):
        """P/C ratio exactly 1.2 -> NEUTRAL (not > 1.2)."""
        mock_volumes.return_value = {
            "call_volume": 1000,
            "put_volume": 1200,  # P/C = 1.2
            "call_oi": 5000,
            "put_oi": 6000,
        }
        result = get_put_call_ratio("AAPL")
        assert result["volume_pc_ratio"] == 1.2
        assert result["signal"] == "NEUTRAL"

    @patch("options_flow._read_cache", return_value=None)
    @patch("options_flow._write_cache")
    @patch("options_flow._get_all_chain_volumes")
    def test_boundary_bullish_at_0_7(self, mock_volumes, mock_write, mock_read):
        """P/C ratio exactly 0.7 -> NEUTRAL (not < 0.7)."""
        mock_volumes.return_value = {
            "call_volume": 1000,
            "put_volume": 700,  # P/C = 0.7
            "call_oi": 5000,
            "put_oi": 3500,
        }
        result = get_put_call_ratio("AAPL")
        assert result["volume_pc_ratio"] == 0.7
        assert result["signal"] == "NEUTRAL"

    @patch("options_flow._read_cache", return_value=None)
    @patch("options_flow._write_cache")
    @patch("options_flow._get_all_chain_volumes")
    def test_just_above_bearish_boundary(self, mock_volumes, mock_write, mock_read):
        """P/C ratio 1.201 -> BEARISH."""
        mock_volumes.return_value = {
            "call_volume": 10000,
            "put_volume": 12010,  # P/C = 1.201
            "call_oi": 50000,
            "put_oi": 60000,
        }
        result = get_put_call_ratio("AAPL")
        assert result["signal"] == "BEARISH"

    @patch("options_flow._read_cache", return_value=None)
    @patch("options_flow._write_cache")
    @patch("options_flow._get_all_chain_volumes")
    def test_just_below_bullish_boundary(self, mock_volumes, mock_write, mock_read):
        """P/C ratio 0.699 -> BULLISH."""
        mock_volumes.return_value = {
            "call_volume": 10000,
            "put_volume": 6990,  # P/C = 0.699
            "call_oi": 50000,
            "put_oi": 35000,
        }
        result = get_put_call_ratio("AAPL")
        assert result["signal"] == "BULLISH"

    @patch("options_flow._read_cache", return_value=None)
    @patch("options_flow._write_cache")
    @patch("options_flow._get_all_chain_volumes")
    def test_result_contains_all_fields(self, mock_volumes, mock_write, mock_read):
        """Result dict has all expected keys."""
        mock_volumes.return_value = {
            "call_volume": 1000,
            "put_volume": 800,
            "call_oi": 5000,
            "put_oi": 4000,
        }
        result = get_put_call_ratio("MSFT")
        expected_keys = {
            "ticker", "volume_pc_ratio", "oi_pc_ratio", "signal",
            "call_volume", "put_volume", "call_oi", "put_oi",
        }
        assert set(result.keys()) == expected_keys

    @patch("options_flow._read_cache", return_value=None)
    @patch("options_flow._write_cache")
    @patch("options_flow._get_all_chain_volumes")
    def test_cache_is_written(self, mock_volumes, mock_write, mock_read):
        """Result should be written to cache."""
        mock_volumes.return_value = {
            "call_volume": 1000,
            "put_volume": 800,
            "call_oi": 5000,
            "put_oi": 4000,
        }
        result = get_put_call_ratio("AAPL")
        mock_write.assert_called_once()
        # The second argument to _write_cache should be the result dict
        written_data = mock_write.call_args[0][1]
        assert written_data["ticker"] == "AAPL"


# ======================================================================
#  scan_unusual_volume
# ======================================================================

class TestScanUnusualVolume:
    """Tests for the parallel unusual volume scanner."""

    @patch("options_flow._read_cache", return_value=None)
    @patch("options_flow._write_cache")
    @patch("options_flow._scan_single_ticker_unusual_volume")
    def test_results_sorted_by_vol_oi_ratio_desc(self, mock_scan, mock_write, mock_read):
        """Results should be sorted by vol_oi_ratio in descending order."""
        mock_scan.side_effect = lambda t, r: [
            {"ticker": t, "vol_oi_ratio": 3.0, "type": "call"},
            {"ticker": t, "vol_oi_ratio": 8.0, "type": "put"},
        ] if t == "AAPL" else [
            {"ticker": t, "vol_oi_ratio": 5.0, "type": "call"},
        ]

        results = scan_unusual_volume(["AAPL", "TSLA"], min_vol_oi_ratio=2.0)
        ratios = [r["vol_oi_ratio"] for r in results]
        assert ratios == sorted(ratios, reverse=True)

    @patch("options_flow._read_cache", return_value=None)
    @patch("options_flow._write_cache")
    @patch("options_flow._scan_single_ticker_unusual_volume")
    def test_empty_results_when_nothing_unusual(self, mock_scan, mock_write, mock_read):
        """No unusual activity -> empty list."""
        mock_scan.return_value = []
        results = scan_unusual_volume(["AAPL", "TSLA"])
        assert results == []

    @patch("options_flow._read_cache")
    def test_returns_cached_result(self, mock_read):
        """Should return cached data without scanning."""
        cached_data = [{"ticker": "AAPL", "vol_oi_ratio": 5.0}]
        mock_read.return_value = cached_data
        results = scan_unusual_volume(["AAPL"])
        assert results == cached_data

    @patch("options_flow._read_cache", return_value=None)
    @patch("options_flow._write_cache")
    @patch("options_flow._scan_single_ticker_unusual_volume")
    def test_aggregates_multiple_tickers(self, mock_scan, mock_write, mock_read):
        """Results from all tickers are aggregated."""
        mock_scan.side_effect = lambda t, r: [
            {"ticker": t, "vol_oi_ratio": 4.0},
        ]
        results = scan_unusual_volume(["AAPL", "TSLA", "NVDA"])
        assert len(results) == 3
        tickers = {r["ticker"] for r in results}
        assert tickers == {"AAPL", "TSLA", "NVDA"}


# ======================================================================
#  scan_large_premium
# ======================================================================

class TestScanLargePremium:
    """Tests for the large premium scanner."""

    @patch("options_flow._read_cache", return_value=None)
    @patch("options_flow._write_cache")
    @patch("options_flow._scan_single_ticker_large_premium")
    def test_results_sorted_by_premium_desc(self, mock_scan, mock_write, mock_read):
        """Results should be sorted by premium_est in descending order."""
        mock_scan.side_effect = lambda t, p: [
            {"ticker": t, "premium_est": 100000},
            {"ticker": t, "premium_est": 500000},
        ] if t == "AAPL" else [
            {"ticker": t, "premium_est": 250000},
        ]

        results = scan_large_premium(["AAPL", "TSLA"], min_premium=50000)
        premiums = [r["premium_est"] for r in results]
        assert premiums == sorted(premiums, reverse=True)

    @patch("options_flow._read_cache", return_value=None)
    @patch("options_flow._write_cache")
    @patch("options_flow._scan_single_ticker_large_premium")
    def test_empty_results(self, mock_scan, mock_write, mock_read):
        """No large premium trades -> empty list."""
        mock_scan.return_value = []
        results = scan_large_premium(["AAPL", "TSLA"])
        assert results == []

    @patch("options_flow._read_cache")
    def test_returns_cached_result(self, mock_read):
        """Should return cached data without scanning."""
        cached_data = [{"ticker": "AAPL", "premium_est": 200000}]
        mock_read.return_value = cached_data
        results = scan_large_premium(["AAPL"])
        assert results == cached_data


# ======================================================================
#  Cache helpers
# ======================================================================

class TestCacheHelpers:
    """Tests for _cache_key, _read_cache, _write_cache."""

    def test_cache_key_deterministic(self):
        """Same inputs produce the same cache key."""
        key1 = _cache_key("scan_unusual_volume", "AAPL,TSLA_2.0")
        key2 = _cache_key("scan_unusual_volume", "AAPL,TSLA_2.0")
        assert key1 == key2

    def test_cache_key_different_for_different_inputs(self):
        """Different inputs produce different cache keys."""
        key1 = _cache_key("scan_unusual_volume", "AAPL_2.0")
        key2 = _cache_key("scan_unusual_volume", "TSLA_2.0")
        assert key1 != key2

    def test_cache_key_includes_func_name(self):
        """Different function names produce different keys."""
        key1 = _cache_key("scan_unusual_volume", "AAPL_2.0")
        key2 = _cache_key("get_put_call_ratio", "AAPL_2.0")
        assert key1 != key2

    def test_cache_key_is_valid_path(self):
        """Cache key should be a valid file path under CACHE_DIR."""
        key = _cache_key("scan_unusual_volume", "AAPL_2.0")
        assert key.startswith(CACHE_DIR)
        assert key.endswith(".json")

    def test_cache_roundtrip(self, tmp_path):
        """Write and read back data through the cache."""
        test_data = {"ticker": "AAPL", "vol_oi_ratio": 5.0, "results": [1, 2, 3]}
        cache_file = str(tmp_path / "test_cache.json")

        # Patch CACHE_DIR so _write_cache uses our temp directory
        with patch("options_flow.CACHE_DIR", str(tmp_path)):
            _write_cache(cache_file, test_data)
            result = _read_cache(cache_file)

        assert result is not None
        assert result["ticker"] == "AAPL"
        assert result["vol_oi_ratio"] == 5.0
        assert result["results"] == [1, 2, 3]

    def test_read_cache_returns_none_for_missing_file(self):
        """Reading a non-existent cache file returns None."""
        result = _read_cache("/tmp/nonexistent_cache_file_12345.json")
        assert result is None

    def test_read_cache_returns_none_for_expired_entry(self, tmp_path):
        """Expired cache entries return None."""
        cache_file = str(tmp_path / "expired.json")
        data = {"key": "value"}
        with open(cache_file, "w") as fh:
            json.dump(data, fh)

        # Set modification time to well beyond max age
        old_time = time.time() - CACHE_MAX_AGE_SECONDS - 100
        os.utime(cache_file, (old_time, old_time))

        result = _read_cache(cache_file)
        assert result is None

    def test_read_cache_returns_data_for_fresh_entry(self, tmp_path):
        """Fresh cache entries are returned successfully."""
        cache_file = str(tmp_path / "fresh.json")
        data = {"key": "fresh_value"}
        with open(cache_file, "w") as fh:
            json.dump(data, fh)

        # File was just created so mtime is now -> well within max age
        result = _read_cache(cache_file)
        assert result is not None
        assert result["key"] == "fresh_value"

    def test_read_cache_returns_none_for_corrupt_json(self, tmp_path):
        """Corrupt JSON files return None gracefully."""
        cache_file = str(tmp_path / "corrupt.json")
        with open(cache_file, "w") as fh:
            fh.write("not valid json {{{")

        result = _read_cache(cache_file)
        assert result is None

    def test_write_cache_creates_directory(self, tmp_path):
        """_write_cache should create the cache directory if it does not exist."""
        nested_dir = str(tmp_path / "sub" / "cache")
        cache_file = os.path.join(nested_dir, "test.json")

        with patch("options_flow.CACHE_DIR", nested_dir):
            _write_cache(cache_file, {"test": True})

        assert os.path.exists(cache_file)
        with open(cache_file) as fh:
            assert json.load(fh) == {"test": True}

    def test_write_cache_handles_non_serializable_gracefully(self, tmp_path):
        """_write_cache uses default=str to handle non-JSON types."""
        from datetime import datetime as dt
        cache_file = str(tmp_path / "datetime_test.json")

        with patch("options_flow.CACHE_DIR", str(tmp_path)):
            _write_cache(cache_file, {"timestamp": dt(2026, 1, 1, 12, 0, 0)})

        result = _read_cache(cache_file)
        assert result is not None
        assert "2026" in result["timestamp"]

    def test_cache_max_age_is_1800_seconds(self):
        """Verify the cache max age constant is 30 minutes."""
        assert CACHE_MAX_AGE_SECONDS == 1800

    def test_cache_dir_path(self):
        """Verify the cache directory constant."""
        assert CACHE_DIR == ".cache/options_flow"
