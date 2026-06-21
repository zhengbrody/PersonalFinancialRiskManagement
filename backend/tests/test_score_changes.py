"""Deterministic 'what changed?' engine + endpoint.

The score is a deterministic function of the dimension scores, so the overall
delta must decompose EXACTLY into per-dimension point contributions. These tests
prove the attribution, the input/data-quality/holdings diffs, and that an
unavailable snapshot degrades gracefully — all offline (no LLM, no DB)."""

from __future__ import annotations

from backend.app.schemas.score_changes import ScoreChangeRequest
from backend.app.services.score_changes import build_change_report


def _req(**kw):
    base = dict(
        window="previous",
        overall_score=500,
        base_overall=500,
        dimensions={"risk_match": 6.0, "risk_adjusted_return": 6.0, "downside_protection": 6.0},
        metrics={
            "annual_volatility": 0.15,
            "sharpe_ratio": 0.8,
            "max_drawdown": 0.12,
            "var_95_daily": 0.013,
            "beta_to_benchmark": 0.9,
            "net_equity": 100_000.0,
            "leverage": 1.0,
        },
        confidence="high",
        dropped_tickers=[],
        top_positions=[{"ticker": "AAA", "weight": 0.5}, {"ticker": "BBB", "weight": 0.5}],
    )
    base.update(kw)
    return ScoreChangeRequest(**base)


def _snap(**rm):
    risk_metrics = dict(
        overall_score=500,
        base_overall=500,
        dimensions={"risk_match": 6.0, "risk_adjusted_return": 6.0, "downside_protection": 6.0},
        annual_volatility=0.15,
        sharpe_ratio=0.8,
        max_drawdown=0.12,
        var_95_daily=0.013,
        beta_to_benchmark=0.9,
        net_equity=100_000.0,
    )
    risk_metrics.update(rm)
    return {
        "created_at": "2026-06-13T00:00:00+00:00",
        "risk_metrics": risk_metrics,
        "data_quality": {"confidence": "high", "dropped_tickers": []},
        "top_positions": [{"ticker": "AAA", "weight": 0.5}, {"ticker": "BBB", "weight": 0.5}],
        "net_equity": 100_000.0,
        "leverage": 1.0,
    }


def test_no_prior_snapshot_is_graceful():
    rep = build_change_report(_req(), None)
    assert rep.available is False
    assert rep.score_delta is None
    assert "No earlier snapshot" in rep.summary


def test_component_deltas_decompose_the_score_move_exactly():
    """A drop in risk-adjusted-return from 6→1 must contribute exactly
    0.35 × (1−6) × 1000/9 ≈ −194 pts, and the component contributions must sum to
    the actual score delta (an exact decomposition)."""
    prev = _snap(overall_score=500)
    cur = _req(
        overall_score=306,  # 500 + round(0.35 * -5 * 1000/9) = 500 - 194
        dimensions={"risk_match": 6.0, "risk_adjusted_return": 1.0, "downside_protection": 6.0},
        metrics={**_req().metrics, "sharpe_ratio": -0.4},
    )
    rep = build_change_report(cur, prev)
    assert rep.available is True
    assert rep.score_delta == 306 - 500
    rar = next(c for c in rep.component_deltas if c.key == "risk_adjusted_return")
    assert rar.delta == -5.0
    assert rar.points_contribution == round(0.35 * -5 * (1000 / 9))  # -194
    # The top driver is the risk-adjusted-return collapse.
    assert rep.top_drivers[0].key == "risk_adjusted_return"
    assert rep.top_drivers[0].points == rar.points_contribution
    # Components sum to the score delta (exact decomposition).
    assert sum(c.points_contribution or 0 for c in rep.component_deltas) == rep.score_delta


def test_input_changes_and_direction():
    prev = _snap(sharpe_ratio=0.8, annual_volatility=0.15)
    cur = _req(metrics={**_req().metrics, "sharpe_ratio": 0.4, "annual_volatility": 0.22})
    rep = build_change_report(cur, prev)
    by = {c.key: c for c in rep.input_changes}
    assert by["sharpe_ratio"].direction == "down"
    assert by["sharpe_ratio"].delta == -0.4
    assert by["annual_volatility"].direction == "up"


def test_data_quality_change_is_flagged():
    prev = _snap()  # confidence high
    cur = _req(confidence="low", dropped_tickers=["CCC"])
    rep = build_change_report(cur, prev)
    keys = {d.key for d in rep.data_quality_changes}
    assert "confidence" in keys
    assert "missing_prices" in keys
    # The summary surfaces the data-quality note.
    assert "confidence" in rep.summary.lower() or "missing" in rep.summary.lower()


def test_holdings_diff_added_removed_reweighted():
    prev = _snap()  # AAA 0.5 / BBB 0.5
    cur = _req(top_positions=[{"ticker": "AAA", "weight": 0.7}, {"ticker": "CCC", "weight": 0.3}])
    rep = build_change_report(cur, prev)
    assert rep.holdings_changes.added == ["CCC"]
    assert rep.holdings_changes.removed == ["BBB"]
    rw = {r["ticker"]: r for r in rep.holdings_changes.reweighted}
    assert rw["AAA"]["delta"] == 0.2


def test_endpoint_is_auth_gated(test_client):
    resp = test_client.post("/api/v1/risk/score_changes", json={"overall_score": 500})
    assert resp.status_code == 401
