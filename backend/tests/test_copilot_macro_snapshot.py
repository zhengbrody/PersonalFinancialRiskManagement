"""Hotfix regression suite: /copilot/ask macro_rates with the REAL
``market_regime.RegimeSnapshot`` (a frozen dataclass).

Production bug: the macro branch (and the MCP get_macro_context tool) did
``dict(snap)`` on the dataclass → TypeError → 500, masked since #56 because
every fixture patched ``get_market_regime`` with a Mapping. These tests use
the REAL types; ``snapshot_to_mapping`` (services/_common.py) is the single
conversion home.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

from backend.app.schemas.copilot2 import SECTION_KEYS
from backend.app.services import copilot_router as cr
from backend.app.services import market_regime as mr
from backend.app.services._common import snapshot_to_mapping
from backend.app.services.market_regime import (
    FearGreedState,
    RegimeSnapshot,
    VixState,
    YieldCurveState,
)


def _real_snapshot() -> RegimeSnapshot:
    return RegimeSnapshot(
        vix=VixState(current=17.4, change=0.035, level="Low"),
        fear_greed=FearGreedState(score=62.0, rating="Greed"),
        yield_curve=YieldCurveState(status="Normal", spread_3m_10y=0.45, inverted=False),
    )


# ── the helper: one typed dispatch, fail-soft on unknown shapes ───────


def test_helper_dataclass_recursive():
    d = snapshot_to_mapping(_real_snapshot())
    assert d is not None
    assert d["vix"] == {"current": 17.4, "change": 0.035, "level": "Low"}
    assert d["fear_greed"]["rating"] == "Greed"
    assert d["yield_curve"]["inverted"] is False
    assert all(isinstance(v, dict) for v in d.values())  # nested states are plain dicts


def test_helper_pydantic_like_and_mapping_and_none():
    class _Model:
        def model_dump(self):
            return {"vix": {"current": 14.0}}

    assert snapshot_to_mapping(_Model()) == {"vix": {"current": 14.0}}
    assert snapshot_to_mapping({"a": 1}) == {"a": 1}
    assert snapshot_to_mapping(None) is None


def test_helper_unknown_type_warns_and_fails_soft(caplog):
    with caplog.at_level(logging.WARNING):
        assert snapshot_to_mapping(object()) is None
    assert any("snapshot_to_mapping.unsupported_type" in r.message for r in caplog.records)
    # the warning names only the TYPE — no object contents leak into logs
    assert any("type=object" in r.message for r in caplog.records)


# ── macro_rates through the real router with the REAL dataclass ───────


def test_macro_intent_english_with_real_dataclass(monkeypatch):
    monkeypatch.setattr(mr, "get_market_regime", lambda: _real_snapshot())
    ans = cr.answer("how are interest rates and the vix looking?", user=object(), llm_callable=None)
    assert ans.intent == "macro_rates"
    values = {e.label: e.value for e in ans.evidence}
    assert values["VIX"] == "17.4"
    assert values["VIX level"] == "Low"
    assert values["Fear & Greed"] == "62"
    assert values["F&G rating"] == "Greed"
    assert values["Yield curve"] == "Normal"
    assert values["3m-10y spread"] == "0.45"
    # VixState.change (a fractional return) is deliberately NOT emitted —
    # the display-percent semantics live on /risk-today, not here.
    assert not any("change" in e.label.lower() for e in ans.evidence)
    assert [s.key for s in ans.sections] == list(SECTION_KEYS)  # six sections intact
    assert all(e.tool == "macro_regime" and e.id for e in ans.evidence)
    assert all(isinstance(e.value, str) for e in ans.evidence)  # no dataclass leaks


def test_macro_intent_chinese_with_real_dataclass(monkeypatch):
    monkeypatch.setattr(mr, "get_market_regime", lambda: _real_snapshot())
    ans = cr.answer("美联储利率和VIX现在对市场意味着什么？", user=object(), llm_callable=None)
    assert ans.intent == "macro_rates"
    assert ans.language == "zh"
    assert ans.disclaimer == "教育性分析，不构成投资建议。"
    assert {e.label: e.value for e in ans.evidence}["VIX"] == "17.4"
    assert [s.title for s in ans.sections][0] == "直接回答"


def test_cached_snapshot_instance_served_twice(monkeypatch):
    """market_regime caches and re-serves the SAME frozen instance — repeated
    answers over the cached dataclass must keep working."""
    snap = _real_snapshot()
    calls = {"n": 0}

    def cached():
        calls["n"] += 1
        return snap

    monkeypatch.setattr(mr, "get_market_regime", cached)
    a1 = cr.answer("how is the fed looking?", user=object(), llm_callable=None)
    a2 = cr.answer("how is the fed looking?", user=object(), llm_callable=None)
    assert calls["n"] == 2
    for a in (a1, a2):
        assert {e.label for e in a.evidence} >= {"VIX", "Fear & Greed"}


def test_mapping_fixture_still_supported(monkeypatch):
    """The eval harness / older fixtures patch the seam with Mappings — that
    contract stays valid alongside the real dataclass."""
    monkeypatch.setattr(
        mr,
        "get_market_regime",
        lambda: {
            "vix": {"current": 17.4, "change": 0.035, "level": "Low"},
            "fear_greed": {"score": 62, "rating": "Greed"},
            "yield_curve": {"status": "Normal", "spread_3m_10y": 0.45},
        },
    )
    ans = cr.answer("how are rates?", user=object(), llm_callable=None)
    assert {e.label: e.value for e in ans.evidence}["VIX"] == "17.4"


def test_pydantic_like_snapshot_still_supported(monkeypatch):
    class _Snap:
        def model_dump(self):
            return {
                "vix": {"current": 14.0, "level": "Low"},
                "fear_greed": {"score": 60, "rating": "Greed"},
                "yield_curve": {"status": "Normal", "spread_3m_10y": 0.45},
            }

    monkeypatch.setattr(mr, "get_market_regime", lambda: _Snap())
    ans = cr.answer("how are rates?", user=object(), llm_callable=None)
    assert {e.label: e.value for e in ans.evidence}["VIX"] == "14.0"


def test_none_unknown_and_partial_shapes_never_raise(monkeypatch):
    # None (the safe()-failure path) → empty evidence, honest degradation
    monkeypatch.setattr(mr, "get_market_regime", lambda: None)
    ans = cr.answer("how are rates?", user=object(), llm_callable=None)
    assert ans.evidence == [] and ans.data_only is True
    assert ans.data_confidence is not None
    assert ans.data_confidence.directional_allowed is False

    # unknown object → warning + empty evidence, never a 500
    monkeypatch.setattr(mr, "get_market_regime", lambda: object())
    ans2 = cr.answer("how are rates?", user=object(), llm_callable=None)
    assert ans2.evidence == []

    # partial: all-None legs → the None fields simply drop out
    monkeypatch.setattr(
        mr,
        "get_market_regime",
        lambda: RegimeSnapshot(
            vix=VixState(current=None, change=None, level=None),
            fear_greed=FearGreedState(score=None, rating=None),
            yield_curve=YieldCurveState(status=None, spread_3m_10y=None, inverted=None),
        ),
    )
    ans3 = cr.answer("how are rates?", user=object(), llm_callable=None)
    assert ans3.evidence == []

    # mixed shape: Mapping top with a dataclass leg + a None leg
    monkeypatch.setattr(
        mr,
        "get_market_regime",
        lambda: {
            "vix": VixState(current=17.4, change=0.035, level="Low"),
            "fear_greed": None,
            "yield_curve": {"status": "Flat"},
        },
    )
    ans4 = cr.answer("how are rates?", user=object(), llm_callable=None)
    values = {e.label: e.value for e in ans4.evidence}
    assert values["VIX"] == "17.4" and values["Yield curve"] == "Flat"


# ── /copilot/ask integration: the real dataclass path end-to-end ──────


def test_ask_endpoint_macro_with_real_dataclass(test_client, mint_token, monkeypatch):
    monkeypatch.setattr(mr, "get_market_regime", lambda: _real_snapshot())
    resp = test_client.post(
        "/api/v1/copilot/ask",
        json={"message": "how are interest rates and the vix looking?"},
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["intent"] == "macro_rates"
    labels = {e["label"]: e["value"] for e in data["evidence"]}
    assert labels["VIX"] == "17.4"
    assert [s["key"] for s in data["sections"]] == list(SECTION_KEYS)
    assert data["language"] == "en"


def test_ask_endpoint_macro_chinese_with_real_dataclass(test_client, mint_token, monkeypatch):
    monkeypatch.setattr(mr, "get_market_regime", lambda: _real_snapshot())
    resp = test_client.post(
        "/api/v1/copilot/ask",
        json={"message": "美联储利率和VIX现在对市场意味着什么？"},
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["language"] == "zh"
    assert {e["label"] for e in data["evidence"]} >= {"VIX", "Fear & Greed"}


def test_other_intents_unaffected(monkeypatch):
    """A non-macro intent never touches the regime seam (no regression)."""

    def boom():
        raise AssertionError("macro seam must not be called for a ticker question")

    monkeypatch.setattr(mr, "get_market_regime", boom)
    positions_score = SimpleNamespace(
        overall_score=720,
        metrics=SimpleNamespace(
            annual_return=0.12,
            annual_volatility=0.18,
            sharpe_ratio=0.67,
            max_drawdown=-0.25,
            var_95_daily=-0.021,
            beta_to_benchmark=1.05,
            total_value=19700.0,
        ),
    )
    monkeypatch.setattr(cr, "_load_score_positions", lambda user: ([], positions_score))
    ans = cr.answer("how risky is my portfolio", user=object(), llm_callable=None)
    assert ans.intent == "portfolio_diagnosis"
    assert {e.label for e in ans.evidence} >= {"Health score", "Sharpe ratio"}
