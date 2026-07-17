"""Risk-plan endpoint contracts + strict schema validation.

Hermetic: the ``backend.app.services.risk_plans`` functions are monkeypatched so
no Supabase is touched. RLS itself (cross-user isolation, portfolio ownership)
is verified in prod (two-user smoke), not here.
"""

from __future__ import annotations

import json

import pytest


def _auth(mint_token, **kw):
    return {"Authorization": f"Bearer {mint_token(**kw)}"}


_UUID = "11111111-1111-1111-1111-111111111111"


def _plan_row(**over):
    row = {
        "id": "99999999-9999-9999-9999-999999999999",
        "portfolio_id": _UUID,
        "title": "Trim NVDA concentration",
        "status": "draft",
        "source": "risk",
        "hypothesis": None,
        "baseline": {"annual_volatility": 0.3},
        "proposed_changes": {},
        "expected_impact": {},
        "data_confidence": {},
        "review_at": None,
        "reviewed_at": None,
        "resolved_at": None,
        "outcome": None,
        "created_at": "2026-07-15T00:00:00Z",
        "updated_at": "2026-07-15T00:00:00Z",
    }
    row.update(over)
    return row


@pytest.fixture
def fake_plans(monkeypatch):
    from backend.app.services import risk_plans as svc

    state: dict = {
        "row": _plan_row(),
        "list": [],
        "get": _plan_row(),
        "raise": None,
        "update": _plan_row(),
        "create_calls": [],
    }

    def _create(access_token, user_id, values):
        state["create_calls"].append({"access_token": access_token, "user_id": user_id, **values})
        if state["raise"]:
            raise state["raise"]
        return _plan_row(
            **{k: values[k] for k in ("title", "source", "portfolio_id") if k in values}
        )

    monkeypatch.setattr(svc, "create_plan", _create)
    monkeypatch.setattr(svc, "list_plans", lambda t, u, p=None: state["list"])
    monkeypatch.setattr(svc, "get_plan", lambda t, u, pid: state["get"])
    monkeypatch.setattr(svc, "update_plan", lambda t, u, pid, f: state["update"])
    monkeypatch.setattr(svc, "delete_plan", lambda t, u, pid: None)
    monkeypatch.setattr(svc, "mark_reviewed", lambda t, u, pid: None)
    return state


# ── auth ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/api/v1/risk/plans"),
        ("post", "/api/v1/risk/plans"),
        ("get", f"/api/v1/risk/plans/{_UUID}"),
        ("patch", f"/api/v1/risk/plans/{_UUID}"),
        ("delete", f"/api/v1/risk/plans/{_UUID}"),
        ("post", f"/api/v1/risk/plans/{_UUID}/review"),
    ],
)
def test_all_plan_routes_require_auth(test_client, method, path):
    assert getattr(test_client, method)(path).status_code == 401


# ── create + validation ────────────────────────────────────────────


def test_create_happy_forwards_jwt(test_client, mint_token, fake_plans):
    token = mint_token(sub="user-7")
    body = {
        "portfolio_id": _UUID,
        "title": "My plan",
        "source": "risk",
        "baseline": {"annual_volatility": 0.3},
    }
    resp = test_client.post(
        "/api/v1/risk/plans", json=body, headers=_auth(mint_token, sub="user-7")
    )
    assert resp.status_code == 200, resp.json()
    assert fake_plans["create_calls"][0]["user_id"] == "user-7"
    assert fake_plans["create_calls"][0]["portfolio_id"] == _UUID


def test_create_rejects_bad_source_enum(test_client, mint_token, fake_plans):
    body = {"portfolio_id": _UUID, "title": "x", "source": "not_a_source"}
    assert (
        test_client.post("/api/v1/risk/plans", json=body, headers=_auth(mint_token)).status_code
        == 422
    )


def test_create_rejects_extra_fields(test_client, mint_token, fake_plans):
    body = {"portfolio_id": _UUID, "title": "x", "source": "risk", "evil": 1}
    assert (
        test_client.post("/api/v1/risk/plans", json=body, headers=_auth(mint_token)).status_code
        == 422
    )


def test_create_rejects_oversized_blob(test_client, mint_token, fake_plans):
    body = {"portfolio_id": _UUID, "title": "x", "source": "risk", "baseline": {"pad": "z" * 20000}}
    r = test_client.post("/api/v1/risk/plans", json=body, headers=_auth(mint_token))
    assert r.status_code == 422
    assert "bytes" in json.dumps(r.json())


def test_create_rejects_non_finite_number(test_client, mint_token, fake_plans):
    # JSON literal Infinity → the finite validator rejects it.
    payload = '{"portfolio_id":"%s","title":"x","source":"risk","baseline":{"v":Infinity}}' % _UUID
    r = test_client.post(
        "/api/v1/risk/plans",
        content=payload,
        headers={**_auth(mint_token), "Content-Type": "application/json"},
    )
    assert r.status_code == 422


def test_create_rejects_bad_portfolio_id_shape(test_client, mint_token, fake_plans):
    body = {"portfolio_id": "not-a-uuid", "title": "x", "source": "risk"}
    assert (
        test_client.post("/api/v1/risk/plans", json=body, headers=_auth(mint_token)).status_code
        == 422
    )


