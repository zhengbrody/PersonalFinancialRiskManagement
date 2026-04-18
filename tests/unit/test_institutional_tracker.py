"""
tests/unit/test_institutional_tracker.py
Unit tests for institutional_tracker.py — SEC 13F Institutional Holdings Tracker.

Covers:
  - Constants validation (institution registry, CUSIP mappings, SEC headers)
  - File-based cache round-trip (read/write with tmp_path)
  - Cache key generation (deterministic, filename-safe)
  - CUSIP-to-ticker resolution
  - 13F XML parsing (_parse_13f_xml) with realistic SEC filing XML
  - fetch_13f_holdings with mocked HTTP responses
  - get_smart_money_signals with mocked fetch_13f_holdings
  - Helper functions (get_institution_name, get_institution_cik, etc.)
"""

import json
import os
import time
import pytest
from unittest.mock import patch, MagicMock

from institutional_tracker import (
    CUSIP_TO_TICKER,
    TICKER_TO_CUSIPS,
    SEC_HEADERS,
    CACHE_DIR,
    CACHE_MAX_AGE_SECONDS,
    _TOP_INSTITUTIONS,
    get_top_institutions,
    _cache_key,
    _read_cache,
    _write_cache,
    _cusip_to_ticker,
    _parse_13f_xml,
    fetch_13f_holdings,
    get_smart_money_signals,
    get_institutional_ownership,
    get_institution_name,
    get_institution_cik,
    summarize_top_holdings,
    clear_cache,
)


# ══════════════════════════════════════════════════════════════
#  Sample XML fixtures
# ══════════════════════════════════════════════════════════════

SAMPLE_13F_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<informationTable xmlns="http://www.sec.gov/edgar/document/thirteenf/informationtable">
  <infoTable>
    <nameOfIssuer>APPLE INC</nameOfIssuer>
    <cusip>037833100</cusip>
    <value>5000000</value>
    <shrsOrPrnAmt>
      <sshPrnamt>25000</sshPrnamt>
      <sshPrnamtType>SH</sshPrnamtType>
    </shrsOrPrnAmt>
    <investmentDiscretion>SOLE</investmentDiscretion>
  </infoTable>
  <infoTable>
    <nameOfIssuer>MICROSOFT CORP</nameOfIssuer>
    <cusip>594918104</cusip>
    <value>3000000</value>
    <shrsOrPrnAmt>
      <sshPrnamt>15000</sshPrnamt>
      <sshPrnamtType>SH</sshPrnamtType>
    </shrsOrPrnAmt>
    <investmentDiscretion>SOLE</investmentDiscretion>
  </infoTable>
  <infoTable>
    <nameOfIssuer>NVIDIA CORP</nameOfIssuer>
    <cusip>67066G104</cusip>
    <value>2000000</value>
    <shrsOrPrnAmt>
      <sshPrnamt>10000</sshPrnamt>
      <sshPrnamtType>SH</sshPrnamtType>
    </shrsOrPrnAmt>
    <investmentDiscretion>DFND</investmentDiscretion>
  </infoTable>
</informationTable>
"""

SAMPLE_13F_XML_NO_NS = """\
<?xml version="1.0" encoding="UTF-8"?>
<informationTable>
  <infoTable>
    <nameOfIssuer>TESLA INC</nameOfIssuer>
    <cusip>88160R101</cusip>
    <value>1500000</value>
    <shrsOrPrnAmt>
      <sshPrnamt>8000</sshPrnamt>
      <sshPrnamtType>SH</sshPrnamtType>
    </shrsOrPrnAmt>
    <investmentDiscretion>SOLE</investmentDiscretion>
  </infoTable>
