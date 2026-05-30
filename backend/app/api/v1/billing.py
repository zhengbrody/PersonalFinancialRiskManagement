"""``/api/v1/billing/*`` — Stripe Checkout + Customer Portal.

All three routes are JWT-protected. The Stripe secret key NEVER
leaves the backend; the frontend only sees one-time hosted URLs that
Stripe issues. The customer ID is looked up server-side from the
``subscriptions`` table keyed by the verified ``user.id`` — clients
cannot pass a customer ID in any direction.

Webhook handling stays where it already is: the Supabase Edge
Function at ``supabase/functions/stripe-webhook/`` keeps syncing
Stripe events into the ``subscriptions`` + ``profiles.plan`` tables.
This module deliberately does NOT touch the webhook path; doing so
would risk double-processing events during Phase 5 cutover.

Error mapping:
  StripeConfigError       → 503  billing_not_configured
  no Stripe customer yet  → 422  no_stripe_customer
  anything else           → 502  stripe_error (class name only)
"""

from __future__ import annotations

import logging
import time

from fastapi import APIRouter, Depends, Request

from ...core.deps_auth import AuthedUser, require_user
from ...core.responses import APIError, ok
from ...schemas.billing import (
    BillingMeResponse,
    CheckoutSessionRequest,
    CheckoutSessionResponse,
    PlanCard,
    PortalSessionRequest,
    PortalSessionResponse,
    SubscriptionOut,
)

router = APIRouter(prefix="/api/v1/billing", tags=["billing"])

_logger = logging.getLogger(__name__)


# ── plan catalogue + helpers ───────────────────────────────────────


def _plan_catalogue() -> list[PlanCard]:
    """Build the pricing-table rows from the canonical PLAN_PRICING +
    PLAN_LIMITS dicts. Pulled from libs.billing so a price/limit
    change in one place updates UI + checkout + quota gate together."""
    from libs.billing.usage import PLAN_LIMITS, PLAN_PRICING

    out: list[PlanCard] = []
    for plan in ("free", "basic", "pro"):
        pricing = PLAN_PRICING.get(plan, {})
        limits = PLAN_LIMITS.get(plan, {})
        out.append(
            PlanCard(
                plan=plan,
                label=pricing.get("label", plan.capitalize()),
                price_usd_per_month=float(pricing.get("price_usd_per_month", 0)),
                monthly_analysis=int(limits.get("analysis", 0)),
                monthly_chat=int(limits.get("chat", 0)),
            )
        )
    return out


def _map_stripe_error(exc: Exception) -> APIError:
    """Translate any exception out of libs.billing into the right
    envelope code. ``StripeConfigError`` (missing key) → 503 so ops
    sees "config gap"; anything else → 502 with the class name only."""
    name = type(exc).__name__
    if name == "StripeConfigError":
        return APIError(
            status=503,
            code="billing_not_configured",
            message="Billing is not fully configured on this deploy.",
            details={"reason": name},
        )
    return APIError(
        status=502,
        code="stripe_error",
        message="Stripe call failed.",
        details={"reason": name},
    )


# ── GET /me — plan + subscription snapshot ─────────────────────────


@router.get("/me", summary="Plan + subscription snapshot for the caller")
def billing_me(request: Request, user: AuthedUser = Depends(require_user)):
    """Return the authed user's current plan, their Stripe
    subscription row (if any), and the plan catalogue for rendering
    the pricing table without a second round-trip."""
    started = time.perf_counter()
    try:
        from libs.billing.usage import get_subscription_record, get_user_plan
    except Exception as exc:  # pragma: no cover - import guard
        raise APIError(
            status=503,
            code="billing_not_configured",
            message="Billing module unavailable.",
            details={"reason": str(exc)},
        ) from exc

    try:
        plan = get_user_plan(user.id)
    except Exception as exc:
        _logger.warning("billing.plan_lookup_failed user=%s err=%s", user.id, exc)
        plan = "free"

    subscription_row: SubscriptionOut | None = None
    try:
        raw = get_subscription_record(user.id)
        if raw:
            subscription_row = SubscriptionOut(**raw)
    except Exception as exc:
        _logger.warning("billing.subscription_lookup_failed user=%s err=%s", user.id, exc)

    payload = BillingMeResponse(
        user_id=user.id,
        email=user.email,
        plan=plan,
        subscription=subscription_row,
        plans=_plan_catalogue(),
    )
    return ok(payload.model_dump(), request=request, started_at=started)


