"""Tests for Stripe checkout/session sync. No real Stripe or Supabase calls."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


def test_create_checkout_session_uses_server_config(monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test")
    monkeypatch.setenv("STRIPE_BASIC_PRICE_ID", "price_basic")
    monkeypatch.setenv("MINDMARKET_APP_URL", "https://mindmarket.ai")

    fake_stripe = SimpleNamespace()
    fake_stripe.checkout = SimpleNamespace()
    fake_stripe.checkout.Session = SimpleNamespace()
    fake_stripe.checkout.Session.create = MagicMock(
        return_value={"id": "cs_test", "url": "https://checkout.stripe.com/cs_test"}
    )
    monkeypatch.setitem(sys.modules, "stripe", fake_stripe)

    from libs.billing.stripe_checkout import create_checkout_session

    out = create_checkout_session(user_id="user-1", email="x@y.com", plan="basic")
    assert out.session_id == "cs_test"
    assert out.url.startswith("https://checkout.stripe.com")

    kwargs = fake_stripe.checkout.Session.create.call_args.kwargs
    assert kwargs["mode"] == "subscription"
    assert kwargs["client_reference_id"] == "user-1"
    assert kwargs["line_items"][0]["price"] == "price_basic"
    assert kwargs["metadata"] == {"user_id": "user-1", "plan": "basic"}
    assert kwargs["subscription_data"]["metadata"]["user_id"] == "user-1"


def test_create_checkout_session_requires_paid_plan(monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test")
    from libs.billing.stripe_checkout import StripeConfigError, create_checkout_session

    with pytest.raises(StripeConfigError):
        create_checkout_session(user_id="user-1", email="x@y.com", plan="free")


def test_sync_subscription_updates_subscription_and_profile(monkeypatch):
    from libs.billing import stripe_sync

    sb = MagicMock()
    sb.table.return_value = sb
    sb.upsert.return_value = sb
    sb.execute.return_value = MagicMock(data=[])
    monkeypatch.setattr(stripe_sync, "get_supabase_admin", lambda: sb)

    result = stripe_sync.sync_subscription(
        {
            "id": "sub_1",
            "customer": "cus_1",
            "status": "active",
            "metadata": {"user_id": "user-1", "plan": "basic"},
            "current_period_start": 1_700_000_000,
            "current_period_end": 1_702_592_000,
            "cancel_at_period_end": False,
        }
    )

    assert result == {"user_id": "user-1", "plan": "basic", "status": "active"}
    table_names = [call.args[0] for call in sb.table.call_args_list]
    assert "subscriptions" in table_names
    assert "profiles" in table_names


def test_sync_deleted_subscription_downgrades_profile(monkeypatch):
    from libs.billing import stripe_sync

    sb = MagicMock()
    sb.table.return_value = sb
    sb.upsert.return_value = sb
    sb.execute.return_value = MagicMock(data=[])
    monkeypatch.setattr(stripe_sync, "get_supabase_admin", lambda: sb)

    result = stripe_sync.sync_subscription(
        {
            "id": "sub_1",
            "customer": "cus_1",
            "metadata": {"user_id": "user-1", "plan": "pro"},
        },
        deleted=True,
    )

    assert result["plan"] == "free"
    profile_upsert = sb.upsert.call_args_list[-1].args[0]
    assert profile_upsert["plan"] == "free"


def _load_webhook_handler():
    path = Path(__file__).resolve().parents[2] / "services" / "billing-webhook" / "handler.py"
    spec = importlib.util.spec_from_file_location("billing_webhook_handler", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_webhook_handler_verifies_and_dispatches(monkeypatch):
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec")
    handler = _load_webhook_handler()

    fake_event = {
        "type": "checkout.session.completed",
        "data": {"object": {"client_reference_id": "user-1", "metadata": {"plan": "basic"}}},
    }
    fake_stripe = SimpleNamespace()
    fake_stripe.Webhook = SimpleNamespace(construct_event=MagicMock(return_value=fake_event))
    monkeypatch.setitem(sys.modules, "stripe", fake_stripe)
    monkeypatch.setattr(handler, "handle_stripe_event", lambda event: {"synced": event["type"]})

    resp = handler.lambda_handler(
        {"body": json.dumps(fake_event), "headers": {"stripe-signature": "sig"}},
        None,
    )
    assert resp["statusCode"] == 200
    assert json.loads(resp["body"])["result"] == {"synced": "checkout.session.completed"}


def test_webhook_handler_rejects_missing_signature(monkeypatch):
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec")
    handler = _load_webhook_handler()

    resp = handler.lambda_handler({"body": "{}", "headers": {}}, None)
    assert resp["statusCode"] == 400


def test_webhook_rejects_invalid_signature(monkeypatch):
    """A forged/invalid signature must produce a 400 (NOT 200, NOT 500).

    - 200 would be a silent accept — game over for billing integrity.
    - 500 would tell Stripe the failure is transient and it would keep
      replaying the same forged event, amplifying the attack.
    Only 400 makes Stripe drop the delivery, which is the desired
    behavior. The downstream `handle_stripe_event` must also NEVER be
    invoked when the signature fails to verify.
    """
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec")
    handler = _load_webhook_handler()

    # Fake stripe module whose construct_event raises a Stripe-shaped
    # SignatureVerificationError. We don't depend on the real stripe
    # package being installed; the handler only catches `Exception`.
    class _SignatureVerificationError(Exception):
        pass

    def _raise(*_args, **_kwargs):
        raise _SignatureVerificationError("No signatures found matching the expected signature")

    fake_stripe = SimpleNamespace()
    fake_stripe.Webhook = SimpleNamespace(construct_event=MagicMock(side_effect=_raise))
    fake_stripe.error = SimpleNamespace(SignatureVerificationError=_SignatureVerificationError)
    monkeypatch.setitem(sys.modules, "stripe", fake_stripe)

    # If the handler ever calls handle_stripe_event after a bad sig,
    # this spy will record it and the assert below will fail.
    spy = MagicMock(return_value={"synced": "BOOM"})
    monkeypatch.setattr(handler, "handle_stripe_event", spy)

    resp = handler.lambda_handler(
        {
            "body": json.dumps({"type": "checkout.session.completed", "data": {}}),
            "headers": {"stripe-signature": "t=1,v1=forged"},
        },
        None,
    )

    # 400 — Stripe will stop retrying. This is the critical assertion.
    assert resp["statusCode"] == 400
    body = json.loads(resp["body"])
    assert "error" in body
    # The error surface should mention the invalid webhook so operators
    # can grep logs. Keep the assertion loose so message tweaks don't
    # break the test.
    assert "Invalid" in body["error"] or "signature" in body["error"].lower()

    # Most important: the forged event must never reach the sync path.
    spy.assert_not_called()
