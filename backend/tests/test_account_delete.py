"""DELETE /api/v1/account — the Privacy Policy's account-deletion promise.

Covers: auth gate, exact confirmation phrase, self-only targeting (the id
always comes from the JWT), Stripe fail-closed (a live subscription that
can't be canceled aborts the deletion), cancel-then-delete ordering, and the
admin-delete failure path.
"""

from __future__ import annotations

import pytest

from backend.app.services import account_delete

_PHRASE = account_delete.CONFIRMATION_PHRASE


def _delete(test_client, token, confirmation=_PHRASE):
    return test_client.request(
        "DELETE",
        "/api/v1/account",
        json={"confirmation": confirmation},
        headers={"Authorization": f"Bearer {token}"},
    )


@pytest.fixture()
def admin_calls(monkeypatch):
    """Stub the server-only Supabase admin client; records deleted user ids."""
    calls: list[str] = []

    class _Admin:
        class auth:  # noqa: N801 - mirrors supabase client shape
            class admin:  # noqa: N801
                @staticmethod
                def delete_user(uid):
                    calls.append(uid)

    import libs.auth.admin_client as ac

    monkeypatch.setattr(ac, "get_supabase_admin", lambda: _Admin())
    return calls


@pytest.fixture()
def no_subscription(monkeypatch):
    import libs.billing.usage as usage

    monkeypatch.setattr(usage, "get_subscription_record", lambda uid: None)


def test_requires_auth(test_client):
    resp = test_client.request("DELETE", "/api/v1/account", json={"confirmation": _PHRASE})
    assert resp.status_code == 401


def test_wrong_confirmation_phrase_is_rejected(test_client, mint_token, admin_calls):
    resp = _delete(test_client, mint_token(sub="user-1"), confirmation="delete my account")
    assert resp.status_code == 400
    assert admin_calls == []  # nothing deleted


def test_happy_path_deletes_only_the_caller(test_client, mint_token, admin_calls, no_subscription):
    resp = _delete(test_client, mint_token(sub="user-42"))
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["deleted"] is True
    assert body["data"]["subscription_canceled"] is False
    # Self-only: the deleted id is the JWT subject — there is no way to pass
    # another user's id (the endpoint takes no user parameter).
    assert admin_calls == ["user-42"]


def test_live_subscription_cancel_failure_fails_closed(
    test_client, mint_token, admin_calls, monkeypatch
):
    import libs.billing.usage as usage

    monkeypatch.setattr(
        usage,
        "get_subscription_record",
        lambda uid: {"stripe_subscription_id": "sub_123", "status": "active"},
    )
    # No STRIPE_SECRET_KEY in the test env → cancel cannot run → fail closed.
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)

    resp = _delete(test_client, mint_token(sub="user-7"))
    assert resp.status_code == 422
    assert "subscription" in resp.json()["error"]["message"].lower()
    assert admin_calls == []  # the account was NOT deleted


def test_live_subscription_cancel_success_then_delete(
    test_client, mint_token, admin_calls, monkeypatch
):
    import libs.billing.usage as usage

    monkeypatch.setattr(
        usage,
        "get_subscription_record",
        lambda uid: {"stripe_subscription_id": "sub_9", "status": "active"},
    )
    canceled: list[str] = []
    monkeypatch.setattr(
        account_delete, "_cancel_stripe_subscription", lambda sid: canceled.append(sid)
    )

    resp = _delete(test_client, mint_token(sub="user-8"))
    assert resp.status_code == 200
    assert resp.json()["data"]["subscription_canceled"] is True
    assert canceled == ["sub_9"]
    assert admin_calls == ["user-8"]


def test_already_canceled_subscription_skips_stripe(
    test_client, mint_token, admin_calls, monkeypatch
):
    import libs.billing.usage as usage

    monkeypatch.setattr(
        usage,
        "get_subscription_record",
        lambda uid: {"stripe_subscription_id": "sub_x", "status": "canceled"},
    )

    def _boom(sid):  # must not be called
        raise AssertionError("stripe cancel should not run for a canceled sub")

    monkeypatch.setattr(account_delete, "_cancel_stripe_subscription", _boom)
    resp = _delete(test_client, mint_token(sub="user-9"))
    assert resp.status_code == 200
    assert admin_calls == ["user-9"]


def test_admin_delete_failure_is_a_clear_500(test_client, mint_token, monkeypatch, no_subscription):
    class _Broken:
        class auth:  # noqa: N801
            class admin:  # noqa: N801
                @staticmethod
                def delete_user(uid):
                    raise RuntimeError("supabase down")

    import libs.auth.admin_client as ac

    monkeypatch.setattr(ac, "get_supabase_admin", lambda: _Broken())
    resp = _delete(test_client, mint_token(sub="user-10"))
    assert resp.status_code == 500
    assert "nothing was removed" in resp.json()["error"]["message"].lower()
