"""Tests for libs/analysis/portfolio_research.py.

Coverage:
- build_portfolio_dossier: shape, HHI / top-N / sector rollup math,
  NaN sanitisation, sentinel-gap detection.
- analyze_portfolio: placeholder when no LLM, happy path, fallback
  on parse failure / schema failure / LLM raise.
- PortfolioDeepAnalysis schema fills five required dimensions.
- System prompt enforces missing-data professional protocol + JSON-
  only output + language matching (key directives we want pinned).
"""

from __future__ import annotations

import json
import math

import pytest

from libs.analysis.portfolio_research import (
    PORTFOLIO_ANALYST_PROMPT,
    PortfolioDeepAnalysis,
    PortfolioVerdict,
    _extract_json,
    _hhi,
    _sector_rollup,
    _top_n_positions,
    analyze_portfolio,
    build_portfolio_dossier,
)

# ── pure helpers ────────────────────────────────────────────────────


def test_hhi_for_perfectly_concentrated():
    """All weight on one ticker → HHI = 1.0."""
    assert _hhi({"NVDA": 1.0}) == pytest.approx(1.0)


def test_hhi_for_evenly_diversified():
    """Five equal positions → HHI = 0.20 (1/n)."""
    weights = {f"X{i}": 0.20 for i in range(5)}
    assert _hhi(weights) == pytest.approx(0.20, abs=1e-6)


def test_hhi_returns_none_for_empty_inputs():
    assert _hhi(None) is None
    assert _hhi({}) is None
    assert _hhi({"X": 0.0}) is None  # all zero → undefined


def test_hhi_strips_nan_weights():
    """yfinance occasionally returns NaN — must not poison HHI."""
    weights = {"A": 0.5, "B": float("nan"), "C": 0.5}
    # Effective universe is just A + C → 0.5^2 + 0.5^2 = 0.5
    assert _hhi(weights) == pytest.approx(0.5)


def test_top_n_positions_orders_by_weight_desc():
    weights = {"SPY": 0.1, "NVDA": 0.4, "AAPL": 0.3, "MSFT": 0.2}
    out = _top_n_positions(weights, n=3)
    assert [p["ticker"] for p in out] == ["NVDA", "AAPL", "MSFT"]
    assert out[0]["weight"] == 0.4


def test_top_n_positions_skips_zero_and_nan():
    weights = {"A": 0.5, "B": 0.0, "C": float("inf"), "D": 0.3}
    out = _top_n_positions(weights, n=5)
    tickers = [p["ticker"] for p in out]
    assert tickers == ["A", "D"]


def test_top_n_positions_handles_empty():
    assert _top_n_positions(None) == []
    assert _top_n_positions({}) == []


def test_sector_rollup_aggregates_correctly():
    weights = {"NVDA": 0.3, "AAPL": 0.2, "TSLA": 0.1, "SPY": 0.4}
    sector_map = {"NVDA": "Tech", "AAPL": "Tech", "TSLA": "Auto", "SPY": "Index"}
    out = _sector_rollup(weights, sector_map)
    assert out["Tech"] == pytest.approx(0.5)
    assert out["Auto"] == pytest.approx(0.1)
    assert out["Index"] == pytest.approx(0.4)


def test_sector_rollup_fallback_unknown():
    weights = {"WEIRD": 0.5, "AAPL": 0.5}
    sector_map = {"AAPL": "Tech"}
    out = _sector_rollup(weights, sector_map)
    assert out["Unknown"] == pytest.approx(0.5)


def test_sector_rollup_handles_empty():
    assert _sector_rollup(None, None) == {}
    assert _sector_rollup({"A": 0.5}, None) == {}


# ── build_portfolio_dossier ─────────────────────────────────────────


@pytest.fixture
def sample_meta():
    return {
        "portfolio_name": "My Portfolio",
        "total_long": 100_000,
        "cash_balance": 25_000,
        "margin_loan": 15_000,
        "net_equity": 110_000,
        "contributed_capital": 90_000,
        "return_on_capital_pct": 0.22,
        "leverage": 0.91,
        "sector_map": {
            "NVDA": "Tech",
            "AAPL": "Tech",
            "MSFT": "Tech",
            "TSLA": "Auto",
        },
        "missing": [],
    }


@pytest.fixture
def sample_weights():
    return {"NVDA": 0.30, "AAPL": 0.25, "MSFT": 0.20, "TSLA": 0.15, "GLD": 0.10}


@pytest.fixture
def sample_report():
    class _Report:
        annual_return = 0.18
        annual_volatility = 0.22
        sharpe_ratio = 0.82
        max_drawdown = -0.18
        var_95 = -0.035
        var_99 = -0.052
        cvar_95 = -0.041
        stress_loss = -0.18
        beta = 1.15
        margin_call_info = {
            "has_margin": True,
            "leverage": 0.91,
            "distance_to_call_pct": 0.42,
        }

    return _Report()


