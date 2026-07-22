"""``/api/v1/risk/plans/*`` + alert-state + journey endpoints (PR2).

All authed and RLS-scoped through the caller's JWT. A plan is a saved ANALYSIS,
never an order — nothing here writes to holdings or executes a trade. A missing
0012 table maps to 503 (the feature isn't provisioned yet), an RLS violation on
a non-owned portfolio maps to 422 (no existence leak), and content is never
logged.
"""

from __future__ import annotations

import logging
import time

from fastapi import APIRouter, Depends, Request

from ...core.deps_auth import AuthedUser, require_user
from ...core.responses import APIError, ok, server_error, service_unavailable
from ...schemas.envelope import Envelope
from ...schemas.risk_ops import (
    AlertStateList,
    AlertStateOut,
    AlertStateUpsert,
    JourneyOut,
    JourneyRecordRequest,
)
from ...schemas.risk_plans import (
    RiskPlanCreate,
    RiskPlanList,
    RiskPlanOut,
    RiskPlanPatch,
    RiskPlanReviewOut,
    RiskPlanReviewRequest,
)

router = APIRouter(prefix="/api/v1", tags=["risk-ops"])
_log = logging.getLogger(__name__)


def _rls_violation(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "row-level security" in msg or "42501" in msg or "violates row-level" in msg


# ── risk plans ─────────────────────────────────────────────────────


@router.get(
    "/risk/plans",
    summary="List the caller's saved risk plans (optionally for one portfolio)",
    response_model=Envelope[RiskPlanList],
)
def list_plans_endpoint(
    request: Request,
    portfolio_id: str | None = None,
    user: AuthedUser = Depends(require_user),
):
    started = time.perf_counter()
    from ...services import risk_plans

    try:
        rows = risk_plans.list_plans(user.access_token, user.id, portfolio_id)
    except Exception as exc:  # noqa: BLE001
        if risk_plans.table_missing(exc):
            raise service_unavailable("Risk plans are not provisioned yet.") from None
        _log.warning("risk_plans.list_failed err=%s", type(exc).__name__)
        raise service_unavailable("Risk plans are temporarily unavailable.") from None
    payload = RiskPlanList(plans=[RiskPlanOut(**r) for r in rows]).model_dump()
    return ok(payload, request=request, started_at=started)


@router.post(
    "/risk/plans",
    summary="Save a risk plan (an analysis, never an order)",
    response_model=Envelope[RiskPlanOut],
)
def create_plan_endpoint(
    body: RiskPlanCreate,
    request: Request,
    user: AuthedUser = Depends(require_user),
):
    started = time.perf_counter()
    from ...services import risk_plans, user_journey

    try:
        row = risk_plans.create_plan(user.access_token, user.id, body.model_dump())
    except Exception as exc:  # noqa: BLE001
        if risk_plans.table_missing(exc):
            raise service_unavailable("Risk plans are not provisioned yet.") from None
        if _rls_violation(exc):
            # portfolio_id isn't the caller's → RLS WITH CHECK rejected it.
            raise APIError(
                status=422, code="portfolio_not_found", message="Portfolio not found."
            ) from None
        _log.warning("risk_plans.create_failed err=%s", type(exc).__name__)
        raise server_error("Could not save the plan.", reason=type(exc).__name__) from exc
    # Journey: saving a plan IS the "first plan" product event (fail-soft).
    user_journey.stamp_milestone_failsoft(user.access_token, user.id, "first_plan_at")
    return ok(RiskPlanOut(**row).model_dump(), request=request, started_at=started)


@router.get(
    "/risk/plans/{plan_id}",
    summary="Fetch one of the caller's risk plans",
    response_model=Envelope[RiskPlanOut],
)
def get_plan_endpoint(
    plan_id: str,
    request: Request,
    user: AuthedUser = Depends(require_user),
):
    started = time.perf_counter()
    from ...services import risk_plans

    try:
        row = risk_plans.get_plan(user.access_token, user.id, plan_id)
    except Exception as exc:  # noqa: BLE001
        if risk_plans.table_missing(exc):
            raise service_unavailable("Risk plans are not provisioned yet.") from None
        raise server_error("Could not load the plan.", reason=type(exc).__name__) from exc
    if not row:
        raise APIError(status=404, code="plan_not_found", message="Plan not found.")
    return ok(RiskPlanOut(**row).model_dump(), request=request, started_at=started)


@router.patch(
    "/risk/plans/{plan_id}",
    summary="Update a risk plan (status / review / outcome / editable fields)",
    response_model=Envelope[RiskPlanOut],
)
def patch_plan_endpoint(
    plan_id: str,
    body: RiskPlanPatch,
    request: Request,
    user: AuthedUser = Depends(require_user),
):
    started = time.perf_counter()
    from ...services import risk_plans

    fields = body.model_dump(exclude_unset=True)
    if not fields:
        raise APIError(status=422, code="no_fields_to_update", message="Nothing to update.")
    # An explicit null on a NOT-NULL column would violate a DB constraint (500);
    # reject it as a client error instead. (outcome/review_at/hypothesis are
    # nullable, so a null there is a legitimate clear.)
    _not_nullable = {"title", "status", "proposed_changes", "expected_impact"}
    if any(k in fields and fields[k] is None for k in _not_nullable):
        raise APIError(
            status=422, code="invalid_field", message="title/status/plan fields cannot be null."
        )
    try:
        row = risk_plans.update_plan(user.access_token, user.id, plan_id, fields)
    except Exception as exc:  # noqa: BLE001
        if risk_plans.table_missing(exc):
            raise service_unavailable("Risk plans are not provisioned yet.") from None
        raise server_error("Could not update the plan.", reason=type(exc).__name__) from exc
    if not row:
        raise APIError(status=404, code="plan_not_found", message="Plan not found.")
    return ok(RiskPlanOut(**row).model_dump(), request=request, started_at=started)


@router.delete(
    "/risk/plans/{plan_id}",
    summary="Delete one of the caller's risk plans",
    response_model=Envelope[dict],
)
def delete_plan_endpoint(
    plan_id: str,
    request: Request,
    user: AuthedUser = Depends(require_user),
):
    started = time.perf_counter()
    from ...services import risk_plans

    try:
        risk_plans.delete_plan(user.access_token, user.id, plan_id)
    except Exception as exc:  # noqa: BLE001
        if risk_plans.table_missing(exc):
            raise service_unavailable("Risk plans are not provisioned yet.") from None
        raise server_error("Could not delete the plan.", reason=type(exc).__name__) from exc
    return ok({"deleted": True, "id": plan_id}, request=request, started_at=started)


@router.post(
    "/risk/plans/{plan_id}/review",
    summary="Compare a plan's baseline to current metrics (deterministic, no advice)",
    response_model=Envelope[RiskPlanReviewOut],
)
def review_plan_endpoint(
    plan_id: str,
    body: RiskPlanReviewRequest,
    request: Request,
    user: AuthedUser = Depends(require_user),
):
    started = time.perf_counter()
    from ...services import plan_review, risk_plans, user_journey

    try:
        plan = risk_plans.get_plan(user.access_token, user.id, plan_id)
    except Exception as exc:  # noqa: BLE001
        if risk_plans.table_missing(exc):
            raise service_unavailable("Risk plans are not provisioned yet.") from None
        raise server_error("Could not load the plan.", reason=type(exc).__name__) from exc
    if not plan:
        raise APIError(status=404, code="plan_not_found", message="Plan not found.")

    review = plan_review.build_review(
        plan.get("baseline") or {}, body.current, plan.get("expected_impact") or {}
    )
    # Bookkeeping only — a review is valid even if the stamp write fails.
    try:
        risk_plans.mark_reviewed(user.access_token, user.id, plan_id)
    except Exception as exc:  # noqa: BLE001
        _log.warning("risk_plans.mark_reviewed_failed err=%s", type(exc).__name__)
    # Journey: a completed review IS the "first plan reviewed" product event.
    user_journey.stamp_milestone_failsoft(user.access_token, user.id, "first_plan_reviewed_at")
    return ok(RiskPlanReviewOut(**review).model_dump(), request=request, started_at=started)


# ── alert lifecycle state ──────────────────────────────────────────


@router.get(
    "/risk/alert_states",
    summary="Alert lifecycle states for one portfolio",
    response_model=Envelope[AlertStateList],
)
def list_alert_states_endpoint(
    request: Request,
    portfolio_id: str,
    user: AuthedUser = Depends(require_user),
):
    started = time.perf_counter()
    from ...services import risk_alert_states

    try:
        rows = risk_alert_states.list_states(user.access_token, user.id, portfolio_id)
    except Exception as exc:  # noqa: BLE001
        if risk_alert_states.table_missing(exc):
            raise service_unavailable("Alert states are not provisioned yet.") from None
        raise server_error("Could not load alert states.", reason=type(exc).__name__) from exc
    payload = AlertStateList(states=[AlertStateOut(**r) for r in rows]).model_dump()
    return ok(payload, request=request, started_at=started)


@router.put(
    "/risk/alert_states",
    summary="Set the lifecycle state (seen / snoozed / resolved) for one alert",
    response_model=Envelope[AlertStateOut],
)
def upsert_alert_state_endpoint(
    body: AlertStateUpsert,
    request: Request,
    user: AuthedUser = Depends(require_user),
):
    started = time.perf_counter()
    from ...services import risk_alert_states

    try:
        row = risk_alert_states.upsert_state(user.access_token, user.id, body.model_dump())
    except Exception as exc:  # noqa: BLE001
        if risk_alert_states.table_missing(exc):
            raise service_unavailable("Alert states are not provisioned yet.") from None
        if _rls_violation(exc):
            raise APIError(
                status=422, code="portfolio_not_found", message="Portfolio not found."
            ) from None
        raise server_error("Could not update the alert.", reason=type(exc).__name__) from exc
    return ok(AlertStateOut(**row).model_dump(), request=request, started_at=started)


# ── journey milestones ─────────────────────────────────────────────


@router.get(
    "/journey",
    summary="The caller's journey milestones (timestamps only)",
    response_model=Envelope[JourneyOut],
)
def get_journey_endpoint(request: Request, user: AuthedUser = Depends(require_user)):
    started = time.perf_counter()
    from ...services import user_journey

    try:
        row = user_journey.get_state(user.access_token, user.id)
    except Exception as exc:  # noqa: BLE001
        if user_journey.table_missing(exc):
            raise service_unavailable("Journey is not provisioned yet.") from None
        raise server_error("Could not load journey.", reason=type(exc).__name__) from exc
    return ok(JourneyOut(**row).model_dump(), request=request, started_at=started)


@router.post(
    "/journey/record",
    summary="Record an explicit stress-test completion or workspace visit",
    response_model=Envelope[JourneyOut],
)
def record_journey_endpoint(
    body: JourneyRecordRequest,
    request: Request,
    user: AuthedUser = Depends(require_user),
):
    started = time.perf_counter()
    from ...services import user_journey

    try:
        row = user_journey.record_milestone(user.access_token, user.id, body.milestone)
    except Exception as exc:  # noqa: BLE001
        if user_journey.table_missing(exc):
            raise service_unavailable("Journey is not provisioned yet.") from None
        raise server_error("Could not record milestone.", reason=type(exc).__name__) from exc
    return ok(JourneyOut(**row).model_dump(), request=request, started_at=started)
