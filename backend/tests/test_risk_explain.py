"""Tests for the structured AI risk diagnosis.

Covers the deterministic skeleton (severity rules, no-invented-numbers), the
LLM-phrasing path (severity/primary_driver always come from the skeleton, never
the LLM), every fallback (no key / bad JSON / exception), and the HTTP route.
"""

from __future__ import annotations

import json
import re

import pytest

from backend.app.schemas.risk_explain import RiskExplainInput
from backend.app.services import risk_explain as rx

# Label constants that are part of a metric's NAME (VaR 95 / VaR 99), not a
# portfolio measurement — allowed to appear in prose.
_LABEL_NUMBERS = {"95", "99"}

_NUM_RE = re.compile(r"\d+(?:\.\d+)?")


def _payload(**over):
    base = dict(
        source="risk",
        overall_score=520,
        dimensions={
            # 0–10 scale (overall score is the 0–1000 one).
            "risk_match": {"name": "Risk Match", "score": 6.0, "status": "ok"},
            "risk_adjusted_return": {
                "name": "Risk-Adjusted Return",
                "score": 3.0,
                "status": "weak",
            },
            "downside_protection": {
                "name": "Downside Protection",
                "score": 4.8,
                "status": "watch",
            },
        },
        metrics={
            "annual_return": 0.082,
            "annual_volatility": 0.134,
            "sharpe_ratio": -0.16,
            "max_drawdown": -0.38,
            "var_95_daily": -0.021,
            "cvar_95_daily": -0.042,
            "beta_to_benchmark": 1.31,
            "total_value": 19700.0,
            "cash_weight": 0.05,
        },
        top_component_var=[
            {"ticker": "NVDA", "pct": 0.41},
            {"ticker": "MSFT", "pct": 0.22},
        ],
        stress_loss=-0.13,
        stress_market_shock=-0.10,
        liquidity_outliers=[{"ticker": "ABCD", "days_to_liquidate": 7.5}],
        snapshot_delta={"prev_overall_score": 565, "as_of": "2026-05-20"},
    )
    base.update(over)
    return RiskExplainInput.model_validate(base)


# ── severity rules ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "score,extra,expected",
    [
        (
            900,
            {"top_component_var": [], "stress_loss": None, "metrics": {"sharpe_ratio": 1.2}},
            "low",
        ),
        (
            700,
            {"top_component_var": [], "stress_loss": None, "metrics": {"sharpe_ratio": 0.9}},
            "low",
        ),
        (500, {"top_component_var": [], "stress_loss": None, "metrics": {}}, "moderate"),
        (300, {"top_component_var": [], "stress_loss": None, "metrics": {}}, "elevated"),
        # poor band + concentration + negative sharpe + deep drawdown → high
        (
            250,
            {
                "top_component_var": [{"ticker": "X", "pct": 0.55}],
                "metrics": {"sharpe_ratio": -0.4, "max_drawdown": -0.45},
            },
            "high",
        ),
    ],
)
def test_severity_rule_table(score, extra, expected):
    payload = _payload(overall_score=score, dimensions={}, **extra)
    assert rx.build_skeleton(payload).severity == expected


# ── no invented numbers (deterministic path) ───────────────────────────


def _numbers(text: str) -> set[str]:
    return set(_NUM_RE.findall(text))


def _allowed_numbers(payload: RiskExplainInput) -> set[str]:
    """Every numeric string the template is permitted to emit = the formatted
    forms of the INPUT numbers (+ metric-name label constants)."""
    allowed: set[str] = set(_LABEL_NUMBERS)

    def add(*strings):
        for s in strings:
            if s:
                allowed.update(_NUM_RE.findall(str(s)))

    add(str(payload.overall_score))
    m = payload.metrics
    for v in (
        m.annual_volatility,
        m.max_drawdown,
        m.var_95_daily,
        m.cvar_95_daily,
        m.annual_return,
    ):
        add(rx.fmt_pct(v), rx.fmt_pct(v, 0))
    for v in (m.sharpe_ratio, m.beta_to_benchmark):
        add(rx.fmt_ratio(v))
    for c in payload.top_component_var:
        add(rx.fmt_pct(c.pct), rx.fmt_pct(c.pct, 0))
    add(rx.fmt_pct(payload.stress_loss), rx.fmt_pct(payload.stress_market_shock, 0))
    for x in payload.liquidity_outliers:
        add(rx.fmt_ratio(x.days_to_liquidate, 1))
    if payload.snapshot_delta and payload.snapshot_delta.prev_overall_score is not None:
        add(str(payload.snapshot_delta.prev_overall_score))
        if payload.overall_score is not None:
            add(str(abs(payload.overall_score - payload.snapshot_delta.prev_overall_score)))
    return allowed


