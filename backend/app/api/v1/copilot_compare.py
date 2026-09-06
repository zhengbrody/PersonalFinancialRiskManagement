"""Explicit foreground comparison, bound to the authenticated active book."""

from copy import deepcopy
from dataclasses import asdict

from fastapi import APIRouter, Depends, Request

from ...core.deps_auth import AuthedUser, require_user
from ...core.responses import APIError, ok
from ...schemas.copilot_compare import ChangeComparison, CompareChange
from ...schemas.envelope import Envelope
from ...services import copilot_compare, copilot_scope, market_data
from . import risk

router = APIRouter(prefix="/api/v1/copilot", tags=["copilot"])


@router.post("/compare-change", response_model=Envelope[ChangeComparison])
def compare_change(body: CompareChange, request: Request, user: AuthedUser = Depends(require_user)):
    if not risk._check_capacity.acquire(blocking=False):
        raise APIError(
            429, "analysis_busy", "Another risk analysis is running. Please try again shortly."
        )
    try:
        context = deepcopy(risk._resolve_active_context_or_raise(user))
        expected = str(body.expected_portfolio_id)
        if context.portfolio_id != expected:
            raise APIError(
                409, "portfolio_changed", "Select the original portfolio before comparing."
            )
        digest = copilot_scope.context_digest(asdict(context))
        symbols = copilot_compare.validate_holdings(context, body)
        sources = {}
        prices = market_data.get_price_history(sorted(symbols), days=365, provenance=sources)
        result = copilot_compare.compare_change(context, body, prices, sources.get("by_ticker", {}))
        copilot_scope.verify_scope(user.access_token, expected, digest)
        return ok(result.model_dump(mode="json"), request=request)
    finally:
        risk._check_capacity.release()
