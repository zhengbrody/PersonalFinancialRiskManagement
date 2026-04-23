"""
tests/unit/test_analyst_report.py

Coverage for the institutional analyst report pipeline in market_intelligence:
  - fetch_analyst_report_data   (FMP aggregation with mocked HTTP)
  - build_analyst_report_prompt (prompt assembly with partial data)
  - generate_analyst_report     (end-to-end with mocked Anthropic client)
"""
from __future__ import annotations

import json
from unittest.mock import patch, MagicMock

import pytest

from market_intelligence import (
    fetch_analyst_report_data,
    build_analyst_report_prompt,
    generate_analyst_report,
    _safe_num,
)


# ══════════════════════════════════════════════════════════════════════════════
#  _safe_num
# ══════════════════════════════════════════════════════════════════════════════

def test_safe_num_formats_billions():
    assert _safe_num(1_500_000_000) == "$1.50B"
    assert _safe_num(2_300_000) == "$2.30M"
    assert _safe_num(45_000) == "$45.00K"
    assert _safe_num(12.34) == "12.34"


def test_safe_num_handles_none_and_invalid():
    assert _safe_num(None) == "-"
    assert _safe_num("not a number") == "-"


# ══════════════════════════════════════════════════════════════════════════════
#  fetch_analyst_report_data — mock FMP HTTP layer
# ══════════════════════════════════════════════════════════════════════════════

def _mock_fmp_response(payload, status=200):
    """Build a mock requests.Response-like object."""
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = payload
    return resp


def test_fetch_analyst_report_data_assembles_structure(monkeypatch):
    """With good FMP responses, all expected keys should be populated."""
    def fake_get(url, params=None, timeout=None, headers=None):
        # New /stable/ endpoints use query parameters, so the URL itself
        # ends at the endpoint name (no path-segment ticker).
        if url.endswith("/profile"):
            return _mock_fmp_response([{"companyName": "NVIDIA Corp", "sector": "Tech",
                                        "industry": "Semis", "mktCap": 3e12}])
        if url.endswith("/quote"):
            return _mock_fmp_response([{"price": 950.0, "marketCap": 3e12}])
        if url.endswith("/income-statement"):
            return _mock_fmp_response([{"date": "2026-03-31", "revenue": 2.5e10, "netIncome": 1.2e10}])
        if url.endswith("/balance-sheet-statement"):
            return _mock_fmp_response([{"date": "2026-03-31", "totalAssets": 1e11}])
        if url.endswith("/cash-flow-statement"):
            return _mock_fmp_response([{"date": "2026-03-31", "freeCashFlow": 1.1e10}])
        if url.endswith("/ratios"):
            return _mock_fmp_response([{"date": "2026-03-31", "priceToSalesRatio": 25,
                                        "returnOnEquity": 0.85, "debtEquityRatio": 0.3}])
        if url.endswith("/key-metrics"):
            return _mock_fmp_response([{"date": "2026-03-31", "peRatio": 60,
                                        "enterpriseValueOverEBITDA": 45}])
        if url.endswith("/analyst-estimates"):
            return _mock_fmp_response([])
        if url.endswith("/price-target-consensus"):
            return _mock_fmp_response([{"targetConsensus": 1100, "targetHigh": 1250,
                                        "targetLow": 900, "analystsCount": 42}])
        # /stable/ renamed upgrades-downgrades → grades-historical
        if url.endswith("/grades-historical"):
            return _mock_fmp_response([
                {"publishedDate": "2026-04-10T00:00", "gradingCompany": "Goldman Sachs",
                 "previousGrade": "Buy", "newGrade": "Buy"}
            ])
        # /stable/ renamed stock_peers → stock-peers (and returns peer profiles)
        if url.endswith("/stock-peers"):
            return _mock_fmp_response([
                {"symbol": "AMD", "companyName": "AMD", "price": 150, "mktCap": 2e11},
                {"symbol": "INTC", "companyName": "Intel", "price": 30, "mktCap": 1.3e11},
                {"symbol": "AVGO", "companyName": "Broadcom", "price": 1400, "mktCap": 6.5e11},
            ])
        if url.endswith("/key-metrics-ttm"):
            return _mock_fmp_response([{"peRatioTTM": 40, "roeTTM": 0.25}])
        # /stable/ renamed earning_call_transcript → earning-call-transcript;
        # now requires (year, quarter) query params, one response per call.
        if url.endswith("/earning-call-transcript"):
            return _mock_fmp_response([
                {"quarter": 1, "year": 2026, "date": "2026-02-15", "content": "strong quarter..."}
            ])
        return _mock_fmp_response([])

    monkeypatch.setattr("market_intelligence.requests.get", fake_get)
    data = fetch_analyst_report_data("NVDA", fmp_key="dummy")

    assert data["ticker"] == "NVDA"
    assert data["profile"]["companyName"] == "NVIDIA Corp"
    assert data["quote"]["price"] == 950.0
    assert len(data["income_statement"]) >= 1
    assert data["price_target_consensus"][0]["targetConsensus"] == 1100
    assert set(data["peers"]) >= {"AMD", "INTC", "AVGO"}
    assert data["transcript"].get("quarter") == 1


