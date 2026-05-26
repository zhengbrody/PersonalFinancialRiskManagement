"""Tests for libs/analysis/equity_research.py.

Coverage:
- build_company_dossier shape + None-safety + data_gaps detection
- _extract_json recovers JSON from fenced / prose-wrapped output
- analyze_equity placeholder path when no LLM
- analyze_equity happy path with stubbed LLM
- analyze_equity falls back to placeholder when LLM raises / returns junk
- DeepAnalysis schema fills missing dimensions
"""

from __future__ import annotations

import json
import math

import pytest

from libs.analysis.equity_research import (
    ANALYST_SYSTEM_PROMPT,
    DeepAnalysis,
    DimensionAssessment,
    _extract_json,
    analyze_equity,
    build_company_dossier,
)

# ── build_company_dossier ───────────────────────────────────────────


def _sample_raw(ticker: str = "FAKE") -> dict:
    return {
        "ticker": ticker,
        "company_name": "Fake Co.",
        "sector": "Technology",
        "industry": "Software",
        "description": "Software company.",
        "employees": 200,
        "market_cap": 2.5e9,
        "current_price": 50.0,
        "institutional_pct": 0.80,
        "fundamentals": {
            "P/E (TTM)": 22.4,
            "ROE": 0.283,
            "Net Margin": 0.21,
            "Rev Growth": 0.18,
            "Beta": 1.2,
            "FCF": 4.5e8,
            "EPS (TTM)": 2.18,
        },
        "valuation": {
            "intrinsic_value": 60.0,
            "upside_pct": 0.20,
            "wacc": 0.088,
            "terminal_growth": 0.025,
        },
        "technicals": {
            "rsi": 55.3,
            "sma_50": 48.2,
            "sma_200": 44.1,
            "macd": 0.42,
            "macd_signal": 0.31,
        },
        "insider": {
            "net_shares_6m": -1500,
            "buy_count_6m": 1,
            "sell_count_6m": 3,
        },
        "analyst_rating": "Buy",
        "analyst_count": 14,
        "price_targets": {"consensus": 58, "high": 70, "low": 42},
        "recent_upgrades": [],
        "top_institutions": [{"holder": "BlackRock", "pct": 0.11}],
        "summary_context": "ctx",
    }


def _fetcher_ok(t, k=""):
    return _sample_raw(t)


def _fetcher_partial(t, k=""):
    raw = _sample_raw(t)
    raw.pop("technicals", None)
    raw["fundamentals"].pop("ROE", None)
    raw["current_price"] = None
    return raw


def _fetcher_explodes(t, k=""):
    raise RuntimeError("network down")


def test_build_dossier_normalises_keys():
    d = build_company_dossier("fake", fetcher=_fetcher_ok)
    assert d["ticker"] == "FAKE"
    expected = {
        "ticker",
        "as_of",
        "profile",
        "market",
        "fundamentals",
        "valuation",
        "technicals",
        "ratings",
        "ownership",
        "insider",
        "data_gaps_detected",
    }
    assert expected.issubset(set(d.keys()))
    assert d["fundamentals"]["roe"] == 0.283
    assert d["fundamentals"]["revenue_growth_yoy"] == 0.18
    assert d["technicals"]["rsi_14"] == 55.3
    assert d["market"]["current_price"] == 50.0
    # No required gap when full data is present.
    assert d["data_gaps_detected"] == []


def test_build_dossier_detects_gaps_for_partial_input():
    d = build_company_dossier("fake", fetcher=_fetcher_partial)
    gaps = set(d["data_gaps_detected"])
    # Some sentinel fields should be flagged when missing.
    assert "fundamentals.roe" in gaps
    assert "technicals.rsi_14" in gaps
    assert "market.current_price" in gaps


def test_build_dossier_falls_back_to_empty_on_fetch_error():
    d = build_company_dossier("X", fetcher=_fetcher_explodes)
    assert d["ticker"] == "X"
    # All sections present but mostly None.
    assert d["fundamentals"]["pe_ttm"] is None
    assert d["market"]["current_price"] is None
    # Gaps detected for every sentinel field.
    assert len(d["data_gaps_detected"]) >= 6


