"""Copilot PR4 — deterministic proactive insights.

Materiality thresholds, one-per-kind dedup + stable episode ids, the
data-quality directional gate, advice-free templates, fail-soft degradation,
and the authed endpoint.
"""

from __future__ import annotations

import re
from types import SimpleNamespace

import pytest

from backend.app.services import copilot_insights as ci


class _Metrics:
    annual_return = 0.12
    annual_volatility = 0.18
    sharpe_ratio = 0.67
    max_drawdown = -0.25
    var_95_daily = -0.021
    beta_to_benchmark = 1.05
    total_value = 19700.0
    net_equity = 19700.0
    leverage = 1.0
    data_quality = 0.95
    confidence = "high"
    reason_codes: list = []


def _score(overall=720, prev_overall=760, **metric_overrides):
    m = _Metrics()
    for k, v in metric_overrides.items():
        setattr(m, k, v)
    dims = {
        "risk_match": SimpleNamespace(score=6.0),
        "risk_adjusted_return": SimpleNamespace(score=6.0),
        "downside_protection": SimpleNamespace(score=6.0),
    }
    return SimpleNamespace(
        overall_score=overall,
        base_overall=overall,
        metrics=m,
        dimensions=dims,
        concentration=SimpleNamespace(
            top_holding_weight=0.15, top_holding_ticker="AAA", top5_weight=0.6
        ),
    )


def _prev_snapshot(overall=760, dims=6.5, extra_metrics=None):
    from libs.mindmarket_core.score_version import SCORE_VERSION

    rm = {
        "overall_score": overall,
        "base_overall": overall,
        "dimensions": {
            "risk_match": dims,
            "risk_adjusted_return": dims,
            "downside_protection": dims,
        },
    }
    rm.update(extra_metrics or {})
    return {
        "created_at": "2026-07-13T00:00:00+00:00",
        "score_version": SCORE_VERSION,
        "risk_metrics": rm,
        "data_quality": {"confidence": "high"},
        "top_positions": [{"ticker": "AAA", "weight": 0.5}, {"ticker": "BBB", "weight": 0.5}],
    }


@pytest.fixture
def wired(monkeypatch):
    """Wire the loader seams; individual tests override the pieces."""

    def use(score=None, prev=None, regime=None, positions=None):
        # Positions matching the prior snapshot's top_positions → a no-trade
        # day, so the attribution is separable (market vs holdings).
        pos = (
            positions
            if positions is not None
            else [
                SimpleNamespace(ticker="AAA", market_value=5000.0),
                SimpleNamespace(ticker="BBB", market_value=5000.0),
            ]
        )
        monkeypatch.setattr(ci, "_load", lambda user: (pos, score or _score()))
        monkeypatch.setattr(ci, "_snapshot", lambda user, window: prev)
        import backend.app.services.ml_regime as mlr

        monkeypatch.setattr(
            mlr, "get_regime", lambda **k: regime or {"regime": "neutral", "confidence": 0.7}
        )

    return use


USER = SimpleNamespace(access_token="jwt", id="u1")


# ── materiality ───────────────────────────────────────────────────────


def test_small_move_is_noise_no_insight(wired):
    wired(score=_score(overall=750), prev=_prev_snapshot(overall=760))  # -10 pts < 25
    out = ci.build_insights(USER)
    assert out.portfolio_available is True
    assert not [i for i in out.insights if i.kind == "score_move"]


def test_material_move_emits_attributed_insight(wired):
    wired(score=_score(overall=720), prev=_prev_snapshot(overall=760))  # -40 pts
    out = ci.build_insights(USER)
    moves = [i for i in out.insights if i.kind == "score_move"]
    assert len(moves) == 1
    ins = moves[0]
    assert "-40" in ins.what_changed
    labels = {e.label: e.value for e in ins.evidence}
    assert labels["Health-score change (since last snapshot)"] == "-40 pts"
    assert "Market-driven" in labels  # attribution rides as evidence
    assert ins.suggested_next_analysis is not None
    assert ins.suggested_next_analysis.href == "/score"
    assert all(e.id and e.tool for e in ins.evidence)


def test_concentration_below_limit_silent_above_fires(wired):
    wired(score=_score(), prev=_prev_snapshot())
    assert not [i for i in ci.build_insights(USER).insights if i.kind == "concentration"]

    heavy = _score()
    heavy.concentration = SimpleNamespace(
        top_holding_weight=0.42, top_holding_ticker="NVDA", top5_weight=0.8
    )
    wired(score=heavy, prev=_prev_snapshot())
    conc = [i for i in ci.build_insights(USER).insights if i.kind == "concentration"]
    assert len(conc) == 1 and conc[0].severity == "high"
    assert "42.0%" in conc[0].what_changed
    assert conc[0].id == "concentration:NVDA"  # stable episode id


def test_leverage_gate_and_stable_id(wired):
    wired(score=_score(leverage=1.2), prev=_prev_snapshot())
    assert not [i for i in ci.build_insights(USER).insights if i.kind == "leverage"]
    wired(score=_score(leverage=2.3), prev=_prev_snapshot(extra_metrics={"leverage": 1.1}))
    lev = [i for i in ci.build_insights(USER).insights if i.kind == "leverage"]
    assert len(lev) == 1 and lev[0].severity == "high" and lev[0].id == "leverage:elevated"
    labels = {e.label: e.value for e in lev[0].evidence}
    assert labels["Current leverage"] == "2.30×"
    assert labels["Prior snapshot leverage"] == "1.10×"