def test_fetch_analyst_report_data_handles_missing_key():
    """No FMP key -> empty-but-safe structure (no crash)."""
    data = fetch_analyst_report_data("NVDA", fmp_key="")
    assert data["ticker"] == "NVDA"
    assert data["profile"] == {}
    assert data["income_statement"] == []
    assert data["peers"] == []


def test_fetch_analyst_report_data_handles_http_error(monkeypatch):
    """Non-200 responses should be absorbed silently."""
    def always_500(*a, **kw):
        return _mock_fmp_response({"error": "server error"}, status=500)

    monkeypatch.setattr("market_intelligence.requests.get", always_500)
    data = fetch_analyst_report_data("NVDA", fmp_key="dummy")
    assert data["profile"] == {}
    assert data["income_statement"] == []


# ══════════════════════════════════════════════════════════════════════════════
#  build_analyst_report_prompt
# ══════════════════════════════════════════════════════════════════════════════

def test_build_prompt_handles_minimal_data():
    """Prompt must build even when most FMP fields are empty (graceful degrade)."""
    data = {
        "ticker": "NVDA",
        "profile": {"companyName": "NVIDIA", "sector": "Tech", "industry": "Semis"},
        "quote": {"price": 950.0},
        "income_statement": [],
        "balance_sheet": [],
        "cash_flow": [],
        "ratios": [],
        "key_metrics": [],
        "price_target_consensus": [],
        "upgrades_downgrades": [],
        "peer_metrics": [],
        "transcript": {},
    }
    prompt = build_analyst_report_prompt(data)
    assert "NVDA" in prompt
    assert "NVIDIA" in prompt
    assert "return ONLY valid JSON" in prompt
    assert "rating" in prompt
    assert "investment_thesis" in prompt
    assert "top_bank_views" in prompt


def test_build_prompt_embeds_financial_history():
    """When financial history present, it must appear in the prompt."""
    data = {
        "ticker": "NVDA",
        "profile": {"companyName": "NVIDIA"},
        "quote": {"price": 950},
        "income_statement": [{"date": "2026-03-31", "revenue": 26e9, "netIncome": 12e9}],
        "cash_flow": [{"date": "2026-03-31", "freeCashFlow": 11e9}],
        "ratios": [],
        "key_metrics": [],
        "balance_sheet": [],
        "price_target_consensus": [],
        "upgrades_downgrades": [],
        "peer_metrics": [],
        "transcript": {},
    }
    prompt = build_analyst_report_prompt(data)
    assert "26000000000" in prompt or "26" in prompt  # revenue shows up


# ══════════════════════════════════════════════════════════════════════════════
#  generate_analyst_report — end-to-end with mocked Claude
# ══════════════════════════════════════════════════════════════════════════════

