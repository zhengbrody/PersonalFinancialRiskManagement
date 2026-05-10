"""
libs.billing — quota + usage tracking for the freemium tier.

Public surface:
    PLAN_LIMITS                — dict of plan name → kind → monthly cap
    QuotaExceeded              — raised when user hits their cap
    check_and_consume(user_id, kind, **metadata)
                                — atomic "I'm about to do this" call;
                                  raises QuotaExceeded or records the
                                  event and returns the new count
    get_quota_status(user_id)  — read-only summary for UI display
                                  ({plan, used, limit, remaining})
    create_checkout_session(...) — create a Stripe Checkout session for
                                  Basic / Pro upgrades

Design notes:

  - Append-only `usage_events` is the source of truth. `monthly_usage`
    view aggregates for fast reads. We never UPDATE usage; only INSERT.

  - Quota check is best-effort consistency: a user could in theory race
    two simultaneous requests past the limit. At our scale + cost model
    that's acceptable — over by 1-2 events doesn't break the tier.
    Later: move to a serializable transaction or a Postgres counter row.

  - `kind` is one of {"analysis", "chat", "tool_call"}. Plans gate
    "analysis" and "chat"; "tool_call" is recorded for cost tracking
    but not currently rate-limited.
"""
from .usage import (
    PLAN_LIMITS,
    PLAN_PRICING,
    QuotaExceeded,
    check_and_consume,
    get_quota_status,
    get_user_plan,
    record_event,
)

try:
    from .stripe_checkout import CheckoutResult, StripeConfigError, create_checkout_session
except Exception:  # pragma: no cover - keeps quota module importable without stripe extras
    CheckoutResult = None
    StripeConfigError = RuntimeError
    create_checkout_session = None

__all__ = [
    "PLAN_LIMITS",
    "PLAN_PRICING",
    "QuotaExceeded",
    "check_and_consume",
    "get_quota_status",
    "get_user_plan",
    "record_event",
    "CheckoutResult",
    "StripeConfigError",
    "create_checkout_session",
]
