"""Contract tests for ``GET /api/v1/portfolios/me``.

These pin the Phase-3 wiring: the route forwards the caller's JWT to
``libs.auth.portfolios.list_portfolios`` (RLS is the security boundary,
not this Python code), shapes the rows via the Pydantic response model,
and surfaces upstream failures as a clean ``server_error`` envelope.

We never hit Supabase here — the ``fake_portfolios`` fixture in
``conftest.py`` swaps ``list_portfolios`` for a stub so the tests run
hermetically and fast."""

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


def test_returns_supabase_rows_shaped_by_response_model(test_client, mint_token, fake_portfolios):
    fake_portfolios.set(
        [
            _sample_row(name="Default", is_default=True),
            _sample_row(
                id="22222222-2222-2222-2222-222222222222",
                name="Speculative",
                is_default=False,
            ),
        ]
    )
    token = mint_token()
    resp = test_client.get(
        "/api/v1/portfolios/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert len(data["portfolios"]) == 2
    names = [p["name"] for p in data["portfolios"]]
    assert names == ["Default", "Speculative"]
    # All declared response_model fields must be present, even when the
    # underlying row omitted optional numerics.
    p0 = data["portfolios"][0]
    for key in (
        "id",
        "name",
        "holdings",
        "margin_loan",
        "contributed_capital",
        "cash_balance",
        "is_default",
    ):
        assert key in p0


def test_forwards_caller_jwt_so_rls_filters_apply(test_client, mint_token, fake_portfolios):
    """The RLS contract: every Supabase read MUST carry the caller's
    JWT, not the server's anon key. If a refactor breaks this, every
    user sees every other user's rows."""
    fake_portfolios.set([])
    token = mint_token(sub="user-99")
    resp = test_client.get(
        "/api/v1/portfolios/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    # The exact bearer token must reach list_portfolios — string
    # equality, not "some token". Catches "I'm a server, I'll use the
    # admin client" regressions.
    assert fake_portfolios.calls == [token]


def test_emits_server_error_envelope_on_supabase_failure(test_client, mint_token, fake_portfolios):
    fake_portfolios.raise_with(RuntimeError("supabase reachable"))
    token = mint_token()
    resp = test_client.get(
        "/api/v1/portfolios/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 500
    body = resp.json()
    assert body["data"] is None
    assert body["error"]["code"] == "server_error"
    # Never leak the upstream exception message — just the class name.
    assert "supabase reachable" not in body["error"]["message"]


def test_empty_response_when_user_has_no_portfolios(test_client, mint_token, fake_portfolios):
    """New users get ``portfolios: []`` (not a 404) so the frontend
    renders an onboarding CTA instead of an error banner."""
    fake_portfolios.set([])
    token = mint_token()
    resp = test_client.get(
        "/api/v1/portfolios/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["portfolios"] == []