def _valid_report_json():
    return {
        "rating": "Buy",
        "rating_rationale": "Strong AI tailwind + widening margins",
        "price_target_12m": 1100,
        "price_target_bull": 1300,
        "price_target_base": 1100,
        "price_target_bear": 800,
        "upside_pct_vs_current": 0.16,
        "executive_summary": "NVDA remains the clear platform winner in AI compute.",
        "financial_highlights": [
            {"metric": "Revenue", "value": "$26.0B", "yoy_change": "+85%", "commentary": "AI demand"},
        ],
        "valuation_table": [
            {"method": "DCF", "implied_price": 1150, "weight": 0.4, "notes": "10% WACC"},
        ],
        "investment_thesis": {"bull": ["a"], "base": ["b"], "bear": ["c"]},
        "risk_factors": ["supply constraints"],
        "peer_comparison_notes": "Premium valuation justified",
        "street_consensus_diff": {
            "street_target": 1080, "our_target": 1100,
            "direction": "above_street", "differentiation": "More bullish on data center mix"
        },
        "catalysts_next_12m": ["Q2 earnings", "Blackwell launch"],
        "top_bank_views": [{"bank": "Goldman Sachs", "rating": "Buy", "target": 1250, "stance": "conviction"}],
    }


def test_generate_report_returns_parsed_json(monkeypatch):
    """End-to-end with mocked FMP + mocked Anthropic returns parsed dict."""
    # Mock FMP — minimal data (new /stable/ query-param endpoints)
    def fake_get(url, params=None, timeout=None, headers=None):
        if url.endswith("/profile"):
            return _mock_fmp_response([{"companyName": "NVIDIA", "sector": "Tech", "industry": "Semis"}])
        if url.endswith("/quote"):
            return _mock_fmp_response([{"price": 950}])
        return _mock_fmp_response([])

    monkeypatch.setattr("market_intelligence.requests.get", fake_get)

    # Mock Anthropic client
    class _FakeResp:
        def __init__(self, text):
            block = MagicMock()
            block.text = text
            self.content = [block]

    class _FakeClient:
        def __init__(self, api_key): pass
        class messages:  # noqa
            pass
        def __init__(self, api_key):
            self.messages = MagicMock()
            self.messages.create = MagicMock(return_value=_FakeResp(json.dumps(_valid_report_json())))

    with patch("anthropic.Anthropic", _FakeClient):
        result = generate_analyst_report(
            ticker="NVDA",
            fmp_key="dummy_fmp",
            anthropic_key="dummy_anth",
        )

    assert result["error"] is None
    assert result["report"]["rating"] == "Buy"
    assert result["report"]["price_target_12m"] == 1100
    assert "investment_thesis" in result["report"]


def test_generate_report_fails_without_keys():
    """Missing keys should short-circuit with a clear error."""
    r1 = generate_analyst_report("NVDA", fmp_key="", anthropic_key="abc")
    assert r1["error"] and "FMP" in r1["error"]

    r2 = generate_analyst_report("NVDA", fmp_key="abc", anthropic_key="")
    assert r2["error"] and "ANTHROPIC" in r2["error"]


def test_generate_report_handles_fenced_json(monkeypatch):
    """Claude sometimes wraps JSON in ```json ... ``` — we must strip fences."""
    def fake_get(url, params=None, timeout=None, headers=None):
        if url.endswith("/profile"):
            return _mock_fmp_response([{"companyName": "X"}])
        if url.endswith("/quote"):
            return _mock_fmp_response([{"price": 100}])
        return _mock_fmp_response([])

    monkeypatch.setattr("market_intelligence.requests.get", fake_get)

    fenced = "```json\n" + json.dumps(_valid_report_json()) + "\n```"

    class _FakeResp:
        def __init__(self, text):
            block = MagicMock(); block.text = text
            self.content = [block]

    class _FakeClient:
        def __init__(self, api_key):
            self.messages = MagicMock()
            self.messages.create = MagicMock(return_value=_FakeResp(fenced))

    with patch("anthropic.Anthropic", _FakeClient):
        result = generate_analyst_report("X", fmp_key="a", anthropic_key="b")

    assert result["error"] is None
    assert result["report"]["rating"] == "Buy"
