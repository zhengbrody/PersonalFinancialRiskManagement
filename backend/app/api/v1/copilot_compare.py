"""Explicit foreground comparison, bound to the authenticated active book."""

from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, Request

from ...core.config import get_settings
from ...core.deps_auth import AuthedUser, require_user
from ...core.responses import APIError, ok
from ...schemas.copilot_compare import (
    ChangeComparison,
    CompareChange,
    ComparisonVerification,
    ConfirmComparison,
    ReplayComparison,
    SavedComparison,
)
from ...schemas.envelope import Envelope
from ...services import (
    comparison_options,
    comparison_replay,
    comparison_save,
    copilot_compare,
    copilot_scope,
    market_data,
)
from . import risk

router = APIRouter(prefix="/api/v1/copilot", tags=["copilot"])


@router.post("/compare-change", response_model=Envelope[ChangeComparison])
def compare_change(body: CompareChange, request: Request, user: AuthedUser = Depends(require_user)):
    if not risk._check_capacity.acquire(blocking=False):
        raise APIError(
            429, "analysis_busy", "Another risk analysis is running. Please try again shortly."
        )
    try:
        expected = str(body.expected_portfolio_id)
        revision = None
        if get_settings().copilot_comparison_save_enabled:
            comparison_save.require_enabled()
            revision = comparison_save.portfolio_revision(user.access_token, user.id, expected)
        context = deepcopy(risk._resolve_active_context_or_raise(user))
        if context.portfolio_id != expected:
            raise APIError(
                409, "portfolio_changed", "Select the original portfolio before comparing."
            )
        digest = copilot_scope.context_digest(asdict(context))
        now = datetime.now(timezone.utc)
        symbols = copilot_compare.validate_holdings(context, body, now=now)
        specs = comparison_options.option_specs(context.holdings, now=now)
        fetch_symbols = sorted(set(symbols) | {s.underlying for s in specs})
        sources = {}
        prices = market_data.get_price_history(fetch_symbols, days=365, provenance=sources)
        frame, _ = copilot_compare.prepare_prices(prices, fetch_symbols, now=now)
        option_results = comparison_options.capture_options(
            specs, frame.iloc[-1].to_dict(), now=now
        )
        result = copilot_compare.compare_change(
            context,
            body,
            frame,
            sources.get("by_ticker", {}),
            now=now,
            option_results=option_results,
        )
        copilot_scope.verify_scope(user.access_token, expected, digest)
        if get_settings().copilot_comparison_replay_enabled:
            receipt = comparison_replay.issue_receipt(
                user.id,
                context,
                frame,
                option_results,
                sources.get("by_ticker", {}),
                result,
                portfolio_revision=revision,
            )
            result = result.model_copy(update={"replay_receipt": receipt})
        return ok(result.model_dump(mode="json"), request=request)
    finally:
        risk._check_capacity.release()


@router.post("/compare-change/{result_id}/confirm", response_model=Envelope[SavedComparison])
def confirm_comparison(
    result_id: UUID,
    body: ConfirmComparison,
    request: Request,
    user: AuthedUser = Depends(require_user),
):
    if not body.confirmed:
        raise APIError(
            422, "confirmation_required", "Explicit confirmation is required to save a draft plan."
        )
    if not risk._check_capacity.acquire(blocking=False):
        raise APIError(
            429, "analysis_busy", "Another risk analysis is running. Please try again shortly."
        )
    try:
        saved = comparison_save.confirm(
            user.access_token,
            user.id,
            str(body.expected_portfolio_id),
            str(result_id),
            body.receipt,
        )
        return ok(saved.model_dump(mode="json"), request=request)
    finally:
        risk._check_capacity.release()


@router.get("/compare-change/{result_id}/saved", response_model=Envelope[SavedComparison])
def saved_comparison(
    result_id: UUID,
    expected_portfolio_id: UUID,
    request: Request,
    user: AuthedUser = Depends(require_user),
):
    saved = comparison_save.get_saved(
        user.access_token, user.id, str(expected_portfolio_id), str(result_id)
    )
    return ok(saved.model_dump(mode="json"), request=request)


@router.post("/compare-change/{result_id}/verify", response_model=Envelope[ComparisonVerification])
def verify_comparison(
    result_id: UUID,
    body: ReplayComparison,
    request: Request,
    user: AuthedUser = Depends(require_user),
):
    if not risk._check_capacity.acquire(blocking=False):
        raise APIError(
            429, "analysis_busy", "Another risk analysis is running. Please try again shortly."
        )
    try:
        snapshot = comparison_replay.read_receipt(
            body.receipt, user.id, str(body.expected_portfolio_id), str(result_id)
        )
        context = deepcopy(risk._resolve_active_context_or_raise(user))
        if context.portfolio_id != str(body.expected_portfolio_id):
            raise APIError(
                409, "portfolio_changed", "Select the original portfolio before verifying."
            )
        result = comparison_replay.replay(snapshot)
        # Recheck active identity/inputs across the pure replay operation too.
        copilot_scope.verify_scope(
            user.access_token, context.portfolio_id, copilot_scope.context_digest(asdict(context))
        )
        now = comparison_replay.utcnow()
        age = int((now - snapshot.captured_at).total_seconds())
        if age < 0:
            raise APIError(
                409,
                "comparison_clock_mismatch",
                "Snapshot time is ahead of the server clock. Run a fresh comparison.",
            )
        payload = ComparisonVerification(
            result=result,
            verified_at=now,
            inputs_match_now=comparison_replay.current_inputs_match(snapshot, context),
            snapshot_age_seconds=age,
            recent_capture=age <= 900,
        )
        return ok(payload.model_dump(mode="json"), request=request)
    finally:
        risk._check_capacity.release()
