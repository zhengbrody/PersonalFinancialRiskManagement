"""Tests for Stripe checkout/session sync. No real Stripe or Supabase calls."""

from __future__ import annotations

import sys
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


def test_create_checkout_session_defaults_to_public_app_url(monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test")
    monkeypatch.setenv("STRIPE_PRO_PRICE_ID", "price_pro")
    monkeypatch.delenv("MINDMARKET_APP_URL", raising=False)

    fake_stripe = SimpleNamespace()
    fake_stripe.checkout = SimpleNamespace()
    fake_stripe.checkout.Session = SimpleNamespace()
    fake_stripe.checkout.Session.create = MagicMock(
        return_value={"id": "cs_test", "url": "https://checkout.stripe.com/cs_test"}
    )
    monkeypatch.setitem(sys.modules, "stripe", fake_stripe)

    from libs.billing.stripe_checkout import create_checkout_session

    create_checkout_session(user_id="user-1", email="x@y.com", plan="pro")

    kwargs = fake_stripe.checkout.Session.create.call_args.kwargs
    assert kwargs["success_url"] == "https://mindmarket.app/Pricing?checkout=success"
    assert kwargs["cancel_url"] == "https://mindmarket.app/Pricing?checkout=cancelled"


def test_create_checkout_session_corrects_swapped_price_ids(monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test")
    monkeypatch.setenv("STRIPE_BASIC_PRICE_ID", "price_pro")
    monkeypatch.setenv("STRIPE_PRO_PRICE_ID", "price_basic")

    def _retrieve(price_id):
        amounts = {"price_basic": 1000, "price_pro": 2500}
        return {"id": price_id, "unit_amount": amounts[price_id]}

    fake_stripe = SimpleNamespace()
    fake_stripe.Price = SimpleNamespace(retrieve=MagicMock(side_effect=_retrieve))
    fake_stripe.checkout = SimpleNamespace()
    fake_stripe.checkout.Session = SimpleNamespace()
    fake_stripe.checkout.Session.create = MagicMock(
        return_value={"id": "cs_test", "url": "https://checkout.stripe.com/cs_test"}
    )
    monkeypatch.setitem(sys.modules, "stripe", fake_stripe)

    from libs.billing.stripe_checkout import create_checkout_session

    create_checkout_session(user_id="user-1", email="x@y.com", plan="basic")
    kwargs = fake_stripe.checkout.Session.create.call_args.kwargs

    assert kwargs["line_items"][0]["price"] == "price_basic"
    assert kwargs["metadata"] == {"user_id": "user-1", "plan": "basic"}


def test_create_checkout_session_rejects_mismatched_price_amount(monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test")
    monkeypatch.setenv("STRIPE_BASIC_PRICE_ID", "price_wrong")
    monkeypatch.setenv("STRIPE_PRO_PRICE_ID", "price_also_wrong")

    def _retrieve(price_id):
        amounts = {"price_wrong": 5000, "price_also_wrong": 7500}
        return {"id": price_id, "unit_amount": amounts[price_id]}

    fake_stripe = SimpleNamespace()
    fake_stripe.Price = SimpleNamespace(retrieve=MagicMock(side_effect=_retrieve))
    fake_stripe.checkout = SimpleNamespace()
    fake_stripe.checkout.Session = SimpleNamespace()
    fake_stripe.checkout.Session.create = MagicMock()
    monkeypatch.setitem(sys.modules, "stripe", fake_stripe)

    from libs.billing.stripe_checkout import StripeConfigError, create_checkout_session

    with pytest.raises(StripeConfigError, match="does not match"):
        create_checkout_session(user_id="user-1", email="x@y.com", plan="basic")

    fake_stripe.checkout.Session.create.assert_not_called()


def test_create_checkout_session_requires_paid_plan(monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test")
    from libs.billing.stripe_checkout import StripeConfigError, create_checkout_session

    with pytest.raises(StripeConfigError):
        create_checkout_session(user_id="user-1", email="x@y.com", plan="free")


def test_stripe_redirect_url_validation_allows_stripe_hosts():
    from libs.billing.stripe_checkout import validate_stripe_redirect_url

    assert (
        validate_stripe_redirect_url("https://checkout.stripe.com/c/pay/cs_test")
        == "https://checkout.stripe.com/c/pay/cs_test"
    )
    assert (
        validate_stripe_redirect_url("https://billing.stripe.com/p/session/test")
        == "https://billing.stripe.com/p/session/test"
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://checkout.stripe.com/c/pay/cs_test",
        "https://checkout.stripe.com.evil.example/c/pay/cs_test",
        "https://evilstripe.com/c/pay/cs_test",
        "javascript:alert(1)",
        "",
    ],
)
def test_stripe_redirect_url_validation_rejects_open_redirects(url):
    from libs.billing.stripe_checkout import StripeConfigError, validate_stripe_redirect_url

    with pytest.raises(StripeConfigError):
        validate_stripe_redirect_url(url)


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


def test_sync_subscription_uses_price_amount_before_price_id_mapping(monkeypatch):
    from libs.billing import stripe_sync

    monkeypatch.setenv("STRIPE_BASIC_PRICE_ID", "price_pro")
    monkeypatch.setenv("STRIPE_PRO_PRICE_ID", "price_basic")
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
            "metadata": {"user_id": "user-1"},
            "items": {
                "data": [
                    {
                        "price": {
                            "id": "price_basic",
                            "unit_amount": 1000,
                        }
                    }
                ]
            },
        }
    )

    assert result["plan"] == "basic"


# NOTE (2026-07-17): the webhook-handler tests that used to live here loaded
# services/billing-webhook/handler.py (the retired Phase-2 Lambda experiment —
# see docs/archive/lambda-experiment.md). They were removed with it: the LIVE
# Stripe webhook is the Supabase Edge Function
# (supabase/functions/stripe-webhook/index.ts), which does its own signature
# verification. The checkout/portal/plan tests above cover libs/billing.