</informationTable>
"""

SAMPLE_13F_XML_EMPTY = """\
<?xml version="1.0" encoding="UTF-8"?>
<informationTable xmlns="http://www.sec.gov/edgar/document/thirteenf/informationtable">
</informationTable>
"""

SAMPLE_SUBMISSIONS_JSON = {
    "cik": "0001067983",
    "entityType": "entity",
    "name": "BERKSHIRE HATHAWAY INC",
    "filings": {
        "recent": {
            "accessionNumber": [
                "0000950123-24-005678",
                "0000950123-24-001234",
                "0000950123-23-009876",
            ],
            "filingDate": [
                "2024-02-14",
                "2023-11-15",
                "2023-08-14",
            ],
            "form": [
                "13F-HR",
                "13F-HR",
                "13F-HR",
            ],
            "primaryDocument": [
                "primary_doc.xml",
                "primary_doc.xml",
                "primary_doc.xml",
            ],
        }
    },
}

SAMPLE_INDEX_JSON = {
    "directory": {
        "item": [
            {"name": "primary_doc.xml", "type": "primary"},
            {"name": "infotable.xml", "type": "informationtable"},
        ]
    }
}


# ══════════════════════════════════════════════════════════════
#  Section 1 — Constants Validation
# ══════════════════════════════════════════════════════════════


class TestConstants:
    """Validate module-level constants and registries."""

    def test_top_institutions_is_nonempty(self):
        """The institution registry should have at least 30 entries."""
        assert len(_TOP_INSTITUTIONS) >= 30

    def test_top_institutions_contains_berkshire_hathaway(self):
        names = [name for name, _ in _TOP_INSTITUTIONS]
        assert "Berkshire Hathaway" in names

    def test_top_institutions_contains_bridgewater(self):
        names = [name for name, _ in _TOP_INSTITUTIONS]
        assert "Bridgewater Associates" in names

    def test_top_institutions_contains_renaissance(self):
        names = [name for name, _ in _TOP_INSTITUTIONS]
        assert "Renaissance Technologies" in names

    def test_top_institutions_contains_citadel(self):
        names = [name for name, _ in _TOP_INSTITUTIONS]
        assert "Citadel Advisors" in names

    def test_top_institutions_contains_blackrock(self):
        names = [name for name, _ in _TOP_INSTITUTIONS]
        assert "BlackRock" in names

    def test_top_institutions_contains_vanguard(self):
        names = [name for name, _ in _TOP_INSTITUTIONS]
        assert "Vanguard Group" in names

    def test_top_institutions_cik_format(self):
        """All CIK values should be zero-padded 10-digit strings."""
        for name, cik in _TOP_INSTITUTIONS:
            assert len(cik) == 10, f"{name} CIK '{cik}' is not 10 digits"
            assert cik.isdigit(), f"{name} CIK '{cik}' is not all digits"

    def test_get_top_institutions_returns_dicts(self):
        result = get_top_institutions()
        assert isinstance(result, list)
        assert len(result) == len(_TOP_INSTITUTIONS)
        for item in result:
            assert "name" in item
            assert "cik" in item

    def test_get_top_institutions_first_entry(self):
        result = get_top_institutions()
        assert result[0]["name"] == "Berkshire Hathaway"
        assert result[0]["cik"] == "0001067983"

    def test_cusip_to_ticker_has_known_mappings(self):
        """Verify key CUSIP -> ticker entries exist."""
        assert CUSIP_TO_TICKER["037833100"] == "AAPL"
        assert CUSIP_TO_TICKER["594918104"] == "MSFT"
        assert CUSIP_TO_TICKER["67066G104"] == "NVDA"
        assert CUSIP_TO_TICKER["023135106"] == "AMZN"
        assert CUSIP_TO_TICKER["88160R101"] == "TSLA"

    def test_cusip_to_ticker_count(self):
        """Mapping should have a substantial number of entries."""
        assert len(CUSIP_TO_TICKER) >= 80

    def test_ticker_to_cusips_reverse_mapping(self):
        """TICKER_TO_CUSIPS should be the reverse of CUSIP_TO_TICKER."""
        assert "AAPL" in TICKER_TO_CUSIPS
        assert "037833100" in TICKER_TO_CUSIPS["AAPL"]

    def test_sec_headers_has_user_agent(self):
        assert "User-Agent" in SEC_HEADERS
        assert "MindMarket" in SEC_HEADERS["User-Agent"]

    def test_cache_dir_path(self):
        assert CACHE_DIR == ".cache/institutional_tracker"

    def test_cache_max_age(self):
        assert CACHE_MAX_AGE_SECONDS == 86400


# ══════════════════════════════════════════════════════════════
#  Section 2 — Cache Functions
# ══════════════════════════════════════════════════════════════


class TestCacheKey:
    """Tests for deterministic cache key generation."""

    def test_cache_key_is_deterministic(self):
        key1 = _cache_key("my_func", "arg1")
        key2 = _cache_key("my_func", "arg1")
        assert key1 == key2

    def test_cache_key_different_for_different_args(self):
        key1 = _cache_key("func", "a")
        key2 = _cache_key("func", "b")
        assert key1 != key2

    def test_cache_key_different_for_different_funcs(self):
        key1 = _cache_key("func_a", "arg")
        key2 = _cache_key("func_b", "arg")
        assert key1 != key2

    def test_cache_key_format(self):
        key = _cache_key("fetch_13f", "some_cik")
        assert key.startswith("fetch_13f_")
        assert key.endswith(".json")

    def test_cache_key_hash_portion_is_hex(self):
        """The hash portion of the key should be a hexadecimal string."""
        key = _cache_key("fetch_13f", "some_cik")
        # Key format: "{func_name}_{hash}.json"
        # Extract the hash part between the last underscore and '.json'
        name_part, ext = os.path.splitext(key)
        assert ext == ".json"
        # The hash is the last 16 chars of name_part (after the prefix + '_')
        prefix = "fetch_13f_"
        assert name_part.startswith(prefix)
        hash_part = name_part[len(prefix):]
        assert len(hash_part) == 16
        # Hash should be lowercase hex
        int(hash_part, 16)  # Raises ValueError if not valid hex


class TestCacheRoundtrip:
    """Test cache read/write using tmp_path to avoid side effects."""

    def test_write_then_read_returns_data(self, tmp_path):
        """Data written to cache should be readable back."""
        test_data = {"holdings": [{"ticker": "AAPL", "shares": 100}]}
        cache_key = "test_roundtrip.json"

        with patch("institutional_tracker.CACHE_DIR", str(tmp_path)):
            _write_cache(cache_key, test_data)
            result = _read_cache(cache_key)

        assert result is not None
        assert result == test_data

    def test_read_cache_miss_returns_none(self, tmp_path):
        """Reading a nonexistent key should return None."""
        with patch("institutional_tracker.CACHE_DIR", str(tmp_path)):
            result = _read_cache("nonexistent_key.json")

        assert result is None

    def test_write_cache_creates_file(self, tmp_path):
        test_data = {"key": "value"}
        cache_key = "file_check.json"

        with patch("institutional_tracker.CACHE_DIR", str(tmp_path)):
            _write_cache(cache_key, test_data)

        assert os.path.exists(os.path.join(str(tmp_path), cache_key))

    def test_cache_expired_returns_none(self, tmp_path):
        """Expired cache entries should return None."""
        test_data = {"old": True}
        cache_key = "expired.json"

        with patch("institutional_tracker.CACHE_DIR", str(tmp_path)):
            _write_cache(cache_key, test_data)

            # Manually backdate the file modification time
            fpath = os.path.join(str(tmp_path), cache_key)
            old_time = time.time() - CACHE_MAX_AGE_SECONDS - 100
            os.utime(fpath, (old_time, old_time))

            result = _read_cache(cache_key)

        assert result is None

    def test_cache_not_expired_returns_data(self, tmp_path):
        """Non-expired cache entries should still be returned."""
        test_data = {"fresh": True}
        cache_key = "fresh.json"

        with patch("institutional_tracker.CACHE_DIR", str(tmp_path)):
            _write_cache(cache_key, test_data)
            # File was just written, so it is fresh
            result = _read_cache(cache_key)

        assert result == test_data

    def test_write_cache_handles_nested_data(self, tmp_path):
        nested = {
            "level1": {
                "level2": [1, 2, {"level3": "deep"}],
            },
            "number": 42,
        }
        cache_key = "nested.json"

        with patch("institutional_tracker.CACHE_DIR", str(tmp_path)):
            _write_cache(cache_key, nested)
            result = _read_cache(cache_key)

        assert result == nested


# ══════════════════════════════════════════════════════════════
#  Section 3 — CUSIP Resolution
# ══════════════════════════════════════════════════════════════


class TestCusipToTicker:
    """Tests for _cusip_to_ticker resolution logic."""

    def test_known_cusip_resolves(self):
        assert _cusip_to_ticker("037833100") == "AAPL"
        assert _cusip_to_ticker("594918104") == "MSFT"

    def test_unknown_cusip_returns_cusip(self):
        """Unknown CUSIPs should fall back to returning the CUSIP itself."""
        unknown = "999999999"
        assert _cusip_to_ticker(unknown) == unknown

    def test_8char_cusip_prefix_resolves(self):
        """8-character CUSIP prefix (without check digit) should also resolve."""
        # "037833100" is AAPL; base is "03783310"
        # The function tries cusip_base + "0" = "037833100" which is in the map
        result = _cusip_to_ticker("03783310")
        assert result == "AAPL"

    def test_nvidia_cusip(self):
        assert _cusip_to_ticker("67066G104") == "NVDA"

    def test_tesla_cusip(self):
        assert _cusip_to_ticker("88160R101") == "TSLA"


# ══════════════════════════════════════════════════════════════
#  Section 4 — 13F XML Parsing
# ══════════════════════════════════════════════════════════════


class TestParse13fXml:
    """Tests for _parse_13f_xml with realistic SEC filing XML."""

    def test_parse_standard_xml_returns_holdings(self):
        holdings = _parse_13f_xml(SAMPLE_13F_XML)
        assert len(holdings) == 3

    def test_parse_standard_xml_first_holding(self):
        holdings = _parse_13f_xml(SAMPLE_13F_XML)
        aapl = holdings[0]
        assert aapl["cusip"] == "037833100"
        assert aapl["name"] == "APPLE INC"
        assert aapl["shares"] == 25000
        # value is reported in thousands, then multiplied by 1000
        assert aapl["value"] == 5000000 * 1000
        assert aapl["investment_discretion"] == "SOLE"

    def test_parse_standard_xml_second_holding(self):
        holdings = _parse_13f_xml(SAMPLE_13F_XML)
        msft = holdings[1]
        assert msft["cusip"] == "594918104"
        assert msft["name"] == "MICROSOFT CORP"
        assert msft["shares"] == 15000
        assert msft["value"] == 3000000 * 1000

    def test_parse_standard_xml_investment_discretion(self):
        holdings = _parse_13f_xml(SAMPLE_13F_XML)
        nvda = holdings[2]
        assert nvda["investment_discretion"] == "DFND"

    def test_parse_no_namespace_xml(self):
        """XML without namespace should still parse correctly."""
        holdings = _parse_13f_xml(SAMPLE_13F_XML_NO_NS)
        assert len(holdings) == 1
        assert holdings[0]["cusip"] == "88160R101"
        assert holdings[0]["name"] == "TESLA INC"
        assert holdings[0]["shares"] == 8000

    def test_parse_empty_xml(self):
        """Empty information table should return no holdings."""
        holdings = _parse_13f_xml(SAMPLE_13F_XML_EMPTY)
        assert holdings == []

    def test_parse_invalid_xml(self):
        """Completely invalid XML should return empty list, not raise."""
        holdings = _parse_13f_xml("this is not xml at all")
        assert holdings == []

    def test_parse_missing_cusip_skips_entry(self):
        """An infoTable entry without a cusip element should be skipped."""
        xml = """\
