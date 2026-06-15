"""`/api/v1/data/health` — owner-gated data-source health view (commit 3/5)."""

from __future__ import annotations


def test_requires_auth(test_client):
    assert test_client.get("/api/v1/data/health").status_code == 401


def test_non_owner_forbidden(test_client, mint_token, monkeypatch):
    monkeypatch.setattr("libs.admin.status.is_owner_email", lambda email: False)
    resp = test_client.get(
        "/api/v1/data/health", headers={"Authorization": f"Bearer {mint_token()}"}
    )
    assert resp.status_code == 403


def test_owner_sees_provider_roster(test_client, mint_token, monkeypatch):
    monkeypatch.setattr("libs.admin.status.is_owner_email", lambda email: True)
    resp = test_client.get(
        "/api/v1/data/health", headers={"Authorization": f"Bearer {mint_token()}"}
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    by_id = {p["id"]: p for p in data["providers"]}
    # external providers present with role + configured + status
    for pid in ("massive", "fmp", "fred", "treasury", "yfinance"):
        assert pid in by_id
        assert "role" in by_id[pid] and "configured" in by_id[pid] and "status" in by_id[pid]
    # keyless sources are always configured; yfinance is fallback kind
    assert by_id["fred"]["configured"] is True
    assert by_id["yfinance"]["kind"] == "fallback"
    # computed sources (engine/derived) are NOT listed as data providers
    assert "engine" not in by_id and "derived" not in by_id


def test_status_reflects_metrics(test_client, mint_token, monkeypatch):
    monkeypatch.setattr("libs.admin.status.is_owner_email", lambda email: True)
    from backend.app.services import metrics

    metrics.record_provider("fmp", "rate_limited")
    resp = test_client.get(
        "/api/v1/data/health", headers={"Authorization": f"Bearer {mint_token()}"}
    )
    by_id = {p["id"]: p for p in resp.json()["data"]["providers"]}
    assert by_id["fmp"]["rate_limited"] >= 1
    assert by_id["fmp"]["status"] in ("rate_limited", "missing")  # missing if no key in test env
