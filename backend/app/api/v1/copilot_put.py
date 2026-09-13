"""Authenticated, no-write hypothetical cash-secured put endpoint."""

from copy import deepcopy
from dataclasses import asdict
from uuid import UUID

from fastapi import APIRouter, Depends, Request

from ...core.config import get_settings
from ...core.deps_auth import AuthedUser, require_user
from ...core.responses import APIError, ok
from ...schemas.copilot_put import CashSecuredPutRequest, CashSecuredPutResult
from ...schemas.envelope import Envelope
from ...schemas.put_plan import ConfirmPutPlan, PutPlanReview, ReviewPutPlanRequest, SavedPutPlan
from ...services import comparison_save, copilot_put, copilot_scope, put_plans
from . import risk

router = APIRouter(prefix="/api/v1/copilot", tags=["copilot"])


@router.post("/cash-secured-put", response_model=Envelope[CashSecuredPutResult])
def scenario(
    body: CashSecuredPutRequest, request: Request, user: AuthedUser = Depends(require_user)
):
    settings = get_settings()
    if not settings.decision_support_enabled or not settings.cash_secured_put_enabled:
        raise APIError(503, "put_scenario_disabled", "Cash-secured put scenarios are not enabled.")
    revision = None
    if settings.cash_secured_put_save_enabled:
        put_plans.require_enabled()
        revision = comparison_save.portfolio_revision(
            user.access_token, user.id, str(body.expected_portfolio_id)
        )
    context = deepcopy(risk._resolve_active_context_or_raise(user))
    digest = copilot_scope.context_digest(asdict(context))
    result = copilot_put.calculate(context, body, digest)
    copilot_scope.verify_scope(user.access_token, str(body.expected_portfolio_id), digest)
    if revision is not None:
        result.receipt = put_plans.issue(user.id, context, revision, result)
    return ok(result.model_dump(mode="json"), request=request)


@router.post("/put-plans/{result_id}/confirm", response_model=Envelope[SavedPutPlan])
def confirm_plan(
    result_id: UUID,
    body: ConfirmPutPlan,
    request: Request,
    user: AuthedUser = Depends(require_user),
):
    if not body.confirmed:
        raise APIError(422, "confirmation_required", "Confirm saving this original calculation.")
    result = put_plans.confirm(
        user.access_token, user.id, str(body.expected_portfolio_id), str(result_id), body.receipt
    )
    return ok(result.model_dump(mode="json"), request=request)


@router.get("/put-plans", response_model=Envelope[list[SavedPutPlan]])
def list_plans(
    expected_portfolio_id: UUID, request: Request, user: AuthedUser = Depends(require_user)
):
    return ok(
        [
            plan.model_dump(mode="json")
            for plan in put_plans.list_saved(user.access_token, user.id, str(expected_portfolio_id))
        ],
        request=request,
    )


@router.post("/put-plans/{plan_id}/review", response_model=Envelope[PutPlanReview])
def review_plan(
    plan_id: UUID,
    body: ReviewPutPlanRequest,
    request: Request,
    user: AuthedUser = Depends(require_user),
):
    expected = str(body.expected_portfolio_id)
    saved, snapshot, _ = put_plans.get_saved(user.access_token, user.id, expected, str(plan_id))
    revision = comparison_save.portfolio_revision(user.access_token, user.id, expected)
    context = deepcopy(risk._resolve_active_context_or_raise(user))
    digest = copilot_scope.context_digest(asdict(context))
    result = put_plans.review(saved, snapshot, context, revision)
    copilot_scope.verify_scope(user.access_token, expected, digest)
    if comparison_save.portfolio_revision(user.access_token, user.id, expected) != revision:
        raise APIError(409, "portfolio_changed", "The account changed during review.")
    return ok(result.model_dump(mode="json"), request=request)
