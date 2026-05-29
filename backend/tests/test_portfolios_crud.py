"""Contract tests for ``POST /portfolios``, ``PATCH /portfolios/{id}``,
``DELETE /portfolios/{id}``.

All hermetic: ``fake_portfolio_mutations`` in ``conftest.py``
monkeypatches the three ``libs.auth.portfolios`` mutation helpers so
tests never hit Supabase.

Key contract assertions:

* Auth required on every mutation route (401 without bearer).
* The caller's raw JWT is forwarded to the libs layer so Supabase RLS
  enforces tenancy at the database — string-equality check, not
  "any token".
* ``AuthError`` from libs maps to 422 on create, 404 on update.
* ``ValueError`` from libs (e.g. bad field name) maps to 422.
* PATCH with empty body → 422 ``no_fields_to_update`` (not a no-op).
"""

from __future__ import annotations


def _sample_row(**overrides):
    row = {
        "id": "11111111-1111-1111-1111-111111111111",
        "user_id": "user-abc-123",
        "name": "Default",
        "holdings": {"SPY": {"shares": 100, "avg_cost": 400.0}},
        "margin_loan": 0.0,
        "contributed_capital": 40000.0,
        "cash_balance": 1000.0,
        "is_default": True,
        "created_at": "2026-05-01T00:00:00Z",
        "updated_at": "2026-05-01T00:00:00Z",
    }
    row.update(overrides)
    return row


# ── POST /portfolios — create ──────────────────────────────────────


def test_create_requires_bearer(test_client):
    resp = test_client.post("/api/v1/portfolios", json={"name": "X", "holdings": {}})
    assert resp.status_code == 401


def test_create_forwards_jwt_and_returns_row(test_client, mint_token, fake_portfolio_mutations):
    fake_portfolio_mutations["create"].set_return(_sample_row(name="New"))
    token = mint_token(sub="user-99")
    resp = test_client.post(
        "/api/v1/portfolios",
        json={
            "name": "New",
            "holdings": {"SPY": {"shares": 100}},
            "is_default": True,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.json()
    body = resp.json()
    assert body["error"] is None
    assert body["data"]["name"] == "New"
    # The exact bearer token must reach the libs layer for RLS. Same
    # invariant as /portfolios/me — refactors that drop this fail here.
    assert fake_portfolio_mutations["create"].calls[0]["access_token"] == token
    assert fake_portfolio_mutations["create"].calls[0]["name"] == "New"
    # Holdings dict was converted from pydantic model to plain dict.
    assert fake_portfolio_mutations["create"].calls[0]["holdings"] == {"SPY": {"shares": 100.0}}


def test_create_rejects_extra_fields(test_client, mint_token, fake_portfolio_mutations):
    """Pydantic ``extra="forbid"`` should block payloads that try to
    set columns we don't allow from the API (e.g. ``user_id``)."""
    resp = test_client.post(
        "/api/v1/portfolios",
        json={"name": "X", "holdings": {}, "user_id": "someone-else"},
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation_failed"


def test_create_auth_error_from_libs_maps_to_422(test_client, mint_token, fake_portfolio_mutations):
    # Simulate libs.auth.AuthError ("Insert returned no row — check RLS").
    class AuthError(Exception):
        pass

    fake_portfolio_mutations["create"].raise_with(
        AuthError("Insert returned no row — check RLS policy.")
    )
    resp = test_client.post(
        "/api/v1/portfolios",
        json={"name": "X", "holdings": {}},
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "portfolio_create_failed"


# ── PATCH /portfolios/{id} — update ────────────────────────────────


def test_patch_requires_bearer(test_client):
    resp = test_client.patch("/api/v1/portfolios/abc", json={"name": "Renamed"})
    assert resp.status_code == 401


def test_patch_applies_partial_fields_and_forwards_jwt(
    test_client, mint_token, fake_portfolio_mutations
):
    fake_portfolio_mutations["update"].set_return(_sample_row(name="Renamed"))
    token = mint_token()
    resp = test_client.patch(
        "/api/v1/portfolios/p-1",
        json={"name": "Renamed"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["name"] == "Renamed"
    call = fake_portfolio_mutations["update"].calls[0]
    assert call["portfolio_id"] == "p-1"
    assert call["access_token"] == token
    # Only `name` was sent — the rest must NOT show up in the libs
    # call (exclude_unset). Otherwise an "edit name" PATCH could
    # accidentally null cash_balance etc.
    assert call.get("cash_balance") is None
    assert (
        "cash_balance" not in {k for k in call if k not in ("portfolio_id", "access_token")}
        or call.get("cash_balance") is None
    )
    assert call["name"] == "Renamed"


def test_patch_empty_body_returns_422(test_client, mint_token, fake_portfolio_mutations):
    resp = test_client.patch(
        "/api/v1/portfolios/p-1",
        json={},
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "no_fields_to_update"


def test_patch_auth_error_from_libs_maps_to_404(test_client, mint_token, fake_portfolio_mutations):
    class AuthError(Exception):
        pass

    fake_portfolio_mutations["update"].raise_with(
        AuthError("No row updated — wrong id or RLS blocked you.")
    )
    resp = test_client.patch(
        "/api/v1/portfolios/missing",
        json={"name": "X"},
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "portfolio_not_found"


def test_patch_value_error_from_libs_maps_to_422(test_client, mint_token, fake_portfolio_mutations):
    fake_portfolio_mutations["update"].raise_with(
        ValueError("Cannot update fields: {'forbidden_col'}")
    )
    resp = test_client.patch(
        "/api/v1/portfolios/p-1",
        json={"name": "X"},
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "invalid_field"


# ── DELETE /portfolios/{id} — delete ───────────────────────────────


def test_delete_requires_bearer(test_client):
    resp = test_client.delete("/api/v1/portfolios/p-1")
    assert resp.status_code == 401


def test_delete_forwards_jwt(test_client, mint_token, fake_portfolio_mutations):
    token = mint_token()
    resp = test_client.delete(
        "/api/v1/portfolios/p-target",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body == {"deleted": True, "id": "p-target"}
    assert fake_portfolio_mutations["delete"].calls == [
        {"portfolio_id": "p-target", "access_token": token}
    ]


def test_delete_upstream_failure_is_server_error(test_client, mint_token, fake_portfolio_mutations):
    fake_portfolio_mutations["delete"].raise_with(RuntimeError("supabase down"))
    resp = test_client.delete(
        "/api/v1/portfolios/p-1",
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    assert resp.status_code == 500
    body = resp.json()
    assert body["error"]["code"] == "server_error"
    assert "supabase down" not in body["error"]["message"]