def test_create_rls_violation_maps_to_422(test_client, mint_token, fake_plans):
    fake_plans["raise"] = RuntimeError("new row violates row-level security policy for table")
    body = {"portfolio_id": _UUID, "title": "x", "source": "risk"}
    r = test_client.post("/api/v1/risk/plans", json=body, headers=_auth(mint_token))
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "portfolio_not_found"


def test_create_missing_table_maps_to_503(test_client, mint_token, fake_plans):
    fake_plans["raise"] = RuntimeError('relation "risk_plans" does not exist')
    body = {"portfolio_id": _UUID, "title": "x", "source": "risk"}
    assert (
        test_client.post("/api/v1/risk/plans", json=body, headers=_auth(mint_token)).status_code
        == 503
    )


# ── get / patch / delete ───────────────────────────────────────────


def test_get_404_when_missing(test_client, mint_token, fake_plans):
    fake_plans["get"] = None

    from backend.app.services import risk_plans as svc

    svc.get_plan = lambda t, u, pid: None  # type: ignore
    r = test_client.get(f"/api/v1/risk/plans/{_UUID}", headers=_auth(mint_token))
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "plan_not_found"


def test_patch_empty_body_422(test_client, mint_token, fake_plans):
    r = test_client.patch(f"/api/v1/risk/plans/{_UUID}", json={}, headers=_auth(mint_token))
    assert r.status_code == 422


def test_patch_immutable_source_rejected(test_client, mint_token, fake_plans):
    # source isn't a patchable field → extra=forbid rejects it
    r = test_client.patch(
        f"/api/v1/risk/plans/{_UUID}", json={"source": "copilot"}, headers=_auth(mint_token)
    )
    assert r.status_code == 422


def test_patch_explicit_null_on_not_null_field_is_422(test_client, mint_token, fake_plans):
    # An explicit null on a NOT-NULL column would 500 at the DB; the boundary
    # rejects it as a 422 client error.
    r = test_client.patch(
        f"/api/v1/risk/plans/{_UUID}", json={"title": None}, headers=_auth(mint_token)
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "invalid_field"
    # …but a null on a nullable field (outcome) is a legitimate clear.
    r2 = test_client.patch(
        f"/api/v1/risk/plans/{_UUID}", json={"outcome": None}, headers=_auth(mint_token)
    )
    assert r2.status_code == 200


def test_delete_happy(test_client, mint_token, fake_plans):
    r = test_client.delete(f"/api/v1/risk/plans/{_UUID}", headers=_auth(mint_token))
    assert r.status_code == 200
    assert r.json()["data"] == {"deleted": True, "id": _UUID}


# ── review ─────────────────────────────────────────────────────────


def test_review_returns_verdict(test_client, mint_token, fake_plans):
    fake_plans["get"] = _plan_row(baseline={"annual_volatility": 0.30})
    from backend.app.services import risk_plans as svc

    svc.get_plan = lambda t, u, pid: _plan_row(baseline={"annual_volatility": 0.30})  # type: ignore
    r = test_client.post(
        f"/api/v1/risk/plans/{_UUID}/review",
        json={"current": {"annual_volatility": 0.20}},
        headers=_auth(mint_token),
    )
    assert r.status_code == 200, r.json()
    assert r.json()["data"]["verdict"] == "improved"
    assert "not financial advice" in r.json()["data"]["disclaimer"].lower()


def test_review_404_when_plan_missing(test_client, mint_token, fake_plans):
    from backend.app.services import risk_plans as svc

    svc.get_plan = lambda t, u, pid: None  # type: ignore
    r = test_client.post(
        f"/api/v1/risk/plans/{_UUID}/review", json={"current": {}}, headers=_auth(mint_token)
    )
    assert r.status_code == 404


# ── server-side journey stamping at plan product events ────────────


@pytest.fixture
def capture_stamps(monkeypatch):
    from backend.app.services import user_journey as svc

    svc.reset_stamp_memo()
    stamped: list[tuple[str, str]] = []
    monkeypatch.setattr(
        svc, "record_milestone", lambda t, u, m: stamped.append((u, m)) or {m: "now"}
    )
    return stamped


def test_plan_create_stamps_first_plan_milestone(
    test_client, mint_token, fake_plans, capture_stamps
):
    body = {
        "portfolio_id": _UUID,
        "title": "Trim tech concentration",
        "source": "research",
    }
    r = test_client.post("/api/v1/risk/plans", json=body, headers=_auth(mint_token, sub="user-j1"))
    assert r.status_code == 200
    assert ("user-j1", "first_plan_at") in capture_stamps


def test_plan_review_stamps_first_plan_reviewed_milestone(
    test_client, mint_token, fake_plans, capture_stamps
):
    r = test_client.post(
        f"/api/v1/risk/plans/{_UUID}/review",
        json={"current": {"overall_score": 700.0}},
        headers=_auth(mint_token, sub="user-j2"),
    )
    assert r.status_code == 200
    assert ("user-j2", "first_plan_reviewed_at") in capture_stamps


def test_plan_create_survives_stamp_failure(test_client, mint_token, fake_plans, monkeypatch):
    from backend.app.services import user_journey as svc

    svc.reset_stamp_memo()

    def _boom(*a, **k):
        raise RuntimeError("journey table missing")

    monkeypatch.setattr(svc, "record_milestone", _boom)
    body = {"portfolio_id": _UUID, "title": "Plan", "source": "research"}
    r = test_client.post("/api/v1/risk/plans", json=body, headers=_auth(mint_token))
    assert r.status_code == 200  # the product event succeeds regardless
