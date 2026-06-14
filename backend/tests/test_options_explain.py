"""Tests for the options AI-explain (deterministic skeleton → optional LLM
rephrase). The LLM never changes severity/actions/numbers; failures fall back to
the deterministic template.
"""

from __future__ import annotations

from backend.app.schemas.options import OptionExplainInput
from backend.app.services import options_explain as ox


def _exposure(flags, **over):
    base = dict(
        net_delta=50.0,
        gross_delta=50.0,
        net_gamma=-1.0,
        net_theta=-20.0,
        net_vega=10.0,
        option_market_value=1000.0,
        option_notional=12000.0,
        short_collateral_estimate=10000.0,
        contracts=2,
        short_contracts=1,
        expiry_ladder=[],
        underlying_exposure=[],
        flags=flags,
    )
    base.update(over)
    return base


def _payload(flags, **over):
    return OptionExplainInput.model_validate({"exposure": _exposure(flags, **over)})


def test_high_flag_drives_high_severity_and_action():
    p = _payload(
        [
            {
                "code": "uncovered_short_call",
                "severity": "high",
                "detail": "Short 1 AAPL call uncovered.",
            }
        ]
    )
    sk = ox.build_skeleton(p)
    assert sk.severity == "high"
    assert "uncovered" in sk.primary_driver.lower()
    assert any("coverage" in a.title.lower() for a in sk.actions)


def test_watch_flag_is_elevated():
    p = _payload([{"code": "concentrated_expiry", "severity": "watch", "detail": "One expiry."}])
    assert ox.build_skeleton(p).severity == "elevated"


def test_no_flags_but_short_gamma_is_moderate():
    p = _payload([], net_gamma=-2.0)
    assert ox.build_skeleton(p).severity == "moderate"


def test_clean_book_is_low():
    p = _payload([], net_gamma=1.0, net_theta=5.0)
    sk = ox.build_skeleton(p)
    assert sk.severity == "low"
    assert "balanced" in sk.primary_driver.lower()


def test_template_carries_disclaimer():
    out = ox.render_template(ox.build_skeleton(_payload([])))
    assert out.ai_generated is False
    assert any("not financial advice" in c.lower() for c in out.caveats)


def test_llm_rephrase_locks_severity_and_actions():
    p = _payload([{"code": "short_gamma", "severity": "high", "detail": "Net short gamma."}])

    def fake_llm(prompt, system, **k):
        return '{"headline": "Rephrased headline", "summary_bullets": ["a", "b"]}'

    out = ox.explain(p, llm_callable=fake_llm)
    assert out.ai_generated is True
    assert out.headline == "Rephrased headline"
    assert out.severity == "high"  # locked to skeleton
    assert out.suggested_actions  # locked to skeleton


def test_llm_failure_falls_back_to_template():
    p = _payload([{"code": "short_gamma", "severity": "high", "detail": "Net short gamma."}])

    def boom(**k):
        raise RuntimeError("llm down")

    out = ox.explain(p, llm_callable=boom)
    assert out.ai_generated is False
    assert out.severity == "high"


def test_llm_bad_json_falls_back():
    p = _payload([])
    out = ox.explain(p, llm_callable=lambda **k: "not json at all")
    assert out.ai_generated is False


# ── route ─────────────────────────────────────────────────────────────────────


def _exp_body():
    return {"exposure": _exposure([{"code": "short_gamma", "severity": "high", "detail": "x"}])}


def test_explain_route_requires_auth(test_client):
    assert test_client.post("/api/v1/options/explain", json=_exp_body()).status_code == 401


def test_explain_route_happy_no_llm(test_client, mint_token, monkeypatch):
    # No LLM key → deterministic template (still a valid 200).
    monkeypatch.setattr("backend.app.services.llm_client.get_llm_callable", lambda **k: None)
    resp = test_client.post(
        "/api/v1/options/explain",
        json=_exp_body(),
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["severity"] == "high"
    assert data["ai_generated"] is False