def test_build_dossier_rejects_empty_ticker():
    with pytest.raises(ValueError):
        build_company_dossier("", fetcher=_fetcher_ok)


def test_build_dossier_strips_nan_and_inf():
    """yfinance occasionally returns NaN / Inf. The dossier must never
    leak those into the LLM payload."""

    def _nan_fetcher(t, k=""):
        raw = _sample_raw(t)
        raw["current_price"] = math.nan
        raw["fundamentals"]["ROE"] = math.inf
        return raw

    d = build_company_dossier("fake", fetcher=_nan_fetcher)
    assert d["market"]["current_price"] is None
    assert d["fundamentals"]["roe"] is None


# ── _extract_json ───────────────────────────────────────────────────


def test_extract_json_strict_parse():
    raw = '{"verdict": {"rating": "BUY"}}'
    out = _extract_json(raw)
    assert out == {"verdict": {"rating": "BUY"}}


def test_extract_json_strips_code_fence():
    raw = '```json\n{"k": 1}\n```'
    assert _extract_json(raw) == {"k": 1}


def test_extract_json_finds_largest_object_in_prose():
    raw = 'Sure, here you go: {"k": 1, "v": 2} ok?'
    assert _extract_json(raw) == {"k": 1, "v": 2}


def test_extract_json_returns_none_for_junk():
    assert _extract_json("hello world") is None
    assert _extract_json("") is None


# ── analyze_equity ──────────────────────────────────────────────────


def test_analyze_equity_returns_placeholder_when_no_llm():
    d = build_company_dossier("FAKE", fetcher=_fetcher_ok)
    a = analyze_equity(d, llm_callable=None)
    assert a.ticker == "FAKE"
    assert a.verdict.rating == "HOLD"
    assert a.verdict.confidence == "low"
    # 5 dimensions always present.
    assert set(a.dimensions.keys()) == {
        "quality",
        "fundamentals",
        "growth",
        "technicals",
        "sentiment",
    }


def _good_llm_response(ticker: str) -> str:
    payload = {
        "ticker": ticker,
        "as_of": "2026-05-26T12:00:00+00:00",
        "verdict": {
            "rating": "BUY",
            "confidence": "high",
            "target_weight_pct_band": "2-4%",
            "thesis_one_liner": "Wide-moat compounder at fair multiple.",
        },
        "dimensions": {
            "quality": {
                "score_0_100": 82,
                "key_points": ["Strong brand", "Recurring revenue"],
                "evidence": ["profile.sector=Technology"],
            },
            "fundamentals": {
                "score_0_100": 75,
                "key_points": ["ROE 28% per fundamentals.roe"],
                "evidence": ["fundamentals.roe=0.283"],
            },
            "growth": {
                "score_0_100": 80,
                "key_points": ["Rev +18% Y/Y"],
                "evidence": ["fundamentals.revenue_growth_yoy=0.18"],
            },
            "technicals": {
                "score_0_100": 65,
                "key_points": ["Above SMA200"],
                "evidence": ["technicals.sma_200=44.1"],
            },
            "sentiment": {
                "score_0_100": 70,
                "key_points": ["Analyst consensus Buy"],
                "evidence": ["ratings.analyst_rating=Buy"],
            },
        },
        "catalysts_90d": ["Q2 earnings", "Annual product event"],
        "risks": ["Concentration in one product line"],
        "data_gaps": [],
        "would_change_mind": [
            "Operating margin compresses >300bps",
            "Insider net selling accelerates",
            "Forward guidance lowered",
        ],
    }
    return json.dumps(payload)


