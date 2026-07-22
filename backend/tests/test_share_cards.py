from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from backend.app.api.v1 import share_cards
from backend.app.core.config import Settings
from backend.app.core.deps_auth import AuthedUser, require_user
from backend.app.main import create_app
from backend.app.schemas.share_card import ShareCardPayload
from backend.app.services import share_card
from backend.app.services.rate_limit import TokenBucket

SECRET = "share-only-test-secret-that-is-at-least-32-bytes"
NOW = 1_784_000_000


@pytest.fixture(autouse=True)
def _reset_share_card_rate_limiters():
    share_cards.reset_rate_limiters()
    yield
    share_cards.reset_rate_limiters()


def _payload(**updates) -> ShareCardPayload:
    values = {
        "score_band": "healthy",
        "risk_fit": "aligned",
        "top_risk_category": "concentration",
        "stress_band": "10_to_20_pct",
        "confidence_label": "high",
        "as_of": "2026-07-21",
        "model_version": "score-v1",
        "exp": NOW + share_card.TOKEN_TTL_SECONDS,
    }
    values.update(updates)
    return ShareCardPayload(**values)


def _score() -> dict:
    return {
        "overall_score": 700,
        "risk_preference_source": "confirmed",
        "risk_fit": {"status": "above"},
        "metrics": {"beta_to_benchmark": 0.8, "leverage": 1.0},
        "dimensions": {"downside_protection": {"score": 5.0}},
        "concentration": {"top_holding_weight": 0.31},
        "data_confidence": {"label": "high", "directional_allowed": True, "as_of": "2026-07-21"},
        "score_version": "score-v1",
    }


def test_token_round_trip_and_closed_privacy_schema():
    token = share_card.mint_token(_payload(), SECRET)
    result = share_card.resolve_token(token, SECRET, now=NOW)
    assert result == _payload()
    raw = json.loads(share_card._b64decode(token.split(".")[1]))
    assert set(raw) == {
        "v",
        "score_band",
        "risk_fit",
        "top_risk_category",
        "stress_band",
        "confidence_label",
        "as_of",
        "model_version",
        "exp",
    }
    assert not ({"user_id", "portfolio_id", "ticker", "score", "amount"} & set(raw))


@pytest.mark.parametrize("mutation", ["signature", "payload"])
def test_tampering_is_rejected(mutation):
    token = share_card.mint_token(_payload(), SECRET)
    parts = token.split(".")
    idx = 2 if mutation == "signature" else 1
    parts[idx] = ("A" if parts[idx][0] != "A" else "B") + parts[idx][1:]
    with pytest.raises(share_card.InvalidShareToken):
        share_card.resolve_token(".".join(parts), SECRET, now=NOW)


def test_expired_future_and_missing_secret_fail_closed():
    expired = share_card.mint_token(_payload(exp=NOW), SECRET)
    with pytest.raises(share_card.InvalidShareToken):
        share_card.resolve_token(expired, SECRET, now=NOW)
    future = share_card.mint_token(_payload(exp=NOW + share_card.TOKEN_TTL_SECONDS + 61), SECRET)
    with pytest.raises(share_card.InvalidShareToken):
        share_card.resolve_token(future, SECRET, now=NOW)
    with pytest.raises(share_card.InvalidShareToken):
        share_card.resolve_token(expired, "", now=NOW)


def test_payload_is_server_derived_and_not_confirmed_is_explicit():
    score = _score()
    score["risk_preference_source"] = "neutral_baseline"
    result = share_card.build_payload(score, now=NOW)
    assert result.score_band == "healthy"
    assert result.risk_fit == "not_confirmed"
    assert result.top_risk_category == "concentration"
    assert result.stress_band == "10_to_20_pct"


def test_payload_uses_the_canonical_score_concentration_field():
    score = _score()
    score["dimensions"] = {"risk_adjusted_return": {"score": 1.0}}
    result = share_card.build_payload(score, now=NOW)
    assert result.top_risk_category == "concentration"


@pytest.mark.parametrize(
    "confidence",
    [
        {"label": "low", "directional_allowed": True},
        {"label": "medium", "directional_allowed": False},
        {"label": "high", "directional_allowed": True, "stale": True},
    ],
)
def test_payload_never_publishes_directional_stress_when_confidence_blocks(confidence):
    score = _score()
    score["data_confidence"] = confidence
    result = share_card.build_payload(score, now=NOW)
    assert result.stress_band == "unavailable"


