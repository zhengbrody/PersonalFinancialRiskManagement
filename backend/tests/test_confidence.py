"""Unified data-confidence contract + enforcement (rule #3).

The load-bearing guarantee: low-quality data can NEVER produce a high-conviction
directional conclusion. These pin the enforcement helper directly; the
per-surface integration tests (score/risk/research/copilot) assert the same
holds end-to-end.
"""

from __future__ import annotations

from backend.app.services import confidence as C


# ── source-type mapping (registry role → primary/secondary/derived) ───────────
def test_source_type_mapping():
    assert C.source_type_for("massive") == "primary"  # registry PRIMARY
    assert C.source_type_for("fmp") == "primary"
    assert C.source_type_for("yfinance") == "secondary"  # registry FALLBACK
    assert C.source_type_for("engine") == "derived"  # registry COMPUTED
    assert C.source_type_for("derived") == "derived"
    assert C.source_type_for("totally-unknown") == "derived"  # graceful default


# ── missing-reason classification (the typed enum, rule #4) ───────────────────
def test_missing_reason_classification():
    assert C.classify_missing_reason("massive_rate_limited") == "rate_limited"
    assert C.classify_missing_reason("fmp_key_missing") == "no_key"
    assert C.classify_missing_reason("requires Starter plan (402)") == "unsupported"
    assert C.classify_missing_reason("history_capped_at_5") == "insufficient_history"
    assert C.classify_missing_reason("insufficient_history") == "insufficient_history"
    assert C.classify_missing_reason("return_1y not_fetched") == "not_applicable"
    assert C.classify_missing_reason("served stale value") == "stale_fallback"
    assert C.classify_missing_reason("fmp_error:TimeoutError") == "provider_error"
    assert C.classify_missing_reason("no_income_statement") == "empty"
    assert C.classify_missing_reason() == "empty"


# ── the enforcement rules, verbatim ───────────────────────────────────────────
def test_under_40pct_critical_no_directional_verdict():
    conviction, directional, reasons = C.cap_conviction("high", critical_coverage=0.30)
    assert directional is False
    assert conviction == "none"
    assert any(r.code == "critical_coverage_below_40" for r in reasons)


def test_40_to_70pct_caps_conviction_at_low():
    for base in ("high", "medium", "low"):
        conviction, directional, _ = C.cap_conviction(base, critical_coverage=0.55)
        assert directional is True
        assert conviction in ("none", "low")  # never above low
        assert conviction == ("low" if base != "none" else "none")


def test_stale_reduces_conviction():
    conviction, _, reasons = C.cap_conviction("high", critical_coverage=0.90, stale=True)
    assert conviction == "low"
    assert any(r.code == "stale_critical_data" for r in reasons)


def test_missing_critical_reduces_conviction():
    conviction, _, reasons = C.cap_conviction("high", critical_coverage=0.90, missing_critical=True)
    assert conviction == "low"
    assert any(r.code == "missing_critical_data" for r in reasons)


def test_full_data_keeps_full_conviction():
    conviction, directional, reasons = C.cap_conviction("high", critical_coverage=0.95)
    assert directional is True
    assert conviction == "high"
    assert reasons == []


def test_cap_never_raises_conviction():
    # a "low" base with perfect data stays low — the layer only caps.
    conviction, _, _ = C.cap_conviction("low", critical_coverage=1.0)
    assert conviction == "low"


# ── builder: low data → low label + capped conviction (THE guarantee) ─────────
def test_builder_low_quality_cannot_be_high_confidence():
    dc = C.build_data_confidence(
        overall_coverage=0.30,
        critical_coverage=0.25,
        sources=[C.field_provenance("price", "yfinance", coverage=0.3)],
        missing=[
            C.field_provenance("fundamentals", "unavailable", missing_reason="no_key", coverage=0.0)
        ],
        base_conviction="high",
    )
    assert dc.label == "low"
    assert dc.confidence < C._LABEL_MED
    assert dc.directional_allowed is False
    assert dc.conviction_cap == "none"
    assert dc.fallback_used is True  # yfinance is a fallback source


def test_builder_full_quality_is_high_confidence():
    dc = C.build_data_confidence(
        overall_coverage=0.99,
        critical_coverage=0.98,
        sources=[C.field_provenance("price", "massive", coverage=0.99, as_of="2026-07-10")],
        confidence=0.9,
        base_conviction="high",
    )
    assert dc.label == "high"
    assert dc.directional_allowed is True
    assert dc.conviction_cap == "high"


def test_builder_passes_through_surface_own_confidence_float():
    # score/research pass their OWN float — the builder must not recompute it.
    dc = C.build_data_confidence(
        overall_coverage=0.6, critical_coverage=0.6, sources=[], confidence=0.62
    )
    assert dc.confidence == 0.62
    assert dc.label == "medium"


# ── cross-source agreement (net-new, where available) ─────────────────────────
def test_cross_source_agreement():
    assert C.cross_source_agreement([100.0]) is None  # <2 sources → None, never fabricated
    assert C.cross_source_agreement([100.0, 100.0]) == 1.0  # identical
    a = C.cross_source_agreement([100.0, 90.0])  # 10% spread
    assert a is not None and 0.0 < a < 1.0
    assert C.cross_source_agreement([100.0, 40.0]) == 0.0  # huge spread → 0