def test_dossier_shape(sample_weights, sample_meta, sample_report):
    d = build_portfolio_dossier(weights=sample_weights, meta=sample_meta, report=sample_report)
    assert "as_of" in d
    assert d["portfolio_name"] == "My Portfolio"
    assert d["capital"]["net_equity"] == 110_000
    assert d["capital"]["leverage"] == 0.91
    assert d["concentration"]["ticker_count"] == 5
    assert d["concentration"]["top_sector_name"] == "Tech"
    # Top sector weight should be NVDA + AAPL + MSFT = 0.75
    assert d["concentration"]["top_sector_weight"] == pytest.approx(0.75, abs=1e-6)
    # HHI: 0.30^2 + 0.25^2 + 0.20^2 + 0.15^2 + 0.10^2
    #    = 0.09 + 0.0625 + 0.04 + 0.0225 + 0.01 = 0.225
    assert d["concentration"]["hhi"] == pytest.approx(0.225, abs=1e-3)
    # Top 5 positions all present
    assert len(d["top_positions"]) == 5
    # Risk metrics pulled through
    assert d["risk_metrics"]["var_95"] == -0.035
    assert d["risk_metrics"]["sharpe_ratio"] == 0.82
    # Margin info preserved
    assert d["margin"]["distance_to_call_pct"] == 0.42
    # No gaps when everything is populated
    assert d["data_gaps_detected"] == []


def test_dossier_detects_gaps_when_data_missing():
    """An empty report + meta should surface every sentinel as a gap."""
    d = build_portfolio_dossier(
        weights={"SPY": 1.0},
        meta={},
        report=None,
    )
    gaps = set(d["data_gaps_detected"])
    assert "capital.net_equity" in gaps
    assert "risk_metrics.annual_volatility" in gaps
    assert "risk_metrics.var_95" in gaps


def test_dossier_handles_nan_inputs(sample_meta):
    """NaN / Inf in any numeric field must NOT leak into the dossier."""
    meta = dict(sample_meta)
    meta["leverage"] = math.inf
    meta["cash_balance"] = math.nan
    d = build_portfolio_dossier(weights={"A": 1.0}, meta=meta, report=None)
    assert d["capital"]["leverage"] is None
    assert d["capital"]["cash_balance"] is None


def test_dossier_includes_risk_preference():
    d = build_portfolio_dossier(weights={"A": 1.0}, meta={}, risk_preference=4)
    assert d["user_risk_preference"] == 4


def test_dossier_default_sources_handle_none_weights():
    """Caller may have an empty portfolio mid-onboarding; must not raise."""
    d = build_portfolio_dossier(weights=None, meta=None, report=None)
    assert d["top_positions"] == []
    assert d["concentration"]["hhi"] is None


# ── analyze_portfolio ──────────────────────────────────────────────


def test_analyze_returns_placeholder_when_no_llm(sample_weights, sample_meta):
    d = build_portfolio_dossier(weights=sample_weights, meta=sample_meta)
    a = analyze_portfolio(d, llm_callable=None)
    assert a.verdict.rating == "REBALANCE"
    assert a.verdict.confidence == "low"
    assert set(a.dimensions.keys()) == {
        "concentration",
        "risk_budget",
        "margin_capital",
        "return_quality",
        "catalysts",
    }
    assert len(a.verdict.top_actions) == 3


def _good_response() -> str:
    return json.dumps(
        {
            "as_of": "2026-05-26T12:00:00+00:00",
            "verdict": {
                "rating": "TRIM_RISK",
                "confidence": "high",
                "thesis_one_liner": "Tech concentration > 65% — trim top names first.",
                "top_actions": [
                    "Trim NVDA 30% → 22%",
                    "Add 5% defensive (XLP)",
                    "Reduce gross leverage from 1.4x to 1.2x",
                ],
            },
            "dimensions": {
                "concentration": {
                    "score_0_100": 35,
                    "key_points": ["Top-3 weight 75% per concentration.top3_weight"],
                    "evidence": ["concentration.hhi=0.235"],
                },
                "risk_budget": {
                    "score_0_100": 60,
                    "key_points": ["Vol 22% per risk_metrics.annual_volatility"],
                    "evidence": ["risk_metrics.annual_volatility=0.22"],
                },
                "margin_capital": {
                    "score_0_100": 70,
                    "key_points": ["Leverage 0.91x per capital.leverage"],
                    "evidence": ["capital.leverage=0.91"],
                },
                "return_quality": {
                    "score_0_100": 80,
                    "key_points": ["Sharpe 0.82 per risk_metrics.sharpe_ratio"],
                    "evidence": ["risk_metrics.sharpe_ratio=0.82"],
                },
                "catalysts": {
                    "score_0_100": 65,
                    "key_points": ["Earnings season ahead — typical sector pattern"],
                    "evidence": ["sector_exposure.Tech=0.65"],
                },
            },
            "risks": ["Single-sector dominance leaves no hedge in tech drawdown"],
            "data_gaps": [],
        }
    )


