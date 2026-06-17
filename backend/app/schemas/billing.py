"""Request + response shapes for ``/api/v1/billing/*``."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

# Only the two paid plans can be checked-out from the API. Free is
# implicit; owner is operator-internal.
PaidPlan = Literal["basic", "pro"]


class PlanCard(BaseModel):
    """One row of the pricing table the frontend renders."""

    plan: str
    label: str
    price_usd_per_month: float
    monthly_analysis: int
    monthly_chat: int
    # HeyGen-style monthly AI credits (1 credit = $0.01 LLM cost) — the
    # primary, user-facing allowance. monthly_analysis/chat are kept for
    # backward-compat but are no longer the gate.
    monthly_credits: int = 0


class SubscriptionOut(BaseModel):
    """Mirror of the ``public.subscriptions`` row for the current user.

    All fields are optional because users on the implicit free tier
    never had a row created — the frontend renders the table-row-
    missing case as "Free plan, no Stripe history".
    """

    stripe_customer_id: Optional[str] = None
    stripe_subscription_id: Optional[str] = None
    plan: Optional[str] = None
    status: Optional[str] = None
    current_period_start: Optional[str] = None
    current_period_end: Optional[str] = None
    cancel_at_period_end: Optional[bool] = None


class BillingMeResponse(BaseModel):
    """Payload for ``GET /api/v1/billing/me``."""

    user_id: str
    email: Optional[str] = None
    plan: str
    subscription: Optional[SubscriptionOut] = None
    plans: list[PlanCard] = Field(default_factory=list)
    # Monthly AI credit balance (HeyGen-style metering). None fields when the
    # plan is unlimited (owner). Shaped by libs.billing.usage.get_credit_status.
    credits: Optional[dict] = None


class CheckoutSessionRequest(BaseModel):
    """Body for ``POST /api/v1/billing/checkout_session``."""

    plan: PaidPlan
    # Override the post-redirect paths in case the caller is hosted on a
    # different shell (e.g. mobile app preview). Defaults send the user
    # back to /settings on success and /pricing on cancel.
    success_path: Optional[str] = Field(default=None, max_length=200, pattern=r"^/")
    cancel_path: Optional[str] = Field(default=None, max_length=200, pattern=r"^/")


class CheckoutSessionResponse(BaseModel):
    checkout_url: str
    session_id: str


class PortalSessionRequest(BaseModel):
    """Body for ``POST /api/v1/billing/portal_session``."""

    return_path: Optional[str] = Field(default=None, max_length=200, pattern=r"^/")


class PortalSessionResponse(BaseModel):
    portal_url: str


class AnthropicTopupRequest(BaseModel):
    """Body for ``POST /api/v1/billing/admin/anthropic-topup`` — the owner's
    current Claude balance after a top-up (since Anthropic has no balance API)."""

    balance: float = Field(ge=0, le=1_000_000)