def test_template_only_cites_input_numbers():
    payload = _payload()
    out = rx.render_template(rx.build_skeleton(payload))
    blob = " ".join(
        [out.headline, out.primary_driver, *out.summary_bullets, *out.watch_items, *out.caveats]
        + [f"{a.reason} {a.evidence} {a.next_step}" for a in out.suggested_actions]
    )
    invented = _numbers(blob) - _allowed_numbers(payload)
    assert not invented, f"template emitted numbers not present in the input: {invented}"


# ── fallback + LLM-phrasing paths ──────────────────────────────────────


def test_none_llm_returns_template():
    out = rx.explain(_payload(), llm_callable=None)
    assert out.ai_generated is False
    assert out.severity in {"low", "moderate", "elevated", "high"}
    assert out.summary_bullets and out.primary_driver


def test_llm_phrasing_keeps_skeleton_severity_and_driver():
    payload = _payload()
    skeleton = rx.build_skeleton(payload)

    def fake_llm(*, prompt, system, max_tokens, temperature):
        # The model tries to plant a DIFFERENT severity + driver + a made-up
        # number — all of which must be ignored.
        return json.dumps(
            {
                "severity": "low",  # ignored
                "primary_driver": "Totally different driver",  # ignored
                "headline": "Your portfolio carries notable concentration risk.",
                "summary_bullets": ["NVDA is your biggest single risk.", "Returns lag the risk."],
                "watch_items": ["Keep an eye on NVDA."],
                "suggested_actions": [
                    {
                        "reason": "Trim concentration",
                        "evidence": "NVDA dominates VaR.",
                        "next_step": "Review sizing.",
                    }
                ],
                "caveats": ["Educational only."],
            }
        )

    out = rx.explain(payload, llm_callable=fake_llm)
    assert out.ai_generated is True
    assert out.severity == skeleton.severity  # NOT "low"
    assert out.primary_driver == skeleton.primary_driver  # NOT the planted one
    assert out.headline.startswith("Your portfolio carries")
    assert all(a.disclaimer for a in out.suggested_actions)  # disclaimer always stamped


def test_bad_json_falls_back_to_template():
    out = rx.explain(_payload(), llm_callable=lambda **_: "I'm sorry, I can't do that.")
    assert out.ai_generated is False
    assert out.summary_bullets


def test_llm_exception_falls_back_to_template():
    def boom(**_):
        raise RuntimeError("anthropic 500")

    out = rx.explain(_payload(), llm_callable=boom)
    assert out.ai_generated is False


def test_empty_metrics_still_produces_output():
    out = rx.explain(RiskExplainInput(source="score", overall_score=720), llm_callable=None)
    assert out.severity == "low"
    assert out.summary_bullets  # never empty


# ── HTTP route ─────────────────────────────────────────────────────────


def _auth(mint_token):
    return {"Authorization": f"Bearer {mint_token()}"}


def test_explain_requires_bearer(test_client):
    assert test_client.post("/api/v1/risk/explain", json={}).status_code == 401


def test_explain_endpoint_template_path(test_client, mint_token, monkeypatch):
    from backend.app.services import llm_client

    monkeypatch.setattr(llm_client, "get_llm_callable", lambda *a, **k: None)
    resp = test_client.post(
        "/api/v1/risk/explain",
        json=_payload().model_dump(),
        headers=_auth(mint_token),
    )
    assert resp.status_code == 200, resp.json()
    data = resp.json()["data"]
    assert data["ai_generated"] is False
    assert data["severity"] in {"low", "moderate", "elevated", "high"}
    assert data["summary_bullets"]


def test_explain_endpoint_llm_path(test_client, mint_token, monkeypatch):
    from backend.app.services import llm_client

    def fake_callable(*, prompt, system, max_tokens, temperature):
        return json.dumps(
            {
                "headline": "Concentration is your main risk right now.",
                "summary_bullets": ["NVDA dominates your VaR.", "Returns lag the risk taken."],
                "watch_items": ["NVDA share of VaR"],
                "suggested_actions": [],
                "caveats": ["Educational only."],
            }
        )

    monkeypatch.setattr(llm_client, "get_llm_callable", lambda *a, **k: fake_callable)
    # silence the cost recorder (no Supabase in tests)
    monkeypatch.setattr("backend.app.api.v1.risk._record_explain_cost", lambda *a, **k: None)
    resp = test_client.post(
        "/api/v1/risk/explain",
        json=_payload().model_dump(),
        headers=_auth(mint_token),
    )
    assert resp.status_code == 200, resp.json()
    data = resp.json()["data"]
    assert data["ai_generated"] is True
    assert data["headline"].startswith("Concentration is your main risk")