def test_analyze_happy_path_validates(sample_weights, sample_meta, sample_report):
    d = build_portfolio_dossier(weights=sample_weights, meta=sample_meta, report=sample_report)
    captured: dict = {}

    def _llm(*, prompt, system, max_tokens, temperature):
        captured["system"] = system
        captured["prompt"] = prompt
        return _good_response()

    a = analyze_portfolio(d, llm_callable=_llm)
    assert a.verdict.rating == "TRIM_RISK"
    assert a.verdict.confidence == "high"
    assert a.dimensions["concentration"].score_0_100 == 35
    # The PORTFOLIO prompt (not the equity prompt) must have been used.
    assert PORTFOLIO_ANALYST_PROMPT in captured["system"]
    # The dossier must have been passed in the user prompt.
    assert "concentration" in captured["prompt"]


def test_analyze_falls_back_when_llm_returns_junk(sample_weights, sample_meta):
    d = build_portfolio_dossier(weights=sample_weights, meta=sample_meta)

    def _bad(**_kw):
        return "I cannot help."

    a = analyze_portfolio(d, llm_callable=_bad)
    assert a.verdict.rating == "REBALANCE"
    assert a.verdict.confidence == "low"


def test_analyze_falls_back_when_llm_raises(sample_weights, sample_meta):
    d = build_portfolio_dossier(weights=sample_weights, meta=sample_meta)

    def _explode(**_kw):
        raise TimeoutError("provider down")

    a = analyze_portfolio(d, llm_callable=_explode)
    assert a.verdict.rating == "REBALANCE"


def test_analyze_merges_detected_data_gaps(sample_weights):
    """Even if the LLM returns data_gaps=[], the dossier-detected
    gaps must show up in the final analysis output."""
    d = build_portfolio_dossier(weights=sample_weights, meta={}, report=None)
    assert d["data_gaps_detected"]  # sanity

    def _llm(**_kw):
        return _good_response()  # returns data_gaps=[]

    a = analyze_portfolio(d, llm_callable=_llm)
    # The dossier-detected ones must be merged in.
    assert any("capital." in g for g in a.data_gaps)


# ── schema fills missing dimensions ────────────────────────────────


def test_portfolio_analysis_fills_five_dimensions_even_when_llm_returns_two():
    payload = {
        "as_of": "2026-05-26",
        "verdict": {
            "rating": "REBALANCE",
            "confidence": "medium",
            "thesis_one_liner": "Test",
            "top_actions": ["a", "b", "c"],
        },
        "dimensions": {
            "concentration": {"score_0_100": 60, "key_points": ["x"], "evidence": []},
            "risk_budget": {"score_0_100": 50, "key_points": ["y"], "evidence": []},
        },
    }
    a = PortfolioDeepAnalysis(**payload)
    assert set(a.dimensions.keys()) == {
        "concentration",
        "risk_budget",
        "margin_capital",
        "return_quality",
        "catalysts",
    }
    # Filled-in dimensions get a 50 default + "insufficient data" evidence.
    assert "Insufficient" in a.dimensions["catalysts"].evidence[0]


def test_top_actions_always_three():
    """The dashboard slot expects three actions; over-eager LLMs
    sometimes return 5 and we should trim, sometimes return 1 and
    we should pad."""
    v = PortfolioVerdict(
        rating="REBALANCE",
        confidence="medium",
        thesis_one_liner="",
        top_actions=["a", "b", "c", "d", "e"],
    )
    assert len(v.top_actions) == 3
    assert v.top_actions[:3] == ["a", "b", "c"]

    v2 = PortfolioVerdict(
        rating="REBALANCE",
        confidence="medium",
        thesis_one_liner="",
        top_actions=["only one"],
    )
    assert len(v2.top_actions) == 3
    assert v2.top_actions[0] == "only one"


# ── system prompt guardrails ────────────────────────────────────────


def test_portfolio_prompt_pins_missing_data_protocol():
    """The directive 'never blank a section' is load-bearing for the
    'professional analysis even with missing data' product invariant.
    If a future edit weakens it, the LLM will start saying 'insufficient
    data' again and erode user trust."""
    p = PORTFOLIO_ANALYST_PROMPT.lower()
    assert "never blank" in p or "never silence" in p or "never blank a section" in p
    assert "anchoring to" in p or "anchor" in p
    assert "missing-data protocol" in p


def test_portfolio_prompt_pins_no_fabrication_of_numbers():
    p = PORTFOLIO_ANALYST_PROMPT.lower()
    assert "do not invent" in p or "never invent" in p


def test_portfolio_prompt_pins_language_match():
    p = PORTFOLIO_ANALYST_PROMPT.lower()
    assert "language" in p
    assert "user" in p
    assert "default to english" in p


def test_portfolio_prompt_pins_strict_json():
    assert "STRICT JSON" in PORTFOLIO_ANALYST_PROMPT
    assert "no markdown" in PORTFOLIO_ANALYST_PROMPT.lower()


# ── _extract_json (smoke; full coverage lives in test_equity_research) ──


def test_extract_json_handles_fences_and_prose():
    assert _extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert _extract_json('hello: {"b": 2}') == {"b": 2}
    assert _extract_json("nope") is None
