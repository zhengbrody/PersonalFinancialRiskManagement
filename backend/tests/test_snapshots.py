"""Contract test for GET /api/v1/risk/last_snapshot (the 'what changed' baseline)."""

from __future__ import annotations

import pytest


@pytest.fixture
def fake_prev(monkeypatch):
    import backend.app.services.snapshots as snaps

    state = {"row": None}

    def _get(access_token=None):
        return state["row"]

    monkeypatch.setattr(snaps, "get_previous_snapshot", _get)
    return state


def test_last_snapshot_requires_bearer(test_client):
    assert test_client.get("/api/v1/risk/last_snapshot").status_code == 401


def test_last_snapshot_null_when_none(test_client, mint_token, fake_prev):
    fake_prev["row"] = None
    resp = test_client.get(
        "/api/v1/risk/last_snapshot", headers={"Authorization": f"Bearer {mint_token()}"}
    )
    assert resp.status_code == 200, resp.json()
    assert resp.json()["data"]["snapshot"] is None


def test_last_snapshot_serializes_prior_row(test_client, mint_token, fake_prev):
    fake_prev["row"] = {
        "created_at": "2026-05-28T00:00:00+00:00",
        "net_equity": 95000.0,
        "leverage": 1.0,
        "risk_metrics": {
            "overall_score": 612,
            "annual_volatility": 0.16,
            "var_95_daily": 0.021,
            "sharpe_ratio": 0.9,
            "max_drawdown": -0.12,
            "daily_pnl": 1250.0,
            "daily_return": 0.0133,
            "total_pnl": 5000.0,
            "total_return": 0.0556,
        },
    }
    resp = test_client.get(
        "/api/v1/risk/last_snapshot", headers={"Authorization": f"Bearer {mint_token()}"}
    )
    assert resp.status_code == 200, resp.json()
    snap = resp.json()["data"]["snapshot"]
    assert snap["overall_score"] == 612
    assert snap["annual_volatility"] == 0.16
    assert snap["as_of"] == "2026-05-28T00:00:00+00:00"
    assert snap["net_equity"] == 95000.0
    assert snap["daily_pnl"] == 1250.0
    assert snap["daily_return"] == 0.0133
    assert snap["total_pnl"] == 5000.0
    assert snap["total_return"] == 0.0556


@pytest.fixture
def fake_history(monkeypatch):
    import backend.app.services.snapshots as snaps

    state = {"rows": []}
    monkeypatch.setattr(snaps, "get_snapshot_history", lambda access_token=None, **k: state["rows"])
    return state


def test_snapshot_history_requires_bearer(test_client):
    assert test_client.get("/api/v1/risk/snapshot_history").status_code == 401


def test_snapshot_history_empty(test_client, mint_token, fake_history):
    fake_history["rows"] = []
    resp = test_client.get(
        "/api/v1/risk/snapshot_history", headers={"Authorization": f"Bearer {mint_token()}"}
    )
    assert resp.status_code == 200, resp.json()
    assert resp.json()["data"]["snapshots"] == []


def test_snapshot_history_serializes(test_client, mint_token, fake_history):
    fake_history["rows"] = [
        {
            "as_of": "2026-05-20T00:00:00+00:00",
            "overall_score": 540,
            "annual_volatility": 0.18,
            "var_95_daily": 0.022,
            "sharpe_ratio": 0.3,
            "max_drawdown": -0.2,
            "net_equity": 90000.0,
            "total_return": -0.1,
        },
        {
            "as_of": "2026-05-28T00:00:00+00:00",
            "overall_score": 612,
            "annual_volatility": 0.16,
            "var_95_daily": 0.021,
            "sharpe_ratio": 0.9,
            "max_drawdown": -0.12,
            "net_equity": 95000.0,
            "total_return": -0.05,
        },
    ]
    resp = test_client.get(
        "/api/v1/risk/snapshot_history", headers={"Authorization": f"Bearer {mint_token()}"}
    )
    assert resp.status_code == 200, resp.json()
    snaps = resp.json()["data"]["snapshots"]
    assert len(snaps) == 2
    assert snaps[0]["overall_score"] == 540 and snaps[-1]["overall_score"] == 612
    assert snaps[0]["total_return"] == -0.1 and snaps[-1]["total_return"] == -0.05
