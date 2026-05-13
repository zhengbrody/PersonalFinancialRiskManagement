"""
Stripe event sync into Supabase billing tables.

The webhook handler verifies Stripe signatures, then delegates here with the
decoded event payload. Writes require the Supabase service-role client because
regular users must not be able to self-edit `profiles.plan`.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Optional

from libs.auth.admin_client import get_supabase_admin

VALID_PLANS = {"free", "basic", "pro"}


def _read_secret(key: str) -> str:
    val = os.environ.get(key)
    if val:
        return val
    try:
        import streamlit as st

        return st.secrets.get(key, "")
    except Exception:
        return ""


def _iso_from_unix(value: Optional[int]) -> Optional[str]:
    if value in (None, ""):
        return None
    return datetime.fromtimestamp(int(value), tz=timezone.utc).isoformat()


def _plan_from_price_id(price_id: Optional[str], fallback: str = "free") -> str:
    mapping = {
        _read_secret("STRIPE_BASIC_PRICE_ID"): "basic",
        _read_secret("STRIPE_PRO_PRICE_ID"): "pro",
    }
    plan = mapping.get(price_id) or fallback
    return plan if plan in VALID_PLANS else "free"


def _plan_from_subscription(subscription: dict[str, Any], fallback: str = "free") -> str:
    meta_plan = (subscription.get("metadata") or {}).get("plan")
    if meta_plan in VALID_PLANS:
        return meta_plan

    try:
        item = (subscription.get("items") or {}).get("data", [])[0]
        price_id = (item.get("price") or {}).get("id")
    except Exception:
        price_id = None
    return _plan_from_price_id(price_id, fallback=fallback)


def _active_plan(plan: str, status: str) -> str:
    return plan if status in ("active", "trialing") else "free"


def _upsert_profile_plan(user_id: str, email: Optional[str], plan: str) -> None:
    sb = get_supabase_admin()
    sb.table("profiles").upsert(
        {"user_id": user_id, "email": email, "plan": plan},
        on_conflict="user_id",
    ).execute()


def _upsert_subscription(row: dict[str, Any]) -> None:
    get_supabase_admin().table("subscriptions").upsert(
        row,
        on_conflict="user_id",
    ).execute()


def sync_checkout_session(session: dict[str, Any]) -> dict[str, Any]:
    """Sync `checkout.session.completed` into subscriptions + profiles."""
    user_id = session.get("client_reference_id") or (session.get("metadata") or {}).get("user_id")
    if not user_id:
        raise ValueError("Checkout session missing user_id/client_reference_id.")

    plan = (session.get("metadata") or {}).get("plan", "basic")
    if plan not in VALID_PLANS:
        plan = "basic"

    status = "active"
    row = {
        "user_id": user_id,
        "stripe_customer_id": session.get("customer"),
        "stripe_subscription_id": session.get("subscription"),
        "plan": plan,
        "status": status,
        "cancel_at_period_end": False,
    }
    _upsert_subscription(row)
    _upsert_profile_plan(user_id, session.get("customer_email"), _active_plan(plan, status))
    return {"user_id": user_id, "plan": plan, "status": status}


def sync_subscription(subscription: dict[str, Any], *, deleted: bool = False) -> dict[str, Any]:
    """Sync Stripe customer.subscription.* events."""
    metadata = subscription.get("metadata") or {}
    user_id = metadata.get("user_id")
    if not user_id:
        raise ValueError("Subscription event missing metadata.user_id.")

    status = "canceled" if deleted else subscription.get("status", "active")
    plan = _plan_from_subscription(subscription, fallback=metadata.get("plan", "free"))
    profile_plan = _active_plan(plan, status)

    row = {
        "user_id": user_id,
        "stripe_customer_id": subscription.get("customer"),
        "stripe_subscription_id": subscription.get("id"),
        "plan": plan,
        "status": (
            status if status in ("active", "past_due", "canceled", "trialing") else "past_due"
        ),
        "current_period_start": _iso_from_unix(subscription.get("current_period_start")),
        "current_period_end": _iso_from_unix(subscription.get("current_period_end")),
        "cancel_at_period_end": bool(subscription.get("cancel_at_period_end", False)),
    }
    _upsert_subscription(row)
    _upsert_profile_plan(user_id, None, profile_plan)
    return {"user_id": user_id, "plan": profile_plan, "status": row["status"]}


def handle_stripe_event(event: dict[str, Any]) -> dict[str, Any]:
    """Dispatch a verified Stripe event payload."""
    event_type = event.get("type")
    obj = ((event.get("data") or {}).get("object")) or {}

    if event_type == "checkout.session.completed":
        return sync_checkout_session(obj)
    if event_type in ("customer.subscription.created", "customer.subscription.updated"):
        return sync_subscription(obj)
    if event_type == "customer.subscription.deleted":
        return sync_subscription(obj, deleted=True)

    return {"ignored": True, "type": event_type}
