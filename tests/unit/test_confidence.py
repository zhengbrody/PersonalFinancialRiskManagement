"""Tests for libs/risk/confidence.py — data confidence scoring."""

from __future__ import annotations

from libs.risk import compute_confidence
from libs.risk.confidence import confidence_from_meta


def test_fully_healthy_inputs_return_high():
    out = compute_confidence()
    assert out["level"] == "high"
    assert out["score"] == 0
    assert out["missing"] == []
    assert out["hints"] == []


def test_no_risk_report_floors_to_low():
    """Without a RiskReport the AI is generating text from nothing.
    Floor to low regardless of every other input."""
    out = compute_confidence(
        risk_report_present=False,
        fmp_ok=True,
        cost_basis_coverage=1.0,
    )
    assert out["level"] == "low"
    assert "risk_report" in out["missing"]


def test_llm_fallback_alone_drops_to_medium():
    """LLM provider down → fallback text. Worth a downgrade because
    the wording came from a static template, not real reasoning."""
    out = compute_confidence(llm_fallback=True)
    assert out["level"] == "medium"
    assert "llm_provider" in out["missing"]


def test_combined_signals_collapse_to_low():
    out = compute_confidence(
        fmp_ok=False,
        yfinance_missing=["DELISTED", "BAD1", "BAD2"],
        cost_basis_coverage=0.30,
        stale_data=True,
    )
    assert out["level"] == "low"
    assert "fmp" in out["missing"]
    assert "prices" in out["missing"]
    assert "cost_basis" in out["missing"]
    assert "fresh_prices" in out["missing"]


def test_partial_cost_basis_only_dings_lightly():
    """Coverage between 0.4 and 0.7 → -1 score (still high)."""
    out = compute_confidence(cost_basis_coverage=0.6)
    assert out["level"] == "high"  # one downgrade below threshold
    assert any("Cost basis" in h for h in out["hints"])


def test_missing_tickers_threshold_3_is_heavier():
    """Three or more missing tickers earns weight=2; under three earns 1."""
    light = compute_confidence(yfinance_missing=["A"])
    heavy = compute_confidence(yfinance_missing=["A", "B", "C"])
    assert heavy["score"] >= light["score"] + 1


def test_extra_signal_factor_model_failed_dings_meaningfully():
    out = compute_confidence(extra_signals={"factor_model_failed": True})
    assert out["level"] in ("medium", "high")
    assert "factor_model" in out["missing"]


def test_extra_signal_short_sample_is_light_only():
    out = compute_confidence(extra_signals={"sample_size_short": True})
    assert out["level"] == "high"  # weight 1, below threshold


def test_confidence_levels_constants():
    """Public constants tuple — pin to detect accidental rename."""
    from libs.risk.confidence import CONFIDENCE_LEVELS

    assert CONFIDENCE_LEVELS == ("high", "medium", "low")


# ── confidence_from_meta ────────────────────────────────────────────


def test_confidence_from_meta_handles_none():
    """Page hands us None when no analysis run — must not crash."""
    out = confidence_from_meta(None)
    assert out["level"] in {"high", "medium", "low"}


def test_confidence_from_meta_reads_position_cost_info():
    out = confidence_from_meta(
        {
            "position_cost_info": {"coverage_by_mv_pct": 0.30},
            "missing": ["X", "Y", "Z"],
            "data_quality": {"fmp_unavailable": True, "stale": True},
        }
    )
    assert out["level"] == "low"
    # All four degradation sources should be present.
    assert {"fmp", "fresh_prices", "prices", "cost_basis"}.issubset(set(out["missing"]))


def test_confidence_from_meta_clean_state_is_high():
    out = confidence_from_meta(
        {
            "position_cost_info": {"coverage_by_mv_pct": 0.95},
            "missing": [],
            "data_quality": {},
        }
    )
    assert out["level"] == "high"