def test_regime_insight_requires_state_and_beta(wired):
    wired(score=_score(beta_to_benchmark=1.3), regime={"regime": "stress", "confidence": 0.8})
    reg = [i for i in ci.build_insights(USER).insights if i.kind == "market_regime"]
    assert len(reg) == 1 and reg[0].id == "market_regime:stress"
    # calm state → nothing
    wired(score=_score(beta_to_benchmark=1.3), regime={"regime": "neutral", "confidence": 0.8})
    assert not [i for i in ci.build_insights(USER).insights if i.kind == "market_regime"]
    # low-beta book → market state isn't personally material
    wired(score=_score(beta_to_benchmark=0.6), regime={"regime": "stress", "confidence": 0.8})
    assert not [i for i in ci.build_insights(USER).insights if i.kind == "market_regime"]


# ── dedup / cooldown ─────────────────────────────────────────────────


def test_ids_stable_across_calls_and_one_per_kind(wired):
    heavy = _score(overall=720, leverage=2.3)
    heavy.concentration = SimpleNamespace(
        top_holding_weight=0.42, top_holding_ticker="NVDA", top5_weight=0.8
    )
    wired(score=heavy, prev=_prev_snapshot(overall=760))
    a = ci.build_insights(USER)
    b = ci.build_insights(USER)
    assert [i.id for i in a.insights] == [i.id for i in b.insights]  # stable episode ids
    kinds = [i.kind for i in a.insights]
    assert len(kinds) == len(set(kinds))  # at most one per kind


# ── directional gate ─────────────────────────────────────────────────


def test_thin_data_yields_only_data_quality_insight(wired):
    bad = _score(overall=300, data_quality=0.2, confidence="low")
    bad.metrics.reason_codes = ["missing_price_data", "short_history"]
    wired(score=bad, prev=_prev_snapshot(overall=760))
    out = ci.build_insights(USER)
    assert [i.kind for i in out.insights] == ["data_quality"]
    dq = out.insights[0]
    assert "missing_price_data" in dq.missing_data
    assert dq.suggested_next_analysis is not None


# ── boundaries: no advice, fail-soft, endpoint ───────────────────────


def test_no_trade_directives_in_any_template(wired):
    heavy = _score(overall=700, leverage=2.5, beta_to_benchmark=1.4)
    heavy.concentration = SimpleNamespace(
        top_holding_weight=0.45, top_holding_ticker="NVDA", top5_weight=0.9
    )
    wired(
        score=heavy,
        prev=_prev_snapshot(overall=760),
        regime={"regime": "stress", "confidence": 0.9},
    )
    out = ci.build_insights(USER)
    assert out.insights
    blob = " ".join(
        f"{i.what_changed} {i.why_it_matters} "
        + " ".join(f"{e.label} {e.value}" for e in i.evidence)
        + (i.suggested_next_analysis.label if i.suggested_next_analysis else "")
        for i in out.insights
    )
    assert not re.search(r"\b(buy|sell|short|dump|target price)\b", blob, re.IGNORECASE)
    for i in out.insights:
        assert i.suggested_next_analysis is None or i.suggested_next_analysis.href.startswith("/")


def test_no_portfolio_fails_soft(monkeypatch):
    def boom(user):
        raise RuntimeError("no active portfolio")

    monkeypatch.setattr(ci, "_load", boom)
    out = ci.build_insights(USER)
    assert out.portfolio_available is False and out.insights == []
    assert out.missing_data


def test_missing_snapshot_still_yields_state_insights(wired):
    heavy = _score(leverage=2.3)
    wired(score=heavy, prev=None)
    out = ci.build_insights(USER)
    lev = [i for i in out.insights if i.kind == "leverage"]
    assert len(lev) == 1
    assert "no prior snapshot to compare against" in lev[0].missing_data
    assert not [i for i in out.insights if i.kind == "score_move"]  # change needs a prior


def test_insights_endpoint_requires_auth(test_client):
    assert test_client.get("/api/v1/copilot/insights").status_code == 401


def test_insights_endpoint_happy_and_failsoft(test_client, mint_token, monkeypatch):
    import backend.app.api.v1.copilot as api
    from backend.app.schemas.copilot_insights import InsightsOut

    headers = {"Authorization": f"Bearer {mint_token()}"}

    monkeypatch.setattr(
        "backend.app.services.copilot_insights.build_insights",
        lambda user: InsightsOut(
            insights=[], as_of="2026-07-14T00:00:00+00:00", portfolio_available=True
        ),
    )
    resp = test_client.get("/api/v1/copilot/insights", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["data"]["portfolio_available"] is True

    def boom(user):
        raise RuntimeError("engine down")

    monkeypatch.setattr("backend.app.services.copilot_insights.build_insights", boom)
    resp2 = test_client.get("/api/v1/copilot/insights", headers=headers)
    assert resp2.status_code == 200  # fail-soft, never a 500
    assert resp2.json()["data"]["insights"] == []
    assert api is not None
