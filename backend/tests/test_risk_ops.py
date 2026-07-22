"""Alert-state + journey endpoint contracts, plus the journey first-once logic.

Hermetic: services monkeypatched; RLS verified in prod."""

from __future__ import annotations

from types import SimpleNamespace

import pytest


def _auth(mint_token, **kw):
    return {"Authorization": f"Bearer {mint_token(**kw)}"}


_UUID = "22222222-2222-2222-2222-222222222222"


# ── alert states ───────────────────────────────────────────────────


@pytest.fixture
def fake_alerts(monkeypatch):
    from backend.app.services import risk_alert_states as svc

    state = {"list": [], "raise": None, "calls": []}

    def _upsert(t, u, values):
        state["calls"].append({"user_id": u, **values})
        if state["raise"]:
            raise state["raise"]
        return {
            "portfolio_id": values["portfolio_id"],
            "alert_key": values["alert_key"],
            "state": values["state"],
            "snooze_until": values.get("snooze_until"),
            "updated_at": "2026-07-15T00:00:00Z",
        }

    monkeypatch.setattr(svc, "list_states", lambda t, u, p: state["list"])
    monkeypatch.setattr(svc, "upsert_state", _upsert)
    return state


def test_alert_state_routes_require_auth(test_client):
    assert test_client.get("/api/v1/risk/alert_states?portfolio_id=%s" % _UUID).status_code == 401
    assert test_client.put("/api/v1/risk/alert_states", json={}).status_code == 401


def test_upsert_alert_state_happy(test_client, mint_token, fake_alerts):
    body = {
        "portfolio_id": _UUID,
        "alert_key": "concentration:NVDA",
        "state": "snoozed",
        "snooze_until": "2026-08-01T00:00:00Z",
    }
    r = test_client.put("/api/v1/risk/alert_states", json=body, headers=_auth(mint_token, sub="u1"))
    assert r.status_code == 200, r.json()
    assert r.json()["data"]["state"] == "snoozed"
    assert fake_alerts["calls"][0]["user_id"] == "u1"


def test_upsert_alert_state_bad_enum_422(test_client, mint_token, fake_alerts):
    body = {"portfolio_id": _UUID, "alert_key": "x", "state": "dismissed"}  # not a valid state
    assert (
        test_client.put(
            "/api/v1/risk/alert_states", json=body, headers=_auth(mint_token)
        ).status_code
        == 422
    )


def test_upsert_alert_state_rls_violation_422(test_client, mint_token, fake_alerts):
    fake_alerts["raise"] = RuntimeError("violates row-level security policy")
    body = {"portfolio_id": _UUID, "alert_key": "x", "state": "seen"}
    r = test_client.put("/api/v1/risk/alert_states", json=body, headers=_auth(mint_token))
    assert r.status_code == 422 and r.json()["error"]["code"] == "portfolio_not_found"


# ── journey ────────────────────────────────────────────────────────


@pytest.fixture
def fake_journey(monkeypatch):
    from backend.app.services import user_journey as svc

    state = {"row": {m: None for m in svc._MILESTONES}, "record": None}
    monkeypatch.setattr(svc, "get_state", lambda t, u: state["row"])
    monkeypatch.setattr(
        svc,
        "record_milestone",
        lambda t, u, m: state["record"] or {**state["row"], m: "2026-07-15T00:00:00Z"},
    )
    return state


def test_journey_routes_require_auth(test_client):
    assert test_client.get("/api/v1/journey").status_code == 401
    assert (
        test_client.post("/api/v1/journey/record", json={"milestone": "first_score_at"}).status_code
        == 401
    )


def test_journey_get_happy(test_client, mint_token, fake_journey):
    r = test_client.get("/api/v1/journey", headers=_auth(mint_token))
    assert r.status_code == 200
    assert "first_score_at" in r.json()["data"]


def test_journey_record_happy(test_client, mint_token, fake_journey):
    r = test_client.post(
        "/api/v1/journey/record",
        json={"milestone": "first_stress_test_at"},
        headers=_auth(mint_token),
    )
    assert r.status_code == 200
    assert r.json()["data"]["first_stress_test_at"] is not None


def test_journey_record_bad_milestone_422(test_client, mint_token, fake_journey):
    r = test_client.post(
        "/api/v1/journey/record", json={"milestone": "not_a_milestone"}, headers=_auth(mint_token)
    )
    assert r.status_code == 422


