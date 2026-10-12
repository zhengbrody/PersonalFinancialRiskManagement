"""Cross-device saved-plan history and read-only versioned metric review."""

from copy import deepcopy
from dataclasses import asdict
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request

from ...core.deps_auth import AuthedUser, require_user
from ...core.responses import APIError, ok
from ...schemas.envelope import Envelope
from ...schemas.saved_plans import (
    MetricReviewRequest,
    PlanMetricReview,
    SavedPlanDetail,
    SavedPlanPage,
)
from ...services import (
    comparison_replay,
    comparison_save,
    copilot_scope,
    market_data,
    plan_metric_review,
    saved_plan_history,
)
from . import risk

router = APIRouter(prefix="/api/v1/copilot/saved-plans", tags=["copilot"])


@router.get("", response_model=Envelope[SavedPlanPage])
def history(
    expected_portfolio_id: UUID,
    request: Request,
    cursor: str | None = Query(default=None, max_length=101),
    user: AuthedUser = Depends(require_user),
):
    page = saved_plan_history.page(user.access_token, user.id, str(expected_portfolio_id), cursor)
    return ok(page.model_dump(mode="json"), request=request)


@router.get("/{plan_id}", response_model=Envelope[SavedPlanDetail])
def detail(
    plan_id: UUID,
    expected_portfolio_id: UUID,
    request: Request,
    user: AuthedUser = Depends(require_user),
):
    value = saved_plan_history.detail(
        user.access_token, user.id, str(expected_portfolio_id), str(plan_id)
    )
    return ok(value.model_dump(mode="json"), request=request)


@router.post("/{plan_id}/metric-review", response_model=Envelope[PlanMetricReview])
def metric_review(
    plan_id: UUID,
    body: MetricReviewRequest,
    request: Request,
    user: AuthedUser = Depends(require_user),
):
    expected = str(body.expected_portfolio_id)
    # Authenticate the stored evidence BEFORE the single analysis lane.
    row = saved_plan_history.fetch_row(user.access_token, user.id, expected, str(plan_id))
    saved = saved_plan_history.verified(row, user.id, expected)
    now = comparison_replay.utcnow()
    try:
        snapshot = plan_metric_review.source_snapshot(saved, row, user.id, expected)
    except plan_metric_review.NotComputable as exc:
        result = plan_metric_review.not_computable(saved, exc.reason, now)
        return ok(result.model_dump(mode="json"), request=request)
    if not risk._check_capacity.acquire(blocking=False):
        raise APIError(
            429, "analysis_busy", "Another risk analysis is running. Please try again shortly."
        )
    try:
        revision = comparison_save.portfolio_revision(user.access_token, user.id, expected)
        context = deepcopy(risk._resolve_active_context_or_raise(user))
        if context.portfolio_id != expected:
            raise APIError(409, "portfolio_changed", "Select the plan's original portfolio.")
        digest = copilot_scope.context_digest(asdict(context))
        result = plan_metric_review.review(
            saved, snapshot, context, revision, fetch=market_data.get_price_history, now=now
        )
        copilot_scope.verify_scope(user.access_token, expected, digest)
        if comparison_save.portfolio_revision(user.access_token, user.id, expected) != revision:
            raise APIError(409, "portfolio_changed", "The account changed during review.")
    finally:
        risk._check_capacity.release()
    return ok(result.model_dump(mode="json"), request=request)
