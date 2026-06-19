"""portfolio_hash + the deterministic risk / scenario / copilot context caches.

Headline proof (per the brief): **a holdings change invalidates the cache** —
``portfolio_hash`` changes ⇒ the key changes ⇒ the producer re-runs. Plus the two
guardrails: user-private caches require ``user_id`` in the key, and an LLM
response is never cached without a ``context_hash``.

The shared cache is reset before each test by the conftest autouse fixture.
"""

from __future__ import annotations

import json

import pytest

from backend.app.services import cache_keys as ck
from backend.app.services import context_cache as cc
from libs.mindmarket_core.portfolio_scoring import (
    DimensionScore,
    PortfolioMetrics,
    PortfolioScore,
)

H1 = {
    "AAPL": {"shares": 10, "avg_cost": 150.0, "asset_type": "equity"},
    "MSFT": {"shares": 5, "avg_cost": 300.0, "asset_type": "equity"},
}
H1_REORDERED = {
    "MSFT": {"shares": 5, "avg_cost": 300.0, "asset_type": "equity"},
    "AAPL": {"shares": 10.0, "avg_cost": 150.0, "asset_type": "equity"},  # 10 vs 10.0
}
H_ADDED = {**H1, "NVDA": {"shares": 2, "avg_cost": 400.0, "asset_type": "equity"}}
H_SHARES = {**H1, "AAPL": {"shares": 20, "avg_cost": 150.0, "asset_type": "equity"}}


def _mk_score(overall: int = 720) -> PortfolioScore:
    metrics = PortfolioMetrics(
        annual_return=0.1,
        annual_volatility=0.15,
        sharpe_ratio=0.8,
        max_drawdown=-0.2,
        var_95_daily=-0.02,
        cvar_95_daily=-0.03,
        beta_to_benchmark=1.1,
        total_value=100000.0,
        cash_weight=0.1,
        data_coverage=0.95,
        observations=250,
        data_quality_notes=("synthetic", "second-note"),
        leverage=1.0,
        gross_annual_return=0.1,  # finite (default is nan → nan != nan breaks ==)
        margin_cost_annual=0.0,
    )
    dims = {"risk_match": DimensionScore(name="Risk Match", score=7.0, status="good", detail="ok")}
    return PortfolioScore(
        overall_score=overall,
        risk_preference=3,
        risk_target={"label": "Balanced", "annual_volatility": 0.14, "beta": 0.8},
        metrics=metrics,
        dimensions=dims,
    )


# ── portfolio_hash: the invalidation primitive ──────────────────────────────


def test_portfolio_hash_deterministic_and_order_independent():
    assert ck.portfolio_hash(H1) == ck.portfolio_hash(H1_REORDERED)  # order + 10 vs 10.0


def test_portfolio_hash_changes_when_holdings_change():
    base = ck.portfolio_hash(H1)
    assert ck.portfolio_hash(H_ADDED) != base  # ticker added
    assert ck.portfolio_hash(H_SHARES) != base  # share count changed
    cost = {**H1, "AAPL": {"shares": 10, "avg_cost": 999.0, "asset_type": "equity"}}
    assert ck.portfolio_hash(cost) != base  # avg cost changed
    atype = {**H1, "AAPL": {"shares": 10, "avg_cost": 150.0, "asset_type": "option"}}
    assert ck.portfolio_hash(atype) != base  # asset type changed
    removed = {"AAPL": H1["AAPL"]}
    assert ck.portfolio_hash(removed) != base  # ticker removed


def test_portfolio_hash_option_terms_change_the_hash():
    a = {
        "AAPL260116C00150000": {
            "shares": 1,
            "asset_type": "option",
            "strike": 150.0,
            "option_side": "long",
        }
    }
    b = {
        "AAPL260116C00150000": {
            "shares": 1,
            "asset_type": "option",
            "strike": 160.0,
            "option_side": "long",
        }
    }
    c = {
        "AAPL260116C00150000": {
            "shares": 1,
            "asset_type": "option",
            "strike": 150.0,
            "option_side": "short",
        }
    }
    assert ck.portfolio_hash(a) != ck.portfolio_hash(b)  # strike
    assert ck.portfolio_hash(a) != ck.portfolio_hash(c)  # side


def test_market_data_hash_changes_with_prices():
    base = ck.market_data_hash({"AAPL": 150.0, "MSFT": 300.0})
    assert ck.market_data_hash({"AAPL": 150.0, "MSFT": 300.0}) == base  # deterministic
    assert ck.market_data_hash({"AAPL": 151.0, "MSFT": 300.0}) != base  # price moved


# ── key-builder guardrails ──────────────────────────────────────────────────


def test_user_private_keys_require_user_id():
    with pytest.raises(ValueError):
        cc.risk_score_key("", "phash", "mhash")
    with pytest.raises(ValueError):
        cc.copilot_context_key(None, "phash")
    # scenario key is deliberately user-id-free
    assert cc.scenario_key("phash", {"x": 1}).startswith("mm:risk:scenarios:")


def test_risk_and_copilot_keys_isolate_users():
    p = ck.portfolio_hash(H1)
    assert cc.risk_score_key("u1", p, "m") != cc.risk_score_key("u2", p, "m")
    assert cc.copilot_context_key("u1", p) != cc.copilot_context_key("u2", p)


# ── score (de)serialization round-trip (de-risks the cached score path) ─────


def test_score_dict_round_trip_is_faithful():
    s = _mk_score(715)
    restored = cc.score_from_dict(json.loads(json.dumps(cc.score_to_dict(s))))
    assert cc.score_to_dict(restored) == cc.score_to_dict(s)
    assert restored.metrics.data_quality_notes == ("synthetic", "second-note")  # tuple preserved


