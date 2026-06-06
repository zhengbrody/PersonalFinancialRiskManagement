"""Tests for the owner-only system-status endpoint (GET /billing/admin/status).

Owner-gating via MINDMARKET_OWNER_EMAILS; live checks are monkeypatched so CI
never makes real Anthropic/Stripe calls.
"""

from __future__ import annotations

import pytest

_OWNER = "owner@mindmarket.test"


def _auth(mint_token, **claims):
    return {"Authorization": f"Bearer {mint_token(**claims)}"}


@pytest.fixture
def as_owner(monkeypatch):
    monkeypatch.setenv("MINDMARKET_OWNER_EMAILS", _OWNER)
    # The status checker reads a few env keys; set one so it reports configured.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")


def test_status_requires_bearer(test_client):
    assert test_client.get("/api/v1/billing/admin/status").status_code == 401


def test_status_forbidden_for_non_owner(test_client, mint_token, monkeypatch):
    monkeypatch.setenv("MINDMARKET_OWNER_EMAILS", "someone-else@x.com")
    resp = test_client.get("/api/v1/billing/admin/status", headers=_auth(mint_token))
    assert resp.status_code == 403


def test_status_config_only_for_owner(test_client, mint_token, as_owner):
    resp = test_client.get("/api/v1/billing/admin/status", headers=_auth(mint_token))
    assert resp.status_code == 200, resp.json()
    data = resp.json()["data"]
    assert data["live"] is False
    names = {i["name"] for i in data["integrations"]}
    assert {"Claude (Anthropic)", "Supabase", "Stripe"} <= names
    claude = next(i for i in data["integrations"] if i["name"] == "Claude (Anthropic)")
    assert claude["configured"] is True  # ANTHROPIC_API_KEY set by the fixture
    sentry = next(i for i in data["integrations"] if i["name"] == "Sentry")
    assert sentry["configured"] is True  # backend has a default DSN, env-overridable
    assert "SENTRY_DSN" not in sentry["detail"]
    # No secret values leak — only state/detail strings.
    assert "sk-ant-test" not in resp.text


def test_status_live_checks_run_when_requested(test_client, mint_token, as_owner, monkeypatch):
    from backend.app.services import admin_status

    monkeypatch.setitem(admin_status._LIVE_CHECKS, "Claude (Anthropic)", lambda: (True, "pong"))
    resp = test_client.get("/api/v1/billing/admin/status?live=true", headers=_auth(mint_token))
    assert resp.status_code == 200, resp.json()
    data = resp.json()["data"]
    assert data["live"] is True
    claude = next(i for i in data["integrations"] if i["name"] == "Claude (Anthropic)")
    assert claude["state"] == "Connected"
    assert claude["detail"] == "pong"


def test_status_live_check_fails_soft(test_client, mint_token, as_owner, monkeypatch):
    from backend.app.services import admin_status

    def boom():
        raise RuntimeError("401 invalid key")

    monkeypatch.setitem(admin_status._LIVE_CHECKS, "Claude (Anthropic)", boom)
    resp = test_client.get("/api/v1/billing/admin/status?live=true", headers=_auth(mint_token))
    assert resp.status_code == 200  # never 500
    claude = next(
        i for i in resp.json()["data"]["integrations"] if i["name"] == "Claude (Anthropic)"
    )
    assert claude["state"] == "Error"
