"""Contract tests for ``POST /api/v1/copilot/chat``.

Asserts:
  * Auth required (401 without bearer).
  * Empty active portfolio → 422 ``no_active_portfolio``.
  * Happy path (LLM degraded to None) → 200 with non-empty markdown
    + a ``grounded_in`` dict.
  * Happy path with a fake LLM callable → 200 (route still succeeds).
  * Quota exhausted → 429 ``quota_exceeded``.

Hermetic: mocks the Supabase resolver, the market-data service, the
quota gate, and the LLM seam so the suite stays fast + offline. Mirrors
the fixture style of ``test_score_from_active.py``."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


@pytest.fixture
def fake_active_portfolio(monkeypatch):
    """Patch ``libs.auth.active_portfolio.get_active_holdings`` so the
    Copilot context loader doesn't hit Supabase."""

    class _Stub:
        def __init__(self) -> None:
            self.holdings: dict[str, dict] = {}
            self.calls: list[str | None] = []

        def set(self, holdings: dict[str, dict]) -> None:
            self.holdings = holdings

        def __call__(self, access_token=None):
            self.calls.append(access_token)
            return dict(self.holdings)

    stub = _Stub()
    import libs.auth.active_portfolio as ap

    monkeypatch.setattr(ap, "get_active_holdings", stub)
    return stub


@pytest.fixture
def fake_price_history(monkeypatch):
    """Patch ``backend.app.services.market_data.get_price_history``."""

    class _Stub:
        def __init__(self) -> None:
            self.frame: pd.DataFrame = pd.DataFrame()
            self.calls: list[list[str]] = []

        def set(self, frame: pd.DataFrame) -> None:
            self.frame = frame

        def __call__(self, tickers, *, days=365, cache_provider=None):
            self.calls.append(list(tickers))
            cols = [t for t in tickers if t in self.frame.columns]
            return self.frame[cols] if cols else pd.DataFrame()

    stub = _Stub()
    from backend.app.services import market_data as md

    monkeypatch.setattr(md, "get_price_history", stub)
    return stub


@pytest.fixture
def fake_quota(monkeypatch):
    """Patch the credit gate ``libs.billing.usage.check_credits`` (the chat
    endpoints' primary limiter) + silence ``record_event`` so cost logging
    doesn't hit Supabase. Defaults to allow; ``.deny()`` → QuotaExceeded."""

    import libs.billing.usage as usage

    class _Stub:
        def __init__(self) -> None:
            self.denied = False
            self.calls: list[tuple] = []

        def deny(self) -> None:
            self.denied = True

        def __call__(self, user_id, *, email=None, estimated_cost_usd=0.0):
            self.calls.append((user_id, estimated_cost_usd, email))
            if self.denied:
                raise usage.QuotaExceeded(
                    kind="credits", plan="free", used=25, limit=25, message="Out of AI credits."
                )
            return {"credits_remaining": 100}

    stub = _Stub()
    monkeypatch.setattr(usage, "check_credits", stub)
    monkeypatch.setattr(usage, "record_event", lambda *a, **k: None)
    return stub


@pytest.fixture
def fake_llm(monkeypatch):
    """Patch ``backend.app.services.llm_client.get_llm_callable`` so we
    control degraded (None) vs. live-LLM behaviour. Defaults to None
    (deterministic templates)."""

    import backend.app.services.llm_client as llm_mod

    state = {"callable": None}

    def _get(*, with_tools=False):
        return state["callable"]

    # Patch where the router imported it (it does ``from ...services.
    # llm_client import get_llm_callable``), so patch the binding on the
    # router module too.
    import backend.app.api.v1.copilot as copilot_mod

    monkeypatch.setattr(llm_mod, "get_llm_callable", _get)
    monkeypatch.setattr(copilot_mod, "get_llm_callable", _get)
    return state


def _make_history(tickers: list[str], days: int = 260) -> pd.DataFrame:
    """Deterministic price history — geometric random walk around 100."""
    rng = np.random.default_rng(7)
    idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=days)
    data: dict[str, np.ndarray] = {}
    for tk in tickers:
        returns = rng.normal(0.0003, 0.01, days)
        data[tk] = 100.0 * np.exp(np.cumsum(returns))
    return pd.DataFrame(data, index=idx)


# ── auth gate ──────────────────────────────────────────────────────


def test_requires_bearer_token(test_client):
    resp = test_client.post("/api/v1/copilot/chat", json={"message": "hi"})
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "unauthorized"


# ── empty data path ────────────────────────────────────────────────