# ── cached risk score: hit avoids producer; holdings change invalidates ─────


def test_cached_risk_score_hit_and_holdings_change_invalidates():
    calls = {"n": 0}

    def producer():
        calls["n"] += 1
        return _mk_score(700 + calls["n"])

    md = {"AAPL": 150.0, "MSFT": 300.0}
    s1, r1 = cc.cached_risk_score(
        user_id="u1", holdings=H1, market_data=md, params={}, producer=producer
    )
    s2, r2 = cc.cached_risk_score(
        user_id="u1", holdings=H1_REORDERED, market_data=md, params={}, producer=producer
    )
    assert calls["n"] == 1  # identical book (reordered) → cache hit, no recompute
    assert r2.cache_hit is True and s2.overall_score == s1.overall_score == 701

    # Holdings change → portfolio_hash changes → key changes → recompute.
    s3, r3 = cc.cached_risk_score(
        user_id="u1", holdings=H_SHARES, market_data=md, params={}, producer=producer
    )
    assert calls["n"] == 2 and r3.cache_hit is False and s3.overall_score == 702


def test_cached_risk_score_market_data_change_invalidates():
    calls = {"n": 0}

    def producer():
        calls["n"] += 1
        return _mk_score(700 + calls["n"])

    cc.cached_risk_score(
        user_id="u1", holdings=H1, market_data={"AAPL": 150.0}, params={}, producer=producer
    )
    cc.cached_risk_score(
        user_id="u1", holdings=H1, market_data={"AAPL": 151.0}, params={}, producer=producer
    )
    assert calls["n"] == 2  # a new market snapshot busts the cache


# ── cached scenarios: hit avoids producer; holdings change invalidates ──────


def test_cached_scenarios_hit_and_holdings_change_invalidates():
    calls = {"n": 0}

    def producer():
        calls["n"] += 1
        return {"scenarios": [{"shock_pct": -0.1, "pnl_pct": -0.12}], "run": calls["n"]}

    params = {"history_days": 365, "shocks": [-0.1, -0.2]}
    r1 = cc.cached_scenarios(holdings=H1, scenario_params=params, producer=producer)
    r2 = cc.cached_scenarios(holdings=H1_REORDERED, scenario_params=params, producer=producer)
    assert calls["n"] == 1 and r2.cache_hit is True and r1.value["run"] == 1  # same book → hit

    cc.cached_scenarios(holdings=H_ADDED, scenario_params=params, producer=producer)
    assert calls["n"] == 2  # holdings changed → recompute

    cc.cached_scenarios(
        holdings=H1, scenario_params={**params, "history_days": 730}, producer=producer
    )
    assert calls["n"] == 3  # scenario params changed → recompute


# ── cached copilot context: hit; holdings change invalidates; reconstructs ──


def test_cached_copilot_context_hit_and_holdings_change_invalidates():
    from libs.mindmarket_core.portfolio_scoring import AssetPosition

    calls = {"n": 0}

    def producer():
        calls["n"] += 1
        positions = [
            AssetPosition(ticker="AAPL", name="Apple", asset_type="equity", market_value=1500.0)
        ]
        return positions, _mk_score(700 + calls["n"])

    pos1, sc1, r1 = cc.cached_copilot_context(user_id="u1", holdings=H1, producer=producer)
    pos2, sc2, r2 = cc.cached_copilot_context(
        user_id="u1", holdings=H1_REORDERED, producer=producer
    )
    assert calls["n"] == 1 and r2.cache_hit is True  # same book → hit
    assert sc2.overall_score == 701 and pos2[0].ticker == "AAPL"  # reconstructed faithfully

    pos3, sc3, r3 = cc.cached_copilot_context(user_id="u1", holdings=H_ADDED, producer=producer)
    assert calls["n"] == 2 and r3.cache_hit is False and sc3.overall_score == 702


def test_cached_copilot_context_keyed_by_user():
    def producer():
        from libs.mindmarket_core.portfolio_scoring import AssetPosition

        return [
            AssetPosition(ticker="AAPL", name="Apple", asset_type="equity", market_value=1.0)
        ], _mk_score()

    calls = {"n": 0}

    def counting():
        calls["n"] += 1
        return producer()

    cc.cached_copilot_context(user_id="u1", holdings=H1, producer=counting)
    cc.cached_copilot_context(user_id="u2", holdings=H1, producer=counting)
    assert calls["n"] == 2  # same book, different user → separate cache entries


# ── LLM-response guardrail: never cache without a context_hash ──────────────


def test_cache_llm_response_refuses_without_context_hash():
    with pytest.raises(ValueError):
        cc.cache_llm_response(context_hash="", producer=lambda: {"a": 1}, ttl=60)


def test_cache_llm_response_caches_keyed_on_context_hash():
    calls = {"n": 0}

    def producer():
        calls["n"] += 1
        return {"answer": "x"}

    ch = cc.context_hash("u1", ck.portfolio_hash(H1), "what is my risk?")
    r1 = cc.cache_llm_response(context_hash=ch, producer=producer, ttl=60)
    r2 = cc.cache_llm_response(context_hash=ch, producer=producer, ttl=60)
    assert calls["n"] == 1 and r2.cache_hit is True and r1.value == {"answer": "x"}

    other = cc.context_hash("u1", ck.portfolio_hash(H_ADDED), "what is my risk?")
    cc.cache_llm_response(context_hash=other, producer=producer, ttl=60)
    assert calls["n"] == 2  # different context (changed portfolio) → new key → recompute