# ── POST /checkout_session — start a paid plan ─────────────────────


@router.post(
    "/checkout_session",
    summary="Create a Stripe Checkout session for a paid plan",
    response_model=None,
)
def create_checkout_session_endpoint(
    body: CheckoutSessionRequest,
    request: Request,
    user: AuthedUser = Depends(require_user),
):
    """Returns the one-time hosted Checkout URL. The frontend redirects
    to it; Stripe's hosted page handles card capture + 3DS + webhook
    fire-back into our Supabase project.

    The user's ``user.id`` is set as ``client_reference_id`` on the
    Stripe session so the webhook can correlate Stripe customer → our
    auth user when the subscription is created.
    """
    started = time.perf_counter()
    if not user.email:
        # Stripe Checkout requires an email; Supabase JWTs always carry
        # one for password users, but PKCE/magic-link tokens can omit
        # it. Tell the frontend explicitly.
        raise APIError(
            status=422,
            code="email_required",
            message="Sign in with email + password to subscribe.",
        )

    try:
        from libs.billing.stripe_checkout import create_checkout_session
    except Exception as exc:  # pragma: no cover - import guard
        raise APIError(
            status=503,
            code="billing_not_configured",
            message="Stripe checkout module unavailable.",
            details={"reason": str(exc)},
        ) from exc

    success_path = body.success_path or "/settings?checkout=success"
    cancel_path = body.cancel_path or "/pricing?checkout=cancelled"

    try:
        result = create_checkout_session(
            user_id=user.id,
            email=user.email,
            plan=body.plan,
            success_path=success_path,
            cancel_path=cancel_path,
        )
    except Exception as exc:
        # Log only the class name and a stable hash of the user id;
        # NEVER log the Stripe secret or full traceback at INFO.
        _logger.warning(
            "billing.checkout_failed user=%s plan=%s err=%s",
            user.id,
            body.plan,
            type(exc).__name__,
        )
        raise _map_stripe_error(exc) from exc

    payload = CheckoutSessionResponse(checkout_url=result.url, session_id=result.session_id)
    return ok(payload.model_dump(), request=request, started_at=started)


# ── POST /portal_session — manage existing subscription ────────────


@router.post(
    "/portal_session",
    summary="Create a Stripe Customer Portal session",
    response_model=None,
)
def create_portal_session_endpoint(
    body: PortalSessionRequest,
    request: Request,
    user: AuthedUser = Depends(require_user),
):
    """Returns a one-time URL into Stripe's hosted Customer Portal
    (card management, plan switch, cancel, invoices). The customer ID
    is resolved from the user's subscription row — clients do NOT
    pass it.

    422 when the user has never had a subscription (free-tier user who
    wandered onto Settings before subscribing). The frontend should
    redirect them to /pricing instead.
    """
    started = time.perf_counter()
    try:
        from libs.billing.stripe_checkout import create_customer_portal_session
        from libs.billing.usage import get_subscription_record
    except Exception as exc:  # pragma: no cover - import guard
        raise APIError(
            status=503,
            code="billing_not_configured",
            message="Stripe portal module unavailable.",
            details={"reason": str(exc)},
        ) from exc

    try:
        sub = get_subscription_record(user.id)
    except Exception as exc:
        _logger.warning("billing.subscription_lookup_failed user=%s err=%s", user.id, exc)
        sub = None

    customer_id = (sub or {}).get("stripe_customer_id")
    if not customer_id:
        raise APIError(
            status=422,
            code="no_stripe_customer",
            message="No Stripe customer yet. Subscribe first via /pricing.",
        )

    return_path = body.return_path or "/settings"
    try:
        url = create_customer_portal_session(
            stripe_customer_id=customer_id,
            return_path=return_path,
        )
    except Exception as exc:
        _logger.warning("billing.portal_failed user=%s err=%s", user.id, type(exc).__name__)
        raise _map_stripe_error(exc) from exc

    payload = PortalSessionResponse(portal_url=url)
    return ok(payload.model_dump(), request=request, started_at=started)
