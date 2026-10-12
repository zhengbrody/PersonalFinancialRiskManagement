"""Authenticated same-snapshot hypothetical funding alternatives."""

from copy import deepcopy
from dataclasses import asdict

from fastapi import APIRouter, Depends, Request

from ...core.config import get_settings
from ...core.deps_auth import AuthedUser, require_user
from ...core.responses import APIError, ok
from ...schemas.envelope import Envelope
from ...schemas.funding_scenarios import FundingScenarioRequest, FundingScenarioResult
from ...services import (
    comparison_replay,
    comparison_save,
    copilot_scope,
    funding_plans,
    funding_scenarios,
)
from . import risk

router = APIRouter(prefix="/api/v1/copilot", tags=["copilot"])


@router.post("/funding-scenarios", response_model=Envelope[FundingScenarioResult])
def calculate(
    body: FundingScenarioRequest, request: Request, user: AuthedUser = Depends(require_user)
):
    settings = get_settings()
    if not (
        settings.decision_support_enabled
        and settings.cash_secured_put_enabled
        and settings.funding_scenarios_enabled
    ):
        raise APIError(
            503, "funding_scenarios_disabled", "Combined funding scenarios are not enabled."
        )
    save = getattr(settings, "funding_scenarios_save_enabled", False)
    if save:
        # Cheap gate before the analysis lane: a save-enabled deployment with no
        # signing secret must not compute and then refuse to issue the receipt.
        funding_plans.require_enabled()
    expected = str(body.expected_portfolio_id)
    snapshot = comparison_replay.read_receipt(
        body.receipt, user.id, expected, str(body.source_result_id)
    )
    revision = comparison_save.portfolio_revision(user.access_token, user.id, expected)
    context = deepcopy(risk._resolve_active_context_or_raise(user))
    digest = copilot_scope.context_digest(asdict(context))
    if snapshot.portfolio_revision != revision or not comparison_replay.current_inputs_match(
        snapshot, context
    ):
        raise APIError(
            409, "portfolio_changed", "Capture a fresh comparison for the current account."
        )
    if not risk._check_capacity.acquire(blocking=False):
        raise APIError(
            429, "analysis_busy", "Another risk analysis is running. Please try again shortly."
        )
    try:
        result = funding_scenarios.calculate(snapshot, body, now=comparison_replay.utcnow())
    finally:
        risk._check_capacity.release()
    copilot_scope.verify_scope(user.access_token, expected, digest)
    if comparison_save.portfolio_revision(user.access_token, user.id, expected) != revision:
        raise APIError(409, "portfolio_changed", "The account changed during calculation.")
    if save:
        result.receipt = funding_plans.issue(user.id, snapshot, body, result)
    return ok(result.model_dump(mode="json"), request=request)
