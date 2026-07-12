"""Deterministic 'what changed?' engine + endpoint.

The score is a deterministic function of the dimension scores, so the overall
delta must decompose EXACTLY into per-dimension point contributions. These tests
prove the attribution, the input/data-quality/holdings diffs, and that an
unavailable snapshot degrades gracefully — all offline (no LLM, no DB)."""

from __future__ import annotations

from backend.app.schemas.score_changes import ScoreChangeRequest
from backend.app.services.score_changes import build_change_report
from libs.mindmarket_core.score_version import SCORE_VERSION


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
    version = rm.pop("score_version", SCORE_VERSION)
    risk_metrics.update(rm)
    return {
        "created_at": "2026-06-13T00:00:00+00:00",
        "score_version": version,
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


# ── PR B: market / holding / data-quality attribution ──────────────────────────
def test_top_positive_and_negative_contributors():
    prev = _snap(
        dimensions={"risk_match": 7.0, "risk_adjusted_return": 6.0, "downside_protection": 6.0}
    )
    req = _req(
        overall_score=480,
        dimensions={"risk_match": 5.0, "risk_adjusted_return": 7.0, "downside_protection": 6.0},
    )
    r = build_change_report(req, prev)
    assert r.top_negative_contributor is not None
    assert r.top_negative_contributor.key == "risk_match" and r.top_negative_contributor.points < 0
    assert r.top_positive_contributor is not None
    assert r.top_positive_contributor.key == "risk_adjusted_return"


def test_attribution_market_driven_on_no_trade_day():
    """Same holdings, the raw (base) score fell → the move is 100% market."""
    prev = _snap(overall_score=700, base_overall=700)
    req = _req(
        overall_score=650,
        base_overall=650,
        dimensions={"risk_match": 5.5, "risk_adjusted_return": 6.0, "downside_protection": 6.0},
    )
    r = build_change_report(req, prev)
    a = r.attribution
    assert a is not None and a.separable is True
    assert a.market_driven == r.score_delta  # all of it
    assert a.holding_driven == 0 and a.data_quality_driven == 0


def test_attribution_data_quality_driven_not_the_portfolio():
    """Confidence collapsed → dampening pulled the score down while the raw
    (base) score barely moved. The drop must attribute to DATA QUALITY, not the
    portfolio — the req-1 separation made concrete."""
    prev = _snap(overall_score=715, base_overall=715)
    req = _req(
        overall_score=630,
        base_overall=710,  # raw score almost unchanged
        confidence="low",
    )
    r = build_change_report(req, prev)
    a = r.attribution
    assert a is not None
    assert a.data_quality_driven <= -60  # the bulk of the −85 move
    assert abs(a.market_driven) <= 10  # the portfolio itself barely moved
    assert "data-quality" in a.note


def test_attribution_trade_day_is_not_separable():
    prev = _snap(overall_score=650, base_overall=650)
    req = _req(
        overall_score=640,
        base_overall=640,
        top_positions=[{"ticker": "AAA", "weight": 0.2}, {"ticker": "NVDA", "weight": 0.8}],
    )
    r = build_change_report(req, prev)
    a = r.attribution
    assert a.separable is False
    assert a.market_driven is None and a.holding_driven is None
    assert a.combined_market_holdings == r.score_delta - a.data_quality_driven


def test_attribution_exact_identity_all_buckets_sum_to_delta():
    prev = _snap(
        overall_score=700,
        base_overall=720,
        dimensions={"risk_match": 7.0, "risk_adjusted_return": 7.0, "downside_protection": 7.0},
    )
    req = _req(
        overall_score=650,
        base_overall=705,
        dimensions={"risk_match": 6.8, "risk_adjusted_return": 7.0, "downside_protection": 7.0},
        confidence="medium",
    )
    r = build_change_report(req, prev)
    a = r.attribution
    total = a.data_quality_driven + (a.market_driven or 0) + (a.holding_driven or 0)
    assert total == r.score_delta


def test_attribution_option_penalty_is_holding_driven():
    """A bigger option penalty (same book, same prices, same confidence) is a
    HOLDING-side move, peeled out of the data-quality bucket."""
    prev = _snap(overall_score=580, base_overall=600, option_penalty=20)
    req = _req(
        overall_score=570,
        base_overall=600,
        option_penalty=30,
    )
    r = build_change_report(req, prev)
    a = r.attribution
    assert a.data_quality_driven == 0  # dampening unchanged
    assert a.holding_driven == -10  # the +10 penalty costs 10 pts
    assert a.market_driven == 0
    assert a.data_quality_driven + a.market_driven + a.holding_driven == r.score_delta


def test_attribution_unknown_current_penalty_folds_into_data_quality():
    """When the client doesn't send option_penalty, the penalty change must NOT
    be mis-attributed — it folds into data_quality rather than inventing a
    holding move."""
    prev = _snap(overall_score=580, base_overall=600, option_penalty=20)
    req = _req(overall_score=600, base_overall=600)  # option_penalty defaults None
    r = build_change_report(req, prev)
    a = r.attribution
    assert a.holding_driven == 0  # not invented
    assert a.data_quality_driven + a.market_driven + a.holding_driven == r.score_delta


# ── PR B / req-1: a low-quality dataset must never LOOK more unhealthy ──────────
def test_low_data_quality_only_pulls_a_weak_score_toward_neutral():
    """Health Score is separated from Data Confidence: poor data can only
    stabilize a weak dimension TOWARD neutral (less unhealthy-looking), never
    push it below its raw value. This is the engine guarantee behind req-1."""
    from libs.mindmarket_core import portfolio_scoring as ps

    weak_raw = 2.0  # a genuinely unhealthy raw dimension
    fidelity_full = ps._score_fidelity(0.90)  # good data → undamped
    fidelity_low = ps._score_fidelity(0.25)  # poor data → damped toward neutral

    damped_full = ps._dampen_dimension(weak_raw, fidelity_full)
    damped_low = ps._dampen_dimension(weak_raw, fidelity_low)

    assert damped_full == weak_raw  # full data leaves the (bad) score untouched
    assert damped_low > weak_raw  # poor data pulls it UP toward neutral
    assert damped_low <= ps._NEUTRAL_DIM  # but never past neutral