def test_no_active_portfolio_returns_422_with_specific_code(
    test_client, mint_token, fake_active_portfolio
):
    fake_active_portfolio.set({})  # signed-in but no holdings
    resp = test_client.post(
        "/api/v1/copilot/chat",
        json={"message": "diagnose my risk"},
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "no_active_portfolio"


# ── happy paths ────────────────────────────────────────────────────


def test_happy_path_degraded_templates(
    test_client, mint_token, fake_active_portfolio, fake_price_history, fake_quota, fake_llm
):
    """LLM unavailable (None) → orchestrator uses deterministic templates.
    We still get a 200 with non-empty markdown + a grounded_in dict."""
    fake_active_portfolio.set(
        {
            "SPY": {"shares": 100, "avg_cost": 400.0},
            "BND": {"shares": 50, "avg_cost": 70.0},
        }
    )
    fake_price_history.set(_make_history(["BND", "SPY"]))
    fake_llm["callable"] = None  # degraded mode

    token = mint_token(sub="user-degraded")
    resp = test_client.post(
        "/api/v1/copilot/chat",
        json={"message": "diagnose my risk"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.json()
    data = resp.json()["data"]
    assert data["response_markdown"].strip()  # non-empty
    assert isinstance(data["grounded_in"], dict) and data["grounded_in"]
    # The caller's JWT was forwarded to the active-portfolio resolver.
    assert fake_active_portfolio.calls == [token]
    # Quota was consumed for the chat kind.
    assert len(fake_quota.calls) == 1 and fake_quota.calls[0][0] == "user-degraded"


def test_happy_path_with_live_llm(
    test_client, mint_token, fake_active_portfolio, fake_price_history, fake_quota, fake_llm
):
    """A fake LLM callable returning a canned string → the route still
    succeeds (200). The orchestrator decides whether/how to use the
    callable; we just prove the wiring passes it through cleanly."""
    fake_active_portfolio.set({"SPY": {"shares": 100, "avg_cost": 400.0}})
    fake_price_history.set(_make_history(["SPY"]))

    canned = "Your portfolio looks well diversified."

    def _fake_call(prompt, system, max_tokens, temperature):
        return canned

    fake_llm["callable"] = _fake_call

    resp = test_client.post(
        "/api/v1/copilot/chat",
        json={"message": "how am I doing?"},
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    assert resp.status_code == 200, resp.json()
    data = resp.json()["data"]
    assert data["response_markdown"].strip()
    assert isinstance(data["grounded_in"], dict)


def test_quota_exceeded_returns_429(
    test_client, mint_token, fake_active_portfolio, fake_price_history, fake_quota, fake_llm
):
    fake_active_portfolio.set({"SPY": {"shares": 100, "avg_cost": 400.0}})
    fake_price_history.set(_make_history(["SPY"]))
    fake_quota.deny()

    resp = test_client.post(
        "/api/v1/copilot/chat",
        json={"message": "diagnose my risk"},
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    assert resp.status_code == 429
    assert resp.json()["error"]["code"] == "quota_exceeded"


# ── streaming (SSE) ────────────────────────────────────────────────


@pytest.fixture
def fake_streamer(monkeypatch):
    """Patch the binding the stream endpoint uses
    (``copilot.get_answer_streamer``). Default: a 2-chunk fake stream."""
    import backend.app.api.v1.copilot as copilot_mod

    state = {"chunks": ["Hello", " world"], "enabled": True}

    def _get():
        if not state["enabled"]:
            return None  # simulates no API key → template fallback

        def _stream(prompt, system, max_tokens, temperature):
            for c in state["chunks"]:
                yield c

        return _stream

    monkeypatch.setattr(copilot_mod, "get_answer_streamer", _get)
    return state


def test_stream_requires_bearer_token(test_client):
    resp = test_client.post("/api/v1/copilot/chat/stream", json={"message": "hi"})
    assert resp.status_code == 401


def test_stream_happy_path_emits_delta_and_done(
    test_client, mint_token, fake_active_portfolio, fake_price_history, fake_quota, fake_streamer
):
    fake_active_portfolio.set({"SPY": {"shares": 100, "avg_cost": 400.0}})
    fake_price_history.set(_make_history(["SPY"]))

    resp = test_client.post(
        "/api/v1/copilot/chat/stream",
        json={"message": "how risky am I?"},
        headers={"Authorization": f"Bearer {mint_token(sub='user-stream')}"},
    )
    assert resp.status_code == 200
    body = resp.text
    assert "event: status" in body
    assert "event: delta" in body
    assert "Hello" in body and "world" in body
    assert "event: done" in body
    assert "grounded_in" in body
    # the LLM streamed real text → the answer is labeled AI-generated
    assert '"ai_generated": true' in body
    # quota consumed for chat
    assert fake_quota.calls and fake_quota.calls[0][0] == "user-stream"


def test_stream_no_portfolio_emits_error_event(
    test_client, mint_token, fake_active_portfolio, fake_streamer
):
    fake_active_portfolio.set({})  # signed in, no holdings
    resp = test_client.post(
        "/api/v1/copilot/chat/stream",
        json={"message": "hi"},
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    # Stream already started → 200, the failure is an SSE error event.
    assert resp.status_code == 200
    assert "event: error" in resp.text
    assert "no_active_portfolio" in resp.text


def test_stream_degraded_template_when_no_streamer(
    test_client, mint_token, fake_active_portfolio, fake_price_history, fake_quota, fake_streamer
):
    fake_active_portfolio.set({"SPY": {"shares": 100, "avg_cost": 400.0}})
    fake_price_history.set(_make_history(["SPY"]))
    fake_streamer["enabled"] = False  # no API key → template fallback

    resp = test_client.post(
        "/api/v1/copilot/chat/stream",
        json={"message": "diagnose my risk"},
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    assert resp.status_code == 200
    body = resp.text
    assert "event: delta" in body and "event: done" in body  # template still streamed as one delta


def test_stream_empty_yield_falls_back_to_template(
    test_client, mint_token, fake_active_portfolio, fake_price_history, fake_quota, fake_streamer
):
    """A streamer that completes WITHOUT yielding any text (e.g. the model
    spent every tool turn without composing an answer) must still produce a
    non-empty answer via the template — never a silent blank `done`."""
    fake_active_portfolio.set({"SPY": {"shares": 100, "avg_cost": 400.0}})
    fake_price_history.set(_make_history(["SPY"]))
    fake_streamer["chunks"] = []  # streamer yields nothing, raises nothing

    resp = test_client.post(
        "/api/v1/copilot/chat/stream",
        json={"message": "diagnose my risk"},
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    assert resp.status_code == 200
    body = resp.text
    # The fallback template delta carries real content (a score/assessment),
    # so `delta` is present and non-trivial, and `done` still closes the stream.
    assert "event: delta" in body and "event: done" in body
    assert 'data: {"text": ""}' not in body  # not an empty delta
    # nothing streamed from the model → labeled as the deterministic fallback
    assert '"ai_generated": false' in body
