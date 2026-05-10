"""
Stripe Checkout helpers used by the Streamlit Pricing page.

All Stripe keys and price IDs are server-side settings:
    STRIPE_SECRET_KEY
    STRIPE_BASIC_PRICE_ID
    STRIPE_PRO_PRICE_ID
    MINDMARKET_APP_URL
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from .usage import PLAN_PRICING


class StripeConfigError(RuntimeError):
    """Raised when Stripe env/secrets are missing or inconsistent."""


@dataclass(frozen=True)
class CheckoutResult:
    url: str
    session_id: str


def _read_secret(key: str) -> str:
    val = os.environ.get(key)
    if val:
        return val
    try:
        import streamlit as st

        return st.secrets.get(key, "")
    except Exception:
        return ""


def _price_id_for_plan(plan: str) -> str:
    if plan == "basic":
        env_key = "STRIPE_BASIC_PRICE_ID"
    elif plan == "pro":
        env_key = "STRIPE_PRO_PRICE_ID"
    else:
        raise StripeConfigError(f"Unsupported paid plan: {plan}")

    price_id = _read_secret(env_key)
    if not price_id:
        raise StripeConfigError(f"Missing {env_key}. Create the Stripe price first.")
    return price_id


def _app_url() -> str:
    url = _read_secret("MINDMARKET_APP_URL") or "http://localhost:8501"
    return url.rstrip("/")


def create_checkout_session(
    *,
    user_id: str,
    email: str,
    plan: str,
    success_path: str = "/Pricing?checkout=success",
    cancel_path: str = "/Pricing?checkout=cancelled",
) -> CheckoutResult:
    """Create a Stripe subscription Checkout Session for a paid plan."""
    if plan not in ("basic", "pro"):
        raise StripeConfigError("Checkout is only supported for basic/pro plans.")

    secret_key = _read_secret("STRIPE_SECRET_KEY")
    if not secret_key:
        raise StripeConfigError("Missing STRIPE_SECRET_KEY.")

    try:
        import stripe
    except ImportError as e:
        raise StripeConfigError("stripe package not installed. Add stripe to requirements.") from e

    stripe.api_key = secret_key
    price_id = _price_id_for_plan(plan)
    base = _app_url()

    session = stripe.checkout.Session.create(
        mode="subscription",
        payment_method_types=["card"],
        line_items=[{"price": price_id, "quantity": 1}],
        customer_email=email or None,
        client_reference_id=user_id,
        success_url=f"{base}{success_path}",
        cancel_url=f"{base}{cancel_path}",
        metadata={"user_id": user_id, "plan": plan},
        subscription_data={"metadata": {"user_id": user_id, "plan": plan}},
        allow_promotion_codes=True,
    )

    url: Optional[str] = getattr(session, "url", None) or session.get("url")
    session_id: Optional[str] = getattr(session, "id", None) or session.get("id")
    if not url or not session_id:
        raise StripeConfigError("Stripe did not return a Checkout URL.")
    return CheckoutResult(url=url, session_id=session_id)


def paid_plan_cards() -> list[dict]:
    """Return pricing metadata for UI rendering."""
    return [
        {
            "plan": "basic",
            "label": PLAN_PRICING["basic"]["label"],
            "price": PLAN_PRICING["basic"]["price_usd_per_month"],
            "analysis": 30,
            "chat": 100,
        },
        {
            "plan": "pro",
            "label": PLAN_PRICING["pro"]["label"],
            "price": PLAN_PRICING["pro"]["price_usd_per_month"],
            "analysis": 150,
            "chat": 500,
        },
    ]
