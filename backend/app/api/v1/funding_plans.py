"""Explicit save and read-only review of authenticated combined scenarios."""

from copy import deepcopy
from dataclasses import asdict
from uuid import UUID

from fastapi import APIRouter, Depends, Request

from ...core.deps_auth import AuthedUser, require_user
from ...core.responses import APIError, ok
from ...schemas.envelope import Envelope
from ...schemas.funding_plan import (
    ConfirmFundingPlan,
    FundingPlanReview,
    ReviewFundingPlanRequest,
    SavedFundingPlan,
)
from ...services import comparison_save, copilot_scope, funding_plans
from . import risk

router = APIRouter(prefix="/api/v1/copilot/funding-plans", tags=["copilot"])


@router.post("/{result_id}/confirm", response_model=Envelope[SavedFundingPlan])
def confirm(
    result_id: UUID,
    body: ConfirmFundingPlan,
    request: Request,
    user: AuthedUser = Depends(require_user),
):
    if not body.confirmed:
        raise APIError(422, "confirmation_required", "Confirm saving this original scenario.")
    funding_plans.require_enabled()
    # Authenticate the receipt (HMAC + owner/book/result scope) BEFORE taking
    # the single analysis lane: a forged or foreign receipt must not occupy it.
    funding_plans.read(body.receipt, user.id, str(body.expected_portfolio_id), str(result_id))
    if not risk._check_capacity.acquire(blocking=False):
        raise APIError(503, "risk_busy", "Risk computation is busy. Retry this same result.")
    try:
        result = funding_plans.confirm(
            user.access_token,
            user.id,
            str(body.expected_portfolio_id),
            str(result_id),
            body.receipt,
        )
    finally:
        risk._check_capacity.release()
    return ok(result.model_dump(mode="json"), request=request)


@router.get("/{result_id}", response_model=Envelope[SavedFundingPlan])
def read(
    result_id: UUID,
    expected_portfolio_id: UUID,
    request: Request,
    user: AuthedUser = Depends(require_user),
):
    saved, _, _ = funding_plans.get_saved(
        user.access_token, user.id, str(expected_portfolio_id), str(result_id)
    )
    return ok(saved.model_dump(mode="json"), request=request)


@router.post("/{result_id}/review", response_model=Envelope[FundingPlanReview])
def review(
    result_id: UUID,
    body: ReviewFundingPlanRequest,
    request: Request,
    user: AuthedUser = Depends(require_user),
):
    expected = str(body.expected_portfolio_id)
    saved, snapshot, _ = funding_plans.get_saved(
        user.access_token, user.id, expected, str(result_id)
    )
    revision = comparison_save.portfolio_revision(user.access_token, user.id, expected)
    context = deepcopy(risk._resolve_active_context_or_raise(user))
    digest = copilot_scope.context_digest(asdict(context))
    result = funding_plans.review(saved, snapshot, context, revision)
    copilot_scope.verify_scope(user.access_token, expected, digest)
    if comparison_save.portfolio_revision(user.access_token, user.id, expected) != revision:
        raise APIError(409, "portfolio_changed", "The account changed during review.")
    return ok(result.model_dump(mode="json"), request=request)
