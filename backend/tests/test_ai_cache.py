"""AI response cache: unit behavior + endpoint wiring.

The product rule is "cache AI summaries by input hash for 30-60 minutes".
These tests pin the load-bearing properties:

* a cache hit returns the stored response WITHOUT re-calling the LLM
* a cache hit is served BEFORE the credit gate (repeat questions are free)
* only real AI output is cached (deterministic fallbacks are not)
* /copilot/ask keys per-user (evidence folds in the caller's portfolio)
"""

from __future__ import annotations

import json

from backend.app.services.ai_cache import AiResponseCache

# ── unit ───────────────────────────────────────────────────────────────


def test_put_get_roundtrip():
    cache = AiResponseCache(ttl_seconds=60)
    cache.put("k", {"a": 1})
    assert cache.get("k") == {"a": 1}


def test_expired_entry_is_a_miss():
    cache = AiResponseCache(ttl_seconds=-1)  # everything is born expired
    cache.put("k", {"a": 1})
    assert cache.get("k") is None


def test_lru_eviction_drops_oldest():
    cache = AiResponseCache(ttl_seconds=60, max_entries=2)
    cache.put("a", 1)
    cache.put("b", 2)
    cache.get("a")  # touch "a" so "b" is now least-recently-used
    cache.put("c", 3)
    assert cache.get("a") == 1
    assert cache.get("b") is None
    assert cache.get("c") == 3


def test_reset_clears_entries():
    cache = AiResponseCache(ttl_seconds=60)
    cache.put("k", 1)
    cache.reset()
    assert cache.get("k") is None


# ── /risk/explain ──────────────────────────────────────────────────────


def _auth(mint_token, **overrides):
    return {"Authorization": f"Bearer {mint_token(**overrides)}"}


_EXPLAIN_BODY = {
    "source": "score",
    "overall_score": 512,
    "annual_volatility": 0.34,
    "var_95_daily": -0.028,
}

_EXPLAIN_JSON = json.dumps(
    {
        "headline": "Concentration is your main risk right now.",
        "summary_bullets": ["NVDA dominates your VaR."],
        "watch_items": [],
        "suggested_actions": [],
        "caveats": ["Educational only."],
    }
)


def test_explain_second_identical_call_skips_llm(test_client, mint_token, monkeypatch):
    from backend.app.services import llm_client

    calls = {"n": 0}

    def fake_callable(*, prompt, system, max_tokens, temperature):
        calls["n"] += 1
        return _EXPLAIN_JSON

    monkeypatch.setattr(llm_client, "get_llm_callable", lambda *a, **k: fake_callable)
    monkeypatch.setattr("backend.app.api.v1.risk._record_explain_cost", lambda *a, **k: None)

    first = test_client.post("/api/v1/risk/explain", json=_EXPLAIN_BODY, headers=_auth(mint_token))
    second = test_client.post("/api/v1/risk/explain", json=_EXPLAIN_BODY, headers=_auth(mint_token))
    assert first.status_code == second.status_code == 200
    assert calls["n"] == 1
    assert second.json()["data"] == first.json()["data"]
    assert second.json()["data"]["ai_generated"] is True


def test_explain_template_output_is_not_cached(test_client, mint_token, monkeypatch):
    from backend.app.services import llm_client

    # No LLM key → deterministic template; must NOT be cached.
    monkeypatch.setattr(llm_client, "get_llm_callable", lambda *a, **k: None)
    r1 = test_client.post("/api/v1/risk/explain", json=_EXPLAIN_BODY, headers=_auth(mint_token))
    assert r1.json()["data"]["ai_generated"] is False

    # Key recovers → the same input must reach the real model, not the cache.
    monkeypatch.setattr(llm_client, "get_llm_callable", lambda *a, **k: (lambda **_: _EXPLAIN_JSON))
    monkeypatch.setattr("backend.app.api.v1.risk._record_explain_cost", lambda *a, **k: None)
    r2 = test_client.post("/api/v1/risk/explain", json=_EXPLAIN_BODY, headers=_auth(mint_token))
    assert r2.json()["data"]["ai_generated"] is True


# ── /research/verdict ──────────────────────────────────────────────────


class _FakeVerdict:
    data_only = False

    def model_dump(self):
        return {"rating": "hold", "data_only": False}


def test_verdict_cache_hit_skips_llm_and_credit_gate(test_client, mint_token, monkeypatch):
    from backend.app.services import llm_client, research_factpack

    calls = {"n": 0}

    def fake_build_verdict(fp, llm_callable=None):
        calls["n"] += 1
        return _FakeVerdict()

    monkeypatch.setattr(research_factpack, "build_verdict", fake_build_verdict)
    monkeypatch.setattr(llm_client, "get_llm_callable", lambda *a, **k: (lambda **_: "x"))
    monkeypatch.setattr("backend.app.api.v1.research._record_verdict_cost", lambda *a, **k: None)

    body = {"fact_pack": {"ticker": "AAPL"}}
    first = test_client.post("/api/v1/research/verdict", json=body, headers=_auth(mint_token))
    assert first.status_code == 200, first.json()
    assert calls["n"] == 1

    # Out of credits now — the cached answer must still be served (free).
    from libs.billing.usage import QuotaExceeded

    def no_credits(*a, **k):
        raise QuotaExceeded("analysis", "free", 25, 25)

    monkeypatch.setattr("libs.billing.usage.check_credits", no_credits)

    second = test_client.post("/api/v1/research/verdict", json=body, headers=_auth(mint_token))
    assert second.status_code == 200, second.json()
    assert calls["n"] == 1
    assert second.json()["data"]["verdict"] == first.json()["data"]["verdict"]

    # A DIFFERENT FactPack misses the cache and now hits the (exhausted) gate.
    third = test_client.post(
        "/api/v1/research/verdict",
        json={"fact_pack": {"ticker": "MSFT"}},
        headers=_auth(mint_token),
    )
    assert third.status_code == 429


# ── /copilot/ask ───────────────────────────────────────────────────────


class _FakeAsk:
    data_only = False

    def model_dump(self):
        return {"intent": "macro", "answer_markdown": "cached answer"}


def test_ask_cache_is_user_scoped(test_client, mint_token, monkeypatch):
    from backend.app.api.v1 import copilot as copilot_api
    from backend.app.services import copilot_router

    calls = {"n": 0}

    def fake_answer(message, *, user, llm_callable, route=None, ticker=None):
        calls["n"] += 1
        return _FakeAsk()

    monkeypatch.setattr(copilot_router, "answer", fake_answer)
    monkeypatch.setattr(copilot_api, "get_llm_callable", lambda *a, **k: (lambda **_: "x"))
    monkeypatch.setattr(copilot_api, "_record_ask_cost", lambda *a, **k: None)

    body = {"message": "How risky is my portfolio?"}
    a1 = test_client.post("/api/v1/copilot/ask", json=body, headers=_auth(mint_token))
    a2 = test_client.post("/api/v1/copilot/ask", json=body, headers=_auth(mint_token))
    assert a1.status_code == a2.status_code == 200
    assert calls["n"] == 1  # same user + same message → cache hit

    # Different user, same message → must NOT share the cached answer.
    b1 = test_client.post(
        "/api/v1/copilot/ask", json=body, headers=_auth(mint_token, sub="user-other-999")
    )
    assert b1.status_code == 200
    assert calls["n"] == 2
