"""Account deletion — the Privacy Policy's "delete your account" made real.

Flow (fail-closed at every step):
1. The caller is the AUTHENTICATED user (their JWT) — the user id comes from
   the token, never from a request parameter, so a user can only ever delete
   THEMSELVES.
2. If the user has a live Stripe subscription it is CANCELED first; if that
   cancel cannot be performed (no key, API error) the deletion aborts with a
   clear error rather than silently leaving a paid subscription behind.
3. The auth user is deleted via the server-only Supabase ADMIN client; every
   user table (profiles, portfolios, portfolio_snapshots, saved_insights,
   subscriptions, usage_events, digest_prefs, digest_sends) references
   auth.users(id) ON DELETE CASCADE, so the row removal cascades the lot.

Backups note (mirrored in the Privacy Policy): weekly encrypted database
backups age out within 90 days; deleted data disappears from them as they
rotate.
"""

from __future__ import annotations

import logging
import os

_log = logging.getLogger(__name__)

CONFIRMATION_PHRASE = "DELETE MY ACCOUNT"

# Stripe statuses that no longer bill — safe to delete the account without
# touching Stripe. Anything else (active/trialing/past_due/unpaid/paused…)
# must be canceled first.
_INACTIVE_SUB_STATUSES = {"canceled", "incomplete_expired"}


class SubscriptionCancelError(Exception):
    """A live subscription exists and could not be canceled — fail closed."""


class AccountDeleteError(Exception):
    """The auth-user deletion itself failed."""


def _cancel_stripe_subscription(subscription_id: str) -> None:
    secret_key = os.environ.get("STRIPE_SECRET_KEY", "")
    if not secret_key:
        raise SubscriptionCancelError(
            "A live subscription exists but Stripe is not configured on the "
            "server — contact support to cancel before deleting."
        )
    try:
        import stripe

        stripe.api_key = secret_key
        stripe.Subscription.cancel(subscription_id)
    except Exception as exc:  # noqa: BLE001 - fail closed with the class only
        raise SubscriptionCancelError(
            "Your subscription could not be canceled automatically — nothing "
            "was deleted. Cancel it from Settings → Manage subscription (or "
            "contact support), then retry."
        ) from exc


def delete_account(user_id: str) -> dict:
    """Cancel any live subscription, then delete the auth user (cascades all
    user data). Raises SubscriptionCancelError / AccountDeleteError — the
    router maps them to clear HTTP errors. Never partially deletes."""
    from libs.billing.usage import get_subscription_record

    subscription_canceled = False
    sub = get_subscription_record(user_id)
    if sub and sub.get("stripe_subscription_id"):
        status = str(sub.get("status") or "").lower()
        if status not in _INACTIVE_SUB_STATUSES:
            _cancel_stripe_subscription(str(sub["stripe_subscription_id"]))
            subscription_canceled = True
            _log.info("account.delete.subscription_canceled user=%s", user_id)

    try:
        from libs.auth.admin_client import get_supabase_admin

        get_supabase_admin().auth.admin.delete_user(user_id)
    except Exception as exc:  # noqa: BLE001
        _log.error("account.delete.failed user=%s err=%s", user_id, type(exc).__name__)
        raise AccountDeleteError(
            "Account deletion failed on the server — nothing was removed. "
            "Please retry or contact support."
        ) from exc

    _log.info("account.delete.completed user=%s", user_id)
    return {"deleted": True, "subscription_canceled": subscription_canceled}