<?xml version="1.0" encoding="UTF-8"?>
<informationTable xmlns="http://www.sec.gov/edgar/document/thirteenf/informationtable">
  <infoTable>
    <nameOfIssuer>NO CUSIP INC</nameOfIssuer>
    <value>1000</value>
    <shrsOrPrnAmt>
      <sshPrnamt>500</sshPrnamt>
    </shrsOrPrnAmt>
  </infoTable>
  <infoTable>
    <nameOfIssuer>HAS CUSIP INC</nameOfIssuer>
    <cusip>037833100</cusip>
    <value>2000</value>
    <shrsOrPrnAmt>
      <sshPrnamt>1000</sshPrnamt>
    </shrsOrPrnAmt>
  </infoTable>
</informationTable>
"""
        holdings = _parse_13f_xml(xml)
        assert len(holdings) == 1
        assert holdings[0]["cusip"] == "037833100"


# ══════════════════════════════════════════════════════════════
#  Section 5 — fetch_13f_holdings (mocked HTTP)
# ══════════════════════════════════════════════════════════════


class TestFetch13fHoldings:
    """Test fetch_13f_holdings with mocked HTTP responses."""

    @patch("institutional_tracker.requests.get")
    def test_fetch_13f_holdings_success(self, mock_get, tmp_path):
        """Full success path: submissions JSON -> index JSON -> XML table."""
        # Response 1: submissions JSON
        submissions_resp = MagicMock()
        submissions_resp.status_code = 200
        submissions_resp.json.return_value = SAMPLE_SUBMISSIONS_JSON

        # Response 2: filing index JSON
        index_resp = MagicMock()
        index_resp.status_code = 200
        index_resp.json.return_value = SAMPLE_INDEX_JSON

        # Response 3: 13F information table XML
        xml_resp = MagicMock()
        xml_resp.status_code = 200
        xml_resp.text = SAMPLE_13F_XML

        mock_get.side_effect = [submissions_resp, index_resp, xml_resp]

        with patch("institutional_tracker.CACHE_DIR", str(tmp_path)):
            with patch("institutional_tracker._read_cache", return_value=None):
                results = fetch_13f_holdings("0001067983", limit=1)

        assert len(results) >= 1
        holdings = results[0]["holdings"]
        assert len(holdings) == 3
        # Check that tickers were resolved from CUSIPs
        tickers = [h["ticker"] for h in holdings]
        assert "AAPL" in tickers
        assert "MSFT" in tickers
        assert "NVDA" in tickers

    @patch("institutional_tracker.requests.get")
    def test_fetch_13f_holdings_no_filings(self, mock_get, tmp_path):
        """When SEC returns no matching 13F filings, result is empty."""
        submissions_resp = MagicMock()
        submissions_resp.status_code = 200
        # Filings exist but none are 13F-HR
        submissions_resp.json.return_value = {
            "cik": "0001067983",
            "filings": {
                "recent": {
                    "accessionNumber": ["0000950123-24-005678"],
                    "filingDate": ["2024-02-14"],
                    "form": ["10-K"],  # Not a 13F
                    "primaryDocument": ["primary.htm"],
                }
            },
        }

        mock_get.side_effect = [submissions_resp]

        with patch("institutional_tracker.CACHE_DIR", str(tmp_path)):
            with patch("institutional_tracker._read_cache", return_value=None):
                results = fetch_13f_holdings("0001067983", limit=1)

        assert results == []

    @patch("institutional_tracker.requests.get")
    def test_fetch_13f_holdings_sec_api_failure(self, mock_get, tmp_path):
        """When the SEC API returns an error, result is empty."""
        error_resp = MagicMock()
        error_resp.status_code = 500

        mock_get.return_value = error_resp

        with patch("institutional_tracker.CACHE_DIR", str(tmp_path)):
            with patch("institutional_tracker._read_cache", return_value=None):
                results = fetch_13f_holdings("0001067983", limit=1)

        assert results == []

    @patch("institutional_tracker.requests.get")
    def test_fetch_13f_holdings_uses_cache(self, mock_get, tmp_path):
        """Cached results should be returned without making HTTP requests."""
        cached_data = [
            {
                "filing_date": "2024-02-14",
                "holdings": [
                    {
                        "ticker": "AAPL",
                        "name": "APPLE INC",
                        "cusip": "037833100",
                        "shares": 25000,
                        "value": 5000000000,
                        "change_pct_qoq": None,
                    }
                ],
            }
        ]

        with patch("institutional_tracker.CACHE_DIR", str(tmp_path)):
            with patch("institutional_tracker._read_cache", return_value=cached_data):
                results = fetch_13f_holdings("0001067983", limit=1)

        # No HTTP calls should have been made
        mock_get.assert_not_called()
        assert results == cached_data

    @patch("institutional_tracker.requests.get")
    def test_fetch_13f_holdings_filing_date_in_result(self, mock_get, tmp_path):
        """Result should include the filing date from SEC metadata."""
        submissions_resp = MagicMock()
        submissions_resp.status_code = 200
        submissions_resp.json.return_value = SAMPLE_SUBMISSIONS_JSON

        index_resp = MagicMock()
        index_resp.status_code = 200
        index_resp.json.return_value = SAMPLE_INDEX_JSON

        xml_resp = MagicMock()
        xml_resp.status_code = 200
        xml_resp.text = SAMPLE_13F_XML

        mock_get.side_effect = [submissions_resp, index_resp, xml_resp]

        with patch("institutional_tracker.CACHE_DIR", str(tmp_path)):
            with patch("institutional_tracker._read_cache", return_value=None):
                results = fetch_13f_holdings("0001067983", limit=1)

        assert results[0]["filing_date"] == "2024-02-14"


# ══════════════════════════════════════════════════════════════
#  Section 6 — get_smart_money_signals (mocked fetch)
# ══════════════════════════════════════════════════════════════


class TestGetSmartMoneySignals:
    """Test get_smart_money_signals with mocked dependencies."""

    @patch("institutional_tracker.fetch_13f_holdings")
    def test_smart_money_signals_high_conviction(self, mock_fetch, tmp_path):
        """Ticker held by >10 institutions should get HIGH_CONVICTION."""
        # Create fake holdings for many institutions, all holding AAPL
        fake_filing = [
            {
                "filing_date": "2024-02-14",
                "holdings": [
                    {
                        "ticker": "AAPL",
                        "name": "APPLE INC",
                        "cusip": "037833100",
                        "shares": 10000,
                        "value": 1000000,
                        "change_pct_qoq": None,
                    }
                ],
            }
        ]
        mock_fetch.return_value = fake_filing

        with patch("institutional_tracker.CACHE_DIR", str(tmp_path)):
            with patch("institutional_tracker._read_cache", return_value=None):
                results = get_smart_money_signals(["AAPL"])

        assert len(results) == 1
        aapl_signal = results[0]
        assert aapl_signal["ticker"] == "AAPL"
        # All ~31 institutions will "hold" AAPL -> HIGH_CONVICTION
        assert aapl_signal["signal"] == "HIGH_CONVICTION"
        assert aapl_signal["num_institutions"] > 10

    @patch("institutional_tracker.fetch_13f_holdings")
    def test_smart_money_signals_low_conviction(self, mock_fetch, tmp_path):
        """Ticker held by <5 institutions should get LOW signal."""
        # Only return holdings for a few institutions, none holding XYZ
        fake_filing = [
            {
                "filing_date": "2024-02-14",
                "holdings": [
                    {
                        "ticker": "NOPE",
                        "name": "NOPE INC",
                        "cusip": "000000000",
                        "shares": 10000,
                        "value": 1000000,
                        "change_pct_qoq": None,
                    }
                ],
            }
        ]
        mock_fetch.return_value = fake_filing

        with patch("institutional_tracker.CACHE_DIR", str(tmp_path)):
            with patch("institutional_tracker._read_cache", return_value=None):
                results = get_smart_money_signals(["XYZ"])

        assert len(results) == 1
        assert results[0]["ticker"] == "XYZ"
        assert results[0]["signal"] == "LOW"
        assert results[0]["num_institutions"] == 0

    @patch("institutional_tracker.fetch_13f_holdings")
    def test_smart_money_signals_empty_portfolio(self, mock_fetch, tmp_path):
        """Empty portfolio should return empty list."""
        with patch("institutional_tracker.CACHE_DIR", str(tmp_path)):
            with patch("institutional_tracker._read_cache", return_value=None):
                results = get_smart_money_signals([])

        assert results == []
        mock_fetch.assert_not_called()

    @patch("institutional_tracker.fetch_13f_holdings")
    def test_smart_money_signals_multiple_tickers(self, mock_fetch, tmp_path):
        """Multiple tickers should each get a signal."""
        fake_filing = [
            {
                "filing_date": "2024-02-14",
                "holdings": [
                    {
                        "ticker": "AAPL",
                        "name": "APPLE INC",
                        "cusip": "037833100",
                        "shares": 10000,
                        "value": 1000000,
                        "change_pct_qoq": None,
                    },
                    {
                        "ticker": "MSFT",
                        "name": "MICROSOFT CORP",
                        "cusip": "594918104",
                        "shares": 5000,
                        "value": 500000,
                        "change_pct_qoq": None,
                    },
                ],
            }
        ]
        mock_fetch.return_value = fake_filing

        with patch("institutional_tracker.CACHE_DIR", str(tmp_path)):
            with patch("institutional_tracker._read_cache", return_value=None):
                results = get_smart_money_signals(["AAPL", "MSFT", "UNKNOWN"])

        assert len(results) == 3
        tickers_returned = {r["ticker"] for r in results}
        assert tickers_returned == {"AAPL", "MSFT", "UNKNOWN"}

    @patch("institutional_tracker.fetch_13f_holdings")
    def test_smart_money_signals_sorted_by_conviction(self, mock_fetch, tmp_path):
        """Results should be sorted by num_institutions descending."""
        # AAPL will be held by all institutions, RANDO by none
        def fake_fetch(cik, limit=1):
            return [
                {
                    "filing_date": "2024-02-14",
                    "holdings": [
                        {
                            "ticker": "AAPL",
                            "name": "APPLE INC",
                            "cusip": "037833100",
                            "shares": 10000,
                            "value": 1000000,
                            "change_pct_qoq": None,
                        }
                    ],
                }
            ]

        mock_fetch.side_effect = fake_fetch

        with patch("institutional_tracker.CACHE_DIR", str(tmp_path)):
            with patch("institutional_tracker._read_cache", return_value=None):
                results = get_smart_money_signals(["RANDO", "AAPL"])

        # AAPL should come first (more institutions hold it)
        assert results[0]["ticker"] == "AAPL"
        assert results[-1]["ticker"] == "RANDO"

    @patch("institutional_tracker.fetch_13f_holdings")
    def test_smart_money_signals_fetch_error_handled(self, mock_fetch, tmp_path):
        """If fetch_13f_holdings raises for some institutions, others still work."""
        call_count = 0

        def flaky_fetch(cik, limit=1):
            nonlocal call_count
            call_count += 1
            if call_count % 3 == 0:
                raise ConnectionError("simulated failure")
            return [
                {
                    "filing_date": "2024-02-14",
                    "holdings": [
                        {
                            "ticker": "AAPL",
                            "name": "APPLE INC",
                            "cusip": "037833100",
                            "shares": 10000,
                            "value": 1000000,
                            "change_pct_qoq": None,
                        }
                    ],
                }
            ]

        mock_fetch.side_effect = flaky_fetch

        with patch("institutional_tracker.CACHE_DIR", str(tmp_path)):
            with patch("institutional_tracker._read_cache", return_value=None):
                results = get_smart_money_signals(["AAPL"])

        # Should complete without raising; AAPL should still have holders
        assert len(results) == 1
        assert results[0]["ticker"] == "AAPL"
        assert results[0]["num_institutions"] > 0


# ══════════════════════════════════════════════════════════════
#  Section 7 — Helper Functions
# ══════════════════════════════════════════════════════════════


class TestHelperFunctions:
    """Tests for utility/lookup helper functions."""

    def test_get_institution_name_known_cik(self):
        name = get_institution_name("0001067983")
        assert name == "Berkshire Hathaway"

    def test_get_institution_name_unpadded_cik(self):
        """CIK without leading zeros should still resolve."""
        name = get_institution_name("1067983")
        assert name == "Berkshire Hathaway"

    def test_get_institution_name_unknown_cik(self):
        name = get_institution_name("0000000000")
        assert name is None

    def test_get_institution_cik_full_name(self):
        cik = get_institution_cik("Berkshire Hathaway")
        assert cik == "0001067983"

    def test_get_institution_cik_partial_name(self):
        cik = get_institution_cik("Berkshire")
        assert cik == "0001067983"

    def test_get_institution_cik_case_insensitive(self):
        cik = get_institution_cik("berkshire hathaway")
        assert cik == "0001067983"

    def test_get_institution_cik_not_found(self):
        cik = get_institution_cik("Nonexistent Fund XYZ")
        assert cik is None

    @patch("institutional_tracker.fetch_13f_holdings")
    def test_summarize_top_holdings_returns_sorted(self, mock_fetch):
        """summarize_top_holdings should return holdings sorted by value desc."""
        mock_fetch.return_value = [
            {
                "filing_date": "2024-02-14",
                "holdings": [
                    {"ticker": "AAPL", "name": "APPLE", "cusip": "037833100",
                     "shares": 100, "value": 5000, "change_pct_qoq": None},
                    {"ticker": "MSFT", "name": "MICROSOFT", "cusip": "594918104",
                     "shares": 200, "value": 10000, "change_pct_qoq": None},
                    {"ticker": "NVDA", "name": "NVIDIA", "cusip": "67066G104",
                     "shares": 50, "value": 3000, "change_pct_qoq": None},
                ],
            }
        ]

        result = summarize_top_holdings("0001067983", top_n=2)
        assert len(result) == 2
        assert result[0]["ticker"] == "MSFT"  # Highest value
        assert result[1]["ticker"] == "AAPL"
        assert "pct_of_portfolio" in result[0]

    @patch("institutional_tracker.fetch_13f_holdings")
    def test_summarize_top_holdings_empty_filings(self, mock_fetch):
        mock_fetch.return_value = []
        result = summarize_top_holdings("0001067983")
        assert result == []

    def test_clear_cache_nonexistent_dir(self, tmp_path):
        """Clearing cache when dir does not exist should return 0."""
        fake_dir = str(tmp_path / "nonexistent")
        with patch("institutional_tracker.CACHE_DIR", fake_dir):
            count = clear_cache()
        assert count == 0

    def test_clear_cache_removes_files(self, tmp_path):
        """Clearing cache should remove all cached files."""
        # Write a couple of fake cache files
        (tmp_path / "file1.json").write_text('{"data": 1}')
        (tmp_path / "file2.json").write_text('{"data": 2}')

        with patch("institutional_tracker.CACHE_DIR", str(tmp_path)):
            count = clear_cache()

        assert count == 2
        # Directory should still exist but be empty
        remaining = list(tmp_path.iterdir())
        assert len(remaining) == 0


# ══════════════════════════════════════════════════════════════
#  Section 8 — get_institutional_ownership (mocked)
# ══════════════════════════════════════════════════════════════


class TestGetInstitutionalOwnership:
    """Test institutional ownership cross-reference."""

    @patch("institutional_tracker.fetch_13f_holdings")
    def test_ownership_with_matching_holders(self, mock_fetch, tmp_path):
        """Institutions holding the queried ticker should appear in results."""
        mock_fetch.return_value = [
            {
                "filing_date": "2024-02-14",
                "holdings": [
                    {
                        "ticker": "AAPL",
                        "name": "APPLE INC",
                        "cusip": "037833100",
                        "shares": 50000,
                        "value": 10000000,
                        "change_pct_qoq": None,
                    },
                    {
                        "ticker": "MSFT",
                        "name": "MICROSOFT CORP",
                        "cusip": "594918104",
                        "shares": 30000,
                        "value": 6000000,
                        "change_pct_qoq": None,
                    },
                ],
            }
        ]

        institutions = [
            {"name": "Test Fund A", "cik": "0000000001"},
            {"name": "Test Fund B", "cik": "0000000002"},
        ]

        with patch("institutional_tracker.CACHE_DIR", str(tmp_path)):
            with patch("institutional_tracker._read_cache", return_value=None):
                result = get_institutional_ownership("AAPL", institutions=institutions)

        assert result["ticker"] == "AAPL"
        assert len(result["institutions"]) == 2
        assert result["total_institutional_shares"] == 100000
        assert result["crowding_score"] == 1.0

    @patch("institutional_tracker.fetch_13f_holdings")
    def test_ownership_no_holders(self, mock_fetch, tmp_path):
        """Ticker not held by any institution should have zero holders."""
        mock_fetch.return_value = [
            {
                "filing_date": "2024-02-14",
                "holdings": [
                    {
                        "ticker": "MSFT",
                        "name": "MICROSOFT CORP",
                        "cusip": "594918104",
                        "shares": 30000,
                        "value": 6000000,
                        "change_pct_qoq": None,
                    },
                ],
            }
        ]

        institutions = [
            {"name": "Test Fund A", "cik": "0000000001"},
        ]

        with patch("institutional_tracker.CACHE_DIR", str(tmp_path)):
            with patch("institutional_tracker._read_cache", return_value=None):
                result = get_institutional_ownership("RANDO", institutions=institutions)

        assert result["ticker"] == "RANDO"
        assert len(result["institutions"]) == 0
        assert result["total_institutional_shares"] == 0
        assert result["crowding_score"] == 0.0
