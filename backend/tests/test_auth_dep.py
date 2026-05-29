"""``require_user`` dependency contract.

These tests are why we mounted auth as a **per-route dependency**
instead of a global middleware: ``/health`` and ``/risk/score`` stay
public, ``/portfolios/me`` enforces JWT verification, and we can
prove both in the same test file."""

from __future__ import annotations

import time

import jwt as pyjwt


def test_health_does_not_require_auth(test_client):
    """Liveness probes are kicked by infra (Caddy / a load balancer);
    they must work without an Authorization header."""
    resp = test_client.get("/api/v1/health")
    assert resp.status_code == 200


def test_risk_score_does_not_require_auth(test_client):
    """The quant endpoint is Phase-1 public — see ADR-0004 + the
    Phase-1 brief. Frontends behind their own auth gate still
    work; the API itself stays stateless."""
    body = {
        "holdings": [
            {"ticker": "SPY", "market_value": 60_000, "asset_type": "public_security"},
            {"ticker": "BND", "market_value": 40_000, "asset_type": "public_security"},
        ],
    }
    resp = test_client.post("/api/v1/risk/score", json=body)
    assert resp.status_code == 200


def test_portfolios_me_rejects_missing_token(test_client):
    """No Authorization header → 401 envelope, not a 500."""
    resp = test_client.get("/api/v1/portfolios/me")
    assert resp.status_code == 401
    body = resp.json()
    assert body["data"] is None
    assert body["error"]["code"] == "unauthorized"


def test_portfolios_me_rejects_malformed_bearer(test_client, jwt_secret):
    resp = test_client.get(
        "/api/v1/portfolios/me",
        headers={"Authorization": "Bearer not-a-jwt"},
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "unauthorized"


def test_portfolios_me_rejects_wrong_signing_secret(test_client, jwt_secret):
    """Forge a token signed with the wrong key — must be rejected."""
    forged = pyjwt.encode(
        {
            "sub": "user-x",
            "email": "x@y.com",
            "aud": "authenticated",
            "exp": int(time.time()) + 600,
        },
        "DIFFERENT-SECRET",
        algorithm="HS256",
    )
    resp = test_client.get(
        "/api/v1/portfolios/me",
        headers={"Authorization": f"Bearer {forged}"},
    )
    assert resp.status_code == 401


def test_portfolios_me_rejects_expired_token(test_client, jwt_secret):
    expired = pyjwt.encode(
        {
            "sub": "user-x",
            "email": "x@y.com",
            "aud": "authenticated",
            "exp": int(time.time()) - 1,  # 1 second in the past
        },
        jwt_secret,
        algorithm="HS256",
    )
    resp = test_client.get(
        "/api/v1/portfolios/me",
        headers={"Authorization": f"Bearer {expired}"},
    )
    assert resp.status_code == 401


def test_portfolios_me_rejects_wrong_audience(test_client, jwt_secret):
    """Supabase end-user tokens always carry ``aud=authenticated``;
    a service-role token carries a different aud — must be rejected
    so we never accidentally elevate."""
    svc_role = pyjwt.encode(
        {
            "sub": "service-account",
            "aud": "service_role",
            "exp": int(time.time()) + 600,
        },
        jwt_secret,
        algorithm="HS256",
    )
    resp = test_client.get(
        "/api/v1/portfolios/me",
        headers={"Authorization": f"Bearer {svc_role}"},
    )
    assert resp.status_code == 401


def test_portfolios_me_accepts_valid_token(test_client, jwt_secret, mint_token, fake_portfolios):
    """Happy path: valid JWT + Supabase returns rows → envelope carries
    both the verified identity and the RLS-filtered list."""
    fake_portfolios.set([])  # signed-in user with no portfolios yet
    token = mint_token(sub="user-abc-123", email="owner@mindmarket.test")
    resp = test_client.get(
        "/api/v1/portfolios/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["error"] is None
    assert body["data"]["user_id"] == "user-abc-123"
    assert body["data"]["email"] == "owner@mindmarket.test"
    assert body["data"]["portfolios"] == []
    # The raw JWT was forwarded to Supabase for RLS, not replayed
    # from the server's own credentials.
    assert fake_portfolios.calls == [token]


def test_portfolios_me_fails_closed_when_secret_unset(test_client, monkeypatch):
    """A deploy with SUPABASE_JWT_SECRET missing must reject every
    protected request — never silently accept unverified tokens."""
    monkeypatch.delenv("SUPABASE_JWT_SECRET", raising=False)
    from backend.app.core.config import reset_settings_cache

    reset_settings_cache()

    forged = pyjwt.encode(
        {"sub": "anyone", "aud": "authenticated", "exp": int(time.time()) + 600},
        "anything",
        algorithm="HS256",
    )
    resp = test_client.get(
        "/api/v1/portfolios/me",
        headers={"Authorization": f"Bearer {forged}"},
    )
    assert resp.status_code == 401