def _client(monkeypatch, *, secret=SECRET):
    monkeypatch.setattr(share_cards, "get_settings", lambda: Settings(share_signing_secret=secret))
    monkeypatch.setattr(share_cards, "_authoritative_score", lambda _request, _user: _score())
    app = create_app()
    app.dependency_overrides[require_user] = lambda: AuthedUser(
        id="user-a", email=None, raw_claims={}, access_token="jwt"
    )
    return TestClient(app)


def test_mint_accepts_no_display_payload_and_public_resolve(monkeypatch):
    client = _client(monkeypatch)
    assert client.post("/api/v1/share_cards/mint", json={"score": 999}).status_code == 422
    minted = client.post("/api/v1/share_cards/mint", json={}).json()["data"]
    resolved = client.post("/api/v1/share_cards/resolve", json={"token": minted["token"]})
    assert resolved.status_code == 200
    card = resolved.json()["data"]["card"]
    assert card["score_band"] == "healthy"
    assert "score" not in card and "user_id" not in card


def test_public_failures_are_uniform_and_missing_secret_blocks_mint(monkeypatch):
    client = _client(monkeypatch)
    good = client.post("/api/v1/share_cards/mint", json={}).json()["data"]["token"]
    for token in ("not-a-token" * 4, good[:-1] + ("A" if good[-1] != "A" else "B")):
        response = client.post("/api/v1/share_cards/resolve", json={"token": token})
        assert response.status_code == 404
        assert response.json()["error"]["message"] == "Share card not found."
    unavailable = _client(monkeypatch, secret="")
    assert unavailable.post("/api/v1/share_cards/mint", json={}).status_code == 503
    response = unavailable.post("/api/v1/share_cards/resolve", json={"token": good})
    assert response.status_code == 404


def test_capability_exposes_only_configuration_availability(monkeypatch):
    available = _client(monkeypatch)
    response = available.get("/api/v1/share_cards/capability")
    assert response.status_code == 200
    assert response.json()["data"] == {"enabled": True}

    unavailable = _client(monkeypatch, secret="")
    response = unavailable.get("/api/v1/share_cards/capability")
    assert response.status_code == 200
    assert response.json()["data"] == {"enabled": False}


@pytest.mark.parametrize("token", ["", "x", "x" * 4097])
def test_token_shape_failures_share_the_same_public_404(monkeypatch, token):
    response = _client(monkeypatch).post("/api/v1/share_cards/resolve", json={"token": token})
    assert response.status_code == 404
    assert response.json()["error"]["message"] == "Share card not found."


def test_resolve_rejects_oversized_body_before_token_work(monkeypatch):
    client = _client(monkeypatch)

    def should_not_resolve(*_args, **_kwargs):
        raise AssertionError("oversized request reached token verification")

    monkeypatch.setattr(share_card, "resolve_token", should_not_resolve)
    response = client.post(
        "/api/v1/share_cards/resolve",
        content=b'{"token":"' + (b"x" * 9_000) + b'"}',
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 404
    assert response.json()["error"]["message"] == "Share card not found."


def test_public_resolve_and_capability_are_rate_limited(monkeypatch):
    client = _client(monkeypatch)
    monkeypatch.setattr(
        share_cards,
        "_resolve_bucket",
        TokenBucket(capacity=1.0, refill_per_sec=0.0),
    )
    first = client.post("/api/v1/share_cards/resolve", json={"token": "invalid"})
    second = client.post("/api/v1/share_cards/resolve", json={"token": "invalid"})
    assert first.status_code == 404
    assert second.status_code == 429

    monkeypatch.setattr(
        share_cards,
        "_capability_bucket",
        TokenBucket(capacity=1.0, refill_per_sec=0.0),
    )
    assert client.get("/api/v1/share_cards/capability").status_code == 200
    assert client.get("/api/v1/share_cards/capability").status_code == 429


def test_mint_rate_limit_runs_before_authoritative_score(monkeypatch):
    client = _client(monkeypatch)
    calls = 0

    def score_once(_request, _user):
        nonlocal calls
        calls += 1
        return _score()

    monkeypatch.setattr(share_cards, "_authoritative_score", score_once)
    monkeypatch.setattr(
        share_cards,
        "_mint_bucket",
        TokenBucket(capacity=1.0, refill_per_sec=0.0),
    )
    assert client.post("/api/v1/share_cards/mint", json={}).status_code == 200
    assert client.post("/api/v1/share_cards/mint", json={}).status_code == 429
    assert calls == 1