def test_journey_cannot_client_claim_server_owned_milestone(test_client, mint_token, fake_journey):
    r = test_client.post(
        "/api/v1/journey/record",
        json={"milestone": "first_driver_viewed_at"},
        headers=_auth(mint_token),
    )
    assert r.status_code == 422


# ── journey first-once vs last-always logic (service unit) ──────────


def _fake_client_capturing(monkeypatch, existing_row):
    """A chainable supabase stub that captures the upsert payload and returns
    ``existing_row`` from get_state's select."""
    captured = {}
    sb = SimpleNamespace()

    def table(_):
        return sb

    def select(_):
        return sb

    def eq(*_a):
        return sb

    def limit(_):
        return sb

    def execute():
        return SimpleNamespace(data=[existing_row] if existing_row else [])

    def upsert(payload, on_conflict=None):
        captured["payload"] = payload
        return SimpleNamespace(execute=lambda: SimpleNamespace(data=[payload]))

    sb.table = table
    sb.select = select
    sb.eq = eq
    sb.limit = limit
    sb.execute = execute
    sb.upsert = upsert

    from backend.app.services import user_journey as svc

    monkeypatch.setattr(svc, "_client", lambda access_token: sb)
    return captured


def test_record_first_milestone_only_once(monkeypatch):
    from backend.app.services import user_journey as svc

    # already stamped → a second record must NOT overwrite it (no upsert)
    captured = _fake_client_capturing(
        monkeypatch,
        {
            "first_score_at": "2026-01-01T00:00:00Z",
            **{m: None for m in svc._MILESTONES if m != "first_score_at"},
        },
    )
    result = svc.record_milestone("tok", "u1", "first_score_at")
    assert result["first_score_at"] == "2026-01-01T00:00:00Z"
    assert "payload" not in captured  # no write happened


def test_record_last_workspace_view_always_updates(monkeypatch):
    from backend.app.services import user_journey as svc

    captured = _fake_client_capturing(
        monkeypatch,
        {
            "last_workspace_view": "2026-01-01T00:00:00Z",
            **{m: None for m in svc._MILESTONES if m != "last_workspace_view"},
        },
    )
    svc.record_milestone("tok", "u1", "last_workspace_view")
    assert "last_workspace_view" in captured["payload"]  # always writes


def test_record_unknown_milestone_raises(monkeypatch):
    from backend.app.services import user_journey as svc

    _fake_client_capturing(monkeypatch, None)
    with pytest.raises(ValueError):
        svc.record_milestone("tok", "u1", "hax")


# ── server-side milestone stamping (product events) ────────────────


def test_stamp_milestone_failsoft_never_raises(monkeypatch):
    from backend.app.services import user_journey as svc

    svc.reset_stamp_memo()

    def _boom(*a, **k):
        raise RuntimeError("supabase down")

    monkeypatch.setattr(svc, "record_milestone", _boom)
    # Must not raise — journey bookkeeping never fails a product endpoint.
    svc.stamp_milestone_failsoft("tok", "u1", "first_plan_at")


def test_stamp_milestone_failsoft_memoizes_first_milestones(monkeypatch):
    from backend.app.services import user_journey as svc

    svc.reset_stamp_memo()
    calls = []
    monkeypatch.setattr(svc, "record_milestone", lambda t, u, m: calls.append((u, m)) or {})

    svc.stamp_milestone_failsoft("tok", "u1", "first_score_at")
    svc.stamp_milestone_failsoft("tok", "u1", "first_score_at")  # memo hit
    assert calls == [("u1", "first_score_at")]

    # A FAILED stamp is not memoized — the next event retries.
    svc.reset_stamp_memo()
    calls.clear()

    def _fail_once(t, u, m):
        calls.append((u, m))
        if len(calls) == 1:
            raise RuntimeError("blip")
        return {}

    monkeypatch.setattr(svc, "record_milestone", _fail_once)
    svc.stamp_milestone_failsoft("tok", "u2", "first_plan_at")
    svc.stamp_milestone_failsoft("tok", "u2", "first_plan_at")
    assert len(calls) == 2  # retried after the failure
    svc.stamp_milestone_failsoft("tok", "u2", "first_plan_at")
    assert len(calls) == 2  # memoized after the success
