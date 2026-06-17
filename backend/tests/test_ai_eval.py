"""AI-quality eval heuristics — direct-advice / grounding / invented-number,
and the telemetry redaction (eval signals carry no tickers/$/prompt)."""

from __future__ import annotations

from backend.app.services.ai_eval import (
    answer_grounded,
    detect_direct_advice,
    detect_invented_number,
    eval_signals,
)


def test_detect_direct_advice_flags_imperatives_not_honest_framing():
    assert detect_direct_advice("You should sell NVDA now.")
    assert detect_direct_advice("It's a strong buy.")
    assert detect_direct_advice("I'd buy this today.")
    # Honest, non-prescriptive framing must NOT trip it.
    assert not detect_direct_advice("If you were to sell, your VaR would drop.")
    assert not detect_direct_advice("This position drives most of your risk.")
    assert not detect_direct_advice("")


def test_answer_grounded_requires_evidence():
    assert answer_grounded("Your Sharpe is 0.9.", 3)
    assert not answer_grounded("Your Sharpe is 0.9.", 0)  # numbers, no evidence
    assert not answer_grounded("", 5)


def test_invented_number_only_when_figures_without_evidence():
    # $/% figure with ZERO evidence → flagged (the real failure mode).
    assert detect_invented_number("It should return 25% next year.", 0)
    assert detect_invented_number("Worth about $4,200.", 0)
    # With evidence present we trust the cite-only synthesis (no noisy guessing).
    assert not detect_invented_number("It should return 25% next year.", 4)
    # No salient figure → never flagged.
    assert not detect_invented_number("Diversified and stable.", 0)


def test_eval_signals_bundle_is_scalar_and_privacy_safe():
    sig = eval_signals(
        text="NVDA is 55% of your VaR.",
        evidence_count=2,
        intent="portfolio_diagnosis",
        fallback_used=False,
    )
    assert sig["answer_grounded"] is True
    assert sig["invented_number_detected"] is False
    assert sig["direct_advice_detected"] is False
    assert sig["intent"] == "portfolio_diagnosis"
    assert sig["fallback_used"] is False
    # Every value is a scalar (bool/str/num) — nothing to leak.
    assert all(isinstance(v, (bool, str, int, float)) for v in sig.values())


def test_record_ai_call_merges_eval_metadata(monkeypatch):
    from backend.app.services import ai_telemetry

    captured = {}

    def _fake_record_event(user_id, kind, **kw):
        captured.update(kw)

    monkeypatch.setattr("libs.billing.usage.record_event", _fake_record_event)
    monkeypatch.setattr("libs.billing.costs.estimate_cost_usd", lambda *a, **k: 0.001)

    ai_telemetry.record_ai_call(
        "u-1",
        "chat",
        model="claude-haiku",
        tokens_in=100,
        tokens_out=50,
        latency_ms=123.4,
        eval_metadata={"intent": "margin_risk", "answer_grounded": True},
    )
    md = captured["metadata"]
    assert md["latency_ms"] == 123.4 and "input_hash" in md  # base fields kept
    assert md["intent"] == "margin_risk" and md["answer_grounded"] is True  # eval merged
