"""Authenticated, no-write hypothetical cash-secured put endpoint."""

from copy import deepcopy
from dataclasses import asdict

from fastapi import APIRouter, Depends, Request

from ...core.config import get_settings
from ...core.deps_auth import AuthedUser, require_user
from ...core.responses import APIError, ok
from ...schemas.copilot_put import CashSecuredPutRequest, CashSecuredPutResult
from ...schemas.envelope import Envelope
from ...services import copilot_put, copilot_scope
from . import risk

router = APIRouter(prefix="/api/v1/copilot", tags=["copilot"])


@router.post("/cash-secured-put", response_model=Envelope[CashSecuredPutResult])
def scenario(
    body: CashSecuredPutRequest, request: Request, user: AuthedUser = Depends(require_user)
):
    settings = get_settings()
    if not settings.decision_support_enabled or not settings.cash_secured_put_enabled:
        raise APIError(503, "put_scenario_disabled", "Cash-secured put scenarios are not enabled.")
    context = deepcopy(risk._resolve_active_context_or_raise(user))
    digest = copilot_scope.context_digest(asdict(context))
    result = copilot_put.calculate(context, body, digest)
    copilot_scope.verify_scope(user.access_token, str(body.expected_portfolio_id), digest)
    return ok(result.model_dump(mode="json"), request=request)
