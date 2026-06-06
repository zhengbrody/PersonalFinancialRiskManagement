"""Contract tests for ``/api/v1/billing/*``.

**Stripe is never reached in these tests.** We monkeypatch the
``libs.billing`` helpers at the import point so:
  * No HTTP traffic leaves the test process.
  * No secret key, account id, or webhook secret is read.
  * Tests stay fast (<1s for the whole file).

Key invariants:
  * Every route requires a bearer token (401 without).
  * /checkout_session and /portal_session NEVER accept a customer id
    from the client — the customer id is resolved server-side.
  * Specific error codes the frontend branches on: ``email_required``,
    ``no_stripe_customer``, ``billing_not_configured``, ``stripe_error``.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

# ── shared stubs ──────────────────────────────────────────────────


@dataclass
class _FakeCheckoutResult:
    url: str
    session_id: str


@pytest.fixture
def fake_billing(monkeypatch):
    """Patch every libs.billing function the routes touch so tests
    drive behaviour with plain Python objects."""

    state: dict = {
        "plan": "free",
        "subscription": None,
        "checkout_result": None,
        "portal_url": None,
        "checkout_calls": [],
        "portal_calls": [],
        "checkout_raise": None,
        "portal_raise": None,
        "plan_raise": None,
        "sub_raise": None,
    }

    def _get_user_plan(user_id: str, **kwargs) -> str:
        if state["plan_raise"]:
            raise state["plan_raise"]
        from libs.admin.status import is_owner_email

        if is_owner_email(kwargs.get("email")):
            return "owner"
        return state["plan"]

    def _get_subscription_record(user_id: str):
        if state["sub_raise"]:
            raise state["sub_raise"]
        return state["subscription"]

    def _create_checkout_session(*, user_id, email, plan, success_path, cancel_path):
        state["checkout_calls"].append(
            {
                "user_id": user_id,
                "email": email,
                "plan": plan,
                "success_path": success_path,
                "cancel_path": cancel_path,
            }
        )
        if state["checkout_raise"]:
            raise state["checkout_raise"]
        return state["checkout_result"]

    def _create_portal_session(*, stripe_customer_id, return_path):
        state["portal_calls"].append(
            {"stripe_customer_id": stripe_customer_id, "return_path": return_path}
        )
        if state["portal_raise"]:
            raise state["portal_raise"]
        return state["portal_url"]

    import libs.billing.stripe_checkout as sc_mod
    import libs.billing.usage as usage_mod

    monkeypatch.setattr(usage_mod, "get_user_plan", _get_user_plan)
    monkeypatch.setattr(usage_mod, "get_subscription_record", _get_subscription_record)
    monkeypatch.setattr(sc_mod, "create_checkout_session", _create_checkout_session)
    monkeypatch.setattr(sc_mod, "create_customer_portal_session", _create_portal_session)
    return state


# ── /billing/me ───────────────────────────────────────────────────


def test_billing_me_requires_bearer(test_client):
    resp = test_client.get("/api/v1/billing/me")
    assert resp.status_code == 401


def test_billing_me_returns_plan_and_catalogue(test_client, mint_token, fake_billing):
    fake_billing["plan"] = "basic"
    fake_billing["subscription"] = {
        "stripe_customer_id": "cus_123",
        "stripe_subscription_id": "sub_123",
        "plan": "basic",
        "status": "active",
        "current_period_start": "2026-05-01T00:00:00Z",
        "current_period_end": "2026-06-01T00:00:00Z",
        "cancel_at_period_end": False,
    }
    resp = test_client.get(
        "/api/v1/billing/me",
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["plan"] == "basic"
    assert data["subscription"]["status"] == "active"
    assert data["subscription"]["stripe_customer_id"] == "cus_123"
    # Catalogue: free + basic + pro, in that order.
    assert [p["plan"] for p in data["plans"]] == ["free", "basic", "pro"]


def test_billing_me_free_tier_when_no_subscription(test_client, mint_token, fake_billing):
    fake_billing["plan"] = "free"
    fake_billing["subscription"] = None
    resp = test_client.get(
        "/api/v1/billing/me",
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["plan"] == "free"
    assert data["subscription"] is None


def test_billing_me_returns_owner_plan_from_jwt_email(
    test_client, mint_token, fake_billing, monkeypatch
):
    monkeypatch.setenv("MINDMARKET_OWNER_EMAILS", "owner@mindmarket.test")
    fake_billing["plan"] = "free"

    resp = test_client.get(
        "/api/v1/billing/me",
        headers={"Authorization": f"Bearer {mint_token(email='owner@mindmarket.test')}"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["plan"] == "owner"
    assert data["credits"]["unlimited"] is True


def test_billing_me_falls_back_to_free_on_plan_lookup_failure(
    test_client, mint_token, fake_billing
):
    fake_billing["plan_raise"] = RuntimeError("supabase down")
    resp = test_client.get(
        "/api/v1/billing/me",
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    # Fail-closed for billing = free tier surfaces, not 500.
    assert resp.status_code == 200
    assert resp.json()["data"]["plan"] == "free"


# ── /billing/checkout_session ─────────────────────────────────────


def test_checkout_requires_bearer(test_client):
    resp = test_client.post("/api/v1/billing/checkout_session", json={"plan": "basic"})
    assert resp.status_code == 401


def test_checkout_rejects_invalid_plan(test_client, mint_token, fake_billing):
    resp = test_client.post(
        "/api/v1/billing/checkout_session",
        json={"plan": "owner"},
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation_failed"


def test_checkout_happy_path_returns_stripe_url(test_client, mint_token, fake_billing):
    fake_billing["checkout_result"] = _FakeCheckoutResult(
        url="https://checkout.stripe.com/c/pay/cs_test_abc",
        session_id="cs_test_abc",
    )
    resp = test_client.post(
        "/api/v1/billing/checkout_session",
        json={"plan": "basic"},
        headers={"Authorization": f"Bearer {mint_token(email='owner@mindmarket.test')}"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["checkout_url"].startswith("https://checkout.stripe.com/")
    assert data["session_id"] == "cs_test_abc"

    # Verify libs received the right args. Important: the route MUST
    # pass user.id + user.email — clients never inject these.
    call = fake_billing["checkout_calls"][0]
    assert call["user_id"] == "user-abc-123"
    assert call["email"] == "owner@mindmarket.test"
    assert call["plan"] == "basic"
    # Default success/cancel paths point to the new Next.js routes.
    assert call["success_path"] == "/settings?checkout=success"
    assert call["cancel_path"] == "/pricing?checkout=cancelled"


def test_checkout_accepts_custom_success_and_cancel_paths(test_client, mint_token, fake_billing):
    fake_billing["checkout_result"] = _FakeCheckoutResult(
        url="https://checkout.stripe.com/x",
        session_id="cs",
    )
    resp = test_client.post(
        "/api/v1/billing/checkout_session",
        json={
            "plan": "pro",
            "success_path": "/settings?welcome=1",
            "cancel_path": "/pricing?try=again",
        },
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    assert resp.status_code == 200
    call = fake_billing["checkout_calls"][0]
    assert call["success_path"] == "/settings?welcome=1"
    assert call["cancel_path"] == "/pricing?try=again"


def test_checkout_rejects_paths_without_leading_slash(test_client, mint_token, fake_billing):
    """Open-redirect guard: the path must be local (starts with `/`).
    Pydantic pattern blocks absolute URLs at the boundary."""
    resp = test_client.post(
        "/api/v1/billing/checkout_session",
        json={"plan": "basic", "success_path": "https://evil.com"},
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    assert resp.status_code == 422


def test_checkout_missing_email_returns_specific_code(test_client, mint_token, fake_billing):
    resp = test_client.post(
        "/api/v1/billing/checkout_session",
        json={"plan": "basic"},
        headers={"Authorization": f"Bearer {mint_token(email=None)}"},
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "email_required"


def test_checkout_stripe_config_error_maps_to_503(test_client, mint_token, fake_billing):
    class StripeConfigError(RuntimeError):
        pass

    fake_billing["checkout_raise"] = StripeConfigError("Missing STRIPE_SECRET_KEY")
    resp = test_client.post(
        "/api/v1/billing/checkout_session",
        json={"plan": "basic"},
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    assert resp.status_code == 503
    body = resp.json()
    assert body["error"]["code"] == "billing_not_configured"
    # The class name is in details for ops; the secret-key text MUST
    # NOT leak in the message.
    assert "STRIPE_SECRET_KEY" not in body["error"]["message"]


def test_checkout_generic_stripe_error_maps_to_502(test_client, mint_token, fake_billing):
    fake_billing["checkout_raise"] = RuntimeError("Stripe API timeout")
    resp = test_client.post(
        "/api/v1/billing/checkout_session",
        json={"plan": "basic"},
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    assert resp.status_code == 502
    body = resp.json()
    assert body["error"]["code"] == "stripe_error"
    # The upstream timeout text MUST NOT leak in the message.
    assert "Stripe API timeout" not in body["error"]["message"]


# ── /billing/portal_session ───────────────────────────────────────


def test_portal_requires_bearer(test_client):
    resp = test_client.post("/api/v1/billing/portal_session", json={})
    assert resp.status_code == 401


def test_portal_returns_specific_code_when_no_customer(test_client, mint_token, fake_billing):
    # Default fixture state: subscription is None → no Stripe customer.
    resp = test_client.post(
        "/api/v1/billing/portal_session",
        json={},
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "no_stripe_customer"


def test_portal_happy_path(test_client, mint_token, fake_billing):
    fake_billing["subscription"] = {
        "stripe_customer_id": "cus_paid",
        "stripe_subscription_id": "sub_paid",
        "plan": "pro",
        "status": "active",
    }
    fake_billing["portal_url"] = "https://billing.stripe.com/p/session/x"

    resp = test_client.post(
        "/api/v1/billing/portal_session",
        json={"return_path": "/settings?from=portal"},
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["portal_url"].startswith("https://billing.stripe.com/")

    call = fake_billing["portal_calls"][0]
    # CRUCIAL: the customer id used was the one fetched server-side,
    # NOT whatever the client might have sent.
    assert call["stripe_customer_id"] == "cus_paid"
    assert call["return_path"] == "/settings?from=portal"


def test_portal_stripe_error_maps_to_502(test_client, mint_token, fake_billing):
    fake_billing["subscription"] = {"stripe_customer_id": "cus_x"}
    fake_billing["portal_raise"] = RuntimeError("portal create failed")
    resp = test_client.post(
        "/api/v1/billing/portal_session",
        json={},
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    assert resp.status_code == 502
    assert resp.json()["error"]["code"] == "stripe_error"
