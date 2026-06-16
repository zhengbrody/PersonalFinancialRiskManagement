"""Tests for the macro-news + per-holding AI-sentiment endpoints.

Hermetic: the RSS aggregator, yfinance headline fetch, LLM seam, active
portfolio, and quota gate are all monkeypatched.
"""

from __future__ import annotations

import json

import pytest


@pytest.fixture(autouse=True)
def _reset_caches():
    from backend.app.services import market_news, market_sentiment

    market_news.reset_cache()
    market_sentiment.reset_cache()
    yield
    market_news.reset_cache()
    market_sentiment.reset_cache()


def _auth(mint_token):
    return {"Authorization": f"Bearer {mint_token()}"}


# ── news (public) ───────────────────────────────────────────────────


def test_news_public_and_shaped(test_client, monkeypatch):
    import market_intelligence as mi

    monkeypatch.setattr(
        mi,
        "get_all_macro_news",
        lambda max_items=30: [
            {
                "source": "Reuters",
                "title": "Fed holds rates",
                "link": "http://x",
                "published": "t",
                "summary": "s",
            },
            {
                "source": "Yahoo Finance (SPY)",
                "title": "Stocks drift after Fed decision",
                "link": "http://y",
                "published": "t",
                "summary": "s",
            },
            {
                "source": "",
                "title": "",
                "link": "",
                "published": "",
                "summary": "",
            },  # dropped (no title)
        ],
    )
    resp = test_client.get("/api/v1/macro/news")
    assert resp.status_code == 200, resp.json()
    data = resp.json()["data"]
    items = data["items"]
    assert len(items) == 2
    assert items[0]["title"] == "Fed holds rates"
    sources = data["sources"]
    assert {s["label"] for s in sources} == {"Reuters", "Yahoo Finance"}
    assert any(s["role"] == "fallback" and s["provider"] == "yfinance" for s in sources)


def test_news_fail_soft(test_client, monkeypatch):
    import market_intelligence as mi

    def boom(max_items=30):
        raise RuntimeError("rss down")

    monkeypatch.setattr(mi, "get_all_macro_news", boom)
    resp = test_client.get("/api/v1/macro/news")
    assert resp.status_code == 200
    assert resp.json()["data"]["items"] == []
    assert resp.json()["data"]["sources"] == []


# ── sentiment (authed + credit-gated) ───────────────────────────────


@pytest.fixture
def fake_active(monkeypatch):
    import libs.auth.active_portfolio as ap

    monkeypatch.setattr(
        ap,
        "get_active_holdings",
        lambda access_token=None: {"NVDA": {"shares": 1}, "MSFT": {"shares": 1}},
    )


@pytest.fixture
def fake_headlines(monkeypatch):
    from backend.app.services import market_sentiment as ms

    monkeypatch.setattr(
        ms, "_fetch_headlines", lambda t: [f"{t} beats earnings", f"{t} raises guidance"]
    )


@pytest.fixture
def allow_credits(monkeypatch):
    import libs.billing.usage as usage

    monkeypatch.setattr(usage, "check_credits", lambda *a, **k: {"ok": True})
    monkeypatch.setattr(usage, "record_event", lambda *a, **k: None)


def test_sentiment_requires_bearer(test_client):
    assert test_client.post("/api/v1/market/sentiment").status_code == 401


def test_sentiment_neutral_without_llm(
    test_client, mint_token, fake_active, fake_headlines, allow_credits, monkeypatch
):
    from backend.app.services import llm_client

    monkeypatch.setattr(llm_client, "get_llm_callable", lambda *a, **k: None)
    resp = test_client.post("/api/v1/market/sentiment", headers=_auth(mint_token))
    assert resp.status_code == 200, resp.json()
    data = resp.json()["data"]
    assert data["ai_generated"] is False
    assert {s["ticker"] for s in data["sentiments"]} == {"NVDA", "MSFT"}
    assert all(s["score"] == 50 for s in data["sentiments"])  # neutral


def test_sentiment_scored_with_llm(
    test_client, mint_token, fake_active, fake_headlines, allow_credits, monkeypatch
):
    from backend.app.services import llm_client

    def fake_llm(*, prompt, system, max_tokens, temperature):
        return json.dumps({"score": 78, "label": "Bullish", "narrative": "Earnings momentum."})

    monkeypatch.setattr(llm_client, "get_llm_callable", lambda *a, **k: fake_llm)
    resp = test_client.post("/api/v1/market/sentiment", headers=_auth(mint_token))
    assert resp.status_code == 200, resp.json()
    data = resp.json()["data"]
    assert data["ai_generated"] is True
    s = data["sentiments"][0]
    assert s["score"] == 78 and s["label"] == "Bullish"


def test_sentiment_quota_exceeded(test_client, mint_token, fake_active, monkeypatch):
    import libs.billing.usage as usage

    def deny(*a, **k):
        raise usage.QuotaExceeded(
            kind="credits", plan="free", used=25, limit=25, message="out of credits"
        )

    monkeypatch.setattr(usage, "check_credits", deny)
    resp = test_client.post("/api/v1/market/sentiment", headers=_auth(mint_token))
    assert resp.status_code == 429


def test_sentiment_empty_portfolio(test_client, mint_token, monkeypatch):
    import libs.auth.active_portfolio as ap

    monkeypatch.setattr(ap, "get_active_holdings", lambda access_token=None: {})
    resp = test_client.post("/api/v1/market/sentiment", headers=_auth(mint_token))
    assert resp.status_code == 200
    assert resp.json()["data"]["sentiments"] == []
