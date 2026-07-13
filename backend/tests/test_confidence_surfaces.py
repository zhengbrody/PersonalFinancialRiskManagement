"""End-to-end proof of rule #6: low-quality data cannot produce a high-confidence
conclusion on ANY of the four surfaces (score, risk report, research, Copilot).

These exercise each surface's real builder/gate — not just the shared helper —
so a regression that bypasses the enforcement on one surface is caught."""

from __future__ import annotations

import types

import pandas as pd

import backend.app.schemas.research as R
from backend.app.api.v1 import risk as risk_api
from backend.app.schemas.confidence import DataConfidence
from backend.app.schemas.copilot2 import EvidenceItem
from backend.app.schemas.risk_explain import RiskExplainInput
from backend.app.services import copilot_router, research_factpack, risk_explain


def _metrics(**kw):
    base = dict(
        data_coverage=1.0,
        observations=250,
        data_quality=0.9,
        dropped_tickers=[],
    )
    base.update(kw)
    return types.SimpleNamespace(**base)


def _frame(days: int) -> pd.DataFrame:
    idx = pd.date_range("2025-01-01", periods=days, freq="D")
    return pd.DataFrame({"SPY": range(days)}, index=idx)


# ── SCORE ─────────────────────────────────────────────────────────────────────
def test_score_confidence_low_data_is_low_not_high():
    # 15 observations, 40% price coverage, one dropped ticker → thin.
    dc = risk_api._score_data_confidence(
        _metrics(data_coverage=0.4, observations=15, data_quality=0.25, dropped_tickers=["XYZ"]),
        {"by_ticker": {"AAPL": "yfinance"}, "missing": []},
        _frame(15),
        reason_codes=[],
    )
    assert dc.label == "low"
    assert dc.directional_allowed is False  # critical coverage < 40%
    assert dc.conviction_cap == "none"


def test_score_confidence_full_data_is_high():
    dc = risk_api._score_data_confidence(
        _metrics(),
        {"by_ticker": {"AAPL": "massive", "MSFT": "massive"}, "missing": []},
        _frame(250),
        reason_codes=[],
    )
    assert dc.label == "high"
    assert dc.directional_allowed is True


# ── RISK REPORT ───────────────────────────────────────────────────────────────
def test_report_confidence_missing_benchmark_and_short_history():
    dc = risk_api._report_data_confidence(
        {"by_ticker": {"AAPL": "yfinance"}, "missing": ["MSFT", "GOOG"]},
        _frame(20),
        notes=["Benchmark data was unavailable — the stress test assumed market beta (1.0)."],
    )
    assert dc.label in ("low", "medium")
    assert dc.conviction_cap != "high"  # thin history + missing benchmark caps it
    assert any(r.code == "missing_benchmark_beta" for r in dc.reason_codes)


# ── RESEARCH VERDICT ──────────────────────────────────────────────────────────
def _factpack(critical_cov: float) -> R.FactPack:
    return R.FactPack(
        ticker="TST",
        name="Test Co",
        data_quality=R.DataQuality(
            coverage=critical_cov,
            sources=[
                R.SourceRef(field="profile", source="fmp", coverage=critical_cov),
                R.SourceRef(field="fundamentals", source="fmp", coverage=critical_cov),
            ],
            warnings=[],
        ),
    )


def test_research_verdict_low_critical_gives_no_directional_rating():
    v = research_factpack.build_verdict(_factpack(0.25), llm_callable=None)
    assert v.rating == "Insufficient data"
    assert v.conviction == "none"
    assert v.data_confidence.directional_allowed is False


def test_research_verdict_llm_cannot_exceed_data_ceiling():
    # medium-coverage data → the LLM claiming "high" is capped down.
    def fake_llm(**kw):
        return '{"rating":"Strong","conviction":"high","summary":"s","dimensions":[]}'

    v = research_factpack.build_verdict(_factpack(0.6), llm_callable=fake_llm)
    assert v.conviction in ("none", "low")  # 40–70% critical → cap at low
    assert v.data_confidence.conviction_cap in ("none", "low")


def test_research_noncritical_gap_does_not_cap_complete_core_facts():
    fp = R.FactPack(
        ticker="TST",
        data_quality=R.DataQuality(
            coverage=0.86,
            sources=[
                R.SourceRef(field="profile", source="fmp", coverage=1.0),
                R.SourceRef(field="fundamentals", source="fmp", coverage=1.0),
                R.SourceRef(field="news", source="unavailable", coverage=0.0),
            ],
            warnings=["news_empty"],
        ),
    )
    v = research_factpack.build_verdict(fp, llm_callable=None)
    assert v.data_confidence.critical_coverage == 1.0
    assert v.data_confidence.missing[0].field == "news"
    assert v.data_confidence.missing[0].critical is False
    assert v.data_confidence.conviction_cap == "high"


def test_research_stale_factpack_is_visible_and_caps_conviction():
    fp = _factpack(1.0)
    fp.cache = R.CacheProvenance(stale=True, fetched_at="2026-07-01T00:00:00Z")
    v = research_factpack.build_verdict(fp, llm_callable=None)
    assert v.data_confidence.stale is True
    assert v.data_confidence.conviction_cap == "low"


# ── COPILOT ───────────────────────────────────────────────────────────────────
def test_copilot_no_evidence_is_not_directional():
    dc = copilot_router._answer_confidence([])
    assert dc.conviction_cap == "none"
    assert dc.directional_allowed is False


def test_copilot_only_soft_evidence_caps_conviction():
    # glossary/reference only (no hard computed/provider facts) → not directional.
    ev = [
        EvidenceItem(label="Sharpe def", value="…", source="glossary"),
        EvidenceItem(label="Neutral band", value="…", source="reference"),
    ]
    dc = copilot_router._answer_confidence(ev)
    assert dc.directional_allowed is False


def test_copilot_hard_evidence_can_be_directional():
    ev = [EvidenceItem(label=f"m{i}", value="1", source="engine") for i in range(4)]
    dc = copilot_router._answer_confidence(ev)  # no grounding floor → trusts evidence
    assert dc.directional_allowed is True
    assert dc.conviction_cap == "high"


def test_copilot_thin_grounding_data_is_not_directional():
    # All-engine evidence but the portfolio score itself is low-quality (thin
    # history) — the quality_floor clamps critical coverage, so NO directional
    # answer. This is the review's HIGH: evidence source-mix alone must not gate.
    ev = [EvidenceItem(label=f"m{i}", value="1", source="engine") for i in range(4)]
    dc = copilot_router._answer_confidence(ev, quality_floor=0.25)
    assert dc.directional_allowed is False
    assert dc.conviction_cap == "none"


# ── RISK EXPLAIN GATE ─────────────────────────────────────────────────────────
def test_risk_explain_gates_directional_on_low_confidence():
    dc = DataConfidence(
        label="low",
        confidence=0.2,
        overall_coverage=0.3,
        critical_coverage=0.25,
        directional_allowed=False,
        conviction_cap="none",
    )
    out = risk_explain.render_template(
        risk_explain.build_skeleton(
            RiskExplainInput(source="score", overall_score=700, data_confidence=dc)
        )
    )
    assert out.directional_allowed is False
    assert out.confidence_label == "low"
    assert any("provisional" in c.lower() for c in out.caveats)