def test_analyze_equity_happy_path():
    d = build_company_dossier("FAKE", fetcher=_fetcher_ok)
    captured: dict = {}

    def _llm(*, prompt, system, max_tokens, temperature):
        captured["system"] = system
        captured["prompt"] = prompt
        captured["max_tokens"] = max_tokens
        captured["temperature"] = temperature
        return _good_llm_response("FAKE")

    a = analyze_equity(d, llm_callable=_llm)
    assert a.ticker == "FAKE"
    assert a.verdict.rating == "BUY"
    assert a.verdict.confidence == "high"
    assert a.dimensions["fundamentals"].score_0_100 == 75
    # The system prompt we passed in MUST be the senior-analyst one,
    # not some other prompt accidentally leaking through.
    assert ANALYST_SYSTEM_PROMPT in captured["system"]
    # And the dossier JSON should appear in the user prompt.
    assert "FAKE" in captured["prompt"]


def test_analyze_equity_falls_back_when_llm_returns_junk():
    d = build_company_dossier("FAKE", fetcher=_fetcher_ok)

    def _bad_llm(**_kw):
        return "I cannot help with that."

    a = analyze_equity(d, llm_callable=_bad_llm)
    # Placeholder uses HOLD/low.
    assert a.verdict.rating == "HOLD"
    assert a.verdict.confidence == "low"


def test_analyze_equity_falls_back_when_llm_raises():
    d = build_company_dossier("FAKE", fetcher=_fetcher_ok)

    def _explode_llm(**_kw):
        raise TimeoutError("provider down")

    a = analyze_equity(d, llm_callable=_explode_llm)
    assert a.verdict.rating == "HOLD"


def test_analyze_equity_merges_data_gaps_from_dossier():
    d = build_company_dossier("FAKE", fetcher=_fetcher_partial)

    def _llm(**_kw):
        return _good_llm_response("FAKE")

    a = analyze_equity(d, llm_callable=_llm)
    # The dossier already detected gaps; they must appear in
    # a.data_gaps even though the LLM returned an empty list.
    assert any("technicals.rsi_14" in g for g in a.data_gaps)


# ── DeepAnalysis schema ─────────────────────────────────────────────


def test_deep_analysis_fills_missing_dimensions():
    """If the LLM returns only three dimensions, the model fills the
    rest with placeholders so the UI grid stays at 5."""
    payload = {
        "ticker": "FAKE",
        "as_of": "2026-05-26",
        "verdict": {
            "rating": "HOLD",
            "confidence": "medium",
            "target_weight_pct_band": "",
            "thesis_one_liner": "",
        },
        "dimensions": {
            "quality": {"score_0_100": 60, "key_points": ["x"], "evidence": []},
        },
    }
    a = DeepAnalysis(**payload)
    assert set(a.dimensions.keys()) == {
        "quality",
        "fundamentals",
        "growth",
        "technicals",
        "sentiment",
    }
    # Filled-in dimensions get a 50 default + insufficient-data note.
    assert a.dimensions["technicals"].score_0_100 == 50
    assert "Insufficient" in a.dimensions["technicals"].evidence[0]


def test_dimension_assessment_caps_long_lists():
    dim = DimensionAssessment(
        score_0_100=80,
        key_points=["item " + str(i) for i in range(20)],
        evidence=["e" + str(i) for i in range(20)],
    )
    assert len(dim.key_points) == 8
    assert len(dim.evidence) == 8


def test_deep_analysis_upper_cases_ticker():
    a = DeepAnalysis(
        ticker="aapl",
        verdict={
            "rating": "HOLD",
            "confidence": "low",
            "target_weight_pct_band": "",
            "thesis_one_liner": "",
        },
        dimensions={},
    )
    assert a.ticker == "AAPL"


# ── system prompt sanity ────────────────────────────────────────────


def test_system_prompt_enforces_evidence_and_no_fabrication():
    """The prompt is load-bearing — if any of these guardrails get
    accidentally edited away, the analyst will hallucinate. Pin them."""
    lower = ANALYST_SYSTEM_PROMPT.lower()
    assert "do not invent" in lower
    assert "cite" in lower
    assert "strict json" in lower
    # Six-dimension framework must be intact.
    for label in (
        "business quality",
        "fundamentals",
        "growth",
        "technicals",
        "sentiment",
        "verdict",
    ):
        assert label in lower
    # Output schema block must be present.
    assert "output schema" in lower
