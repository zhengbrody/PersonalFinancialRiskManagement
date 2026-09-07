"""Foreground checks with recoverable, server-authenticated results."""

import logging
import time
from dataclasses import asdict
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import ValidationError

from ...core.deps_auth import AuthedUser, require_user
from ...core.responses import APIError, ok
from ...schemas.copilot_runs import RunOut, RunSnapshot, StartRun
from ...schemas.envelope import Envelope
from ...schemas.risk import ReportFromActiveRequest
from ...services import copilot_runs as runs
from ...services import risk_profile
from . import risk

router = APIRouter(prefix="/api/v1/copilot/runs", tags=["copilot"])
_log = logging.getLogger(__name__)


def _journal(user: AuthedUser) -> runs.RunJournal:
    key = runs.signing_key()  # Fail before any storage IO if not provisioned.
    return runs.RunJournal(runs.RunStore(user.access_token, user.id), key, user.id)


def _same_portfolio(record, portfolio_id: UUID):
    if record.portfolio_id != portfolio_id:
        raise APIError(409, "run_conflict", "This run ID belongs to a different portfolio.")


@router.post("", response_model=Envelope[RunOut])
def start_run(body: StartRun, request: Request, user: AuthedUser = Depends(require_user)):
    started = time.perf_counter()
    journal = _journal(user)
    run_id = str(body.id)
    try:
        existing = journal.get(run_id)
    except APIError as exc:
        if exc.status != 404:
            raise
    else:
        _same_portfolio(existing, body.expected_portfolio_id)
        return ok(existing.public().model_dump(mode="json"), request=request, started_at=started)

    # Same bounded lane as the direct foreground check, never an unbounded queue.
    if not risk._check_capacity.acquire(blocking=False):
        raise APIError(
            429, "analysis_busy", "A risk check is already running. Please try again shortly."
        )
    try:
        context = risk._resolve_active_context_or_raise(user)
        if context.portfolio_id != str(body.expected_portfolio_id):
            raise APIError(
                409,
                "portfolio_changed",
                "The active portfolio changed. Start a new check for the selected portfolio.",
            )
        profile = risk_profile.resolve_risk_preference(user)
        parameters = ReportFromActiveRequest()
        try:
            snapshot = RunSnapshot(
                **asdict(context),
                risk_preference=profile.value,
                preference_source=profile.source,
                preference_confirmed_at=profile.confirmed_at,
                history_days=parameters.history_days,
                risk_free_rate=parameters.risk_free_rate,
                market_shock=parameters.market_shock,
            )
        except ValidationError:
            raise APIError(
                422,
                "invalid_run_inputs",
                "Portfolio inputs could not be validated for a saved check.",
            ) from None
        record, inserted = journal.reserve(run_id, snapshot)
        if inserted:
            # Reconstruct from the signed input copy, not mutable live holdings.
            from libs.auth.active_portfolio import ActivePortfolioContext

            frozen = record.snapshot
            captured_context = ActivePortfolioContext(
                portfolio_id=str(frozen.portfolio_id),
                holdings=frozen.model_dump()["holdings"],
                cash_balance=frozen.cash_balance,
                margin_loan=frozen.margin_loan,
                contributed_capital=frozen.contributed_capital,
            )
            captured_profile = risk_profile.ResolvedRiskPreference(
                frozen.risk_preference, frozen.preference_source, frozen.preference_confirmed_at
            )
            try:
                report = risk.compute_active_report(
                    ReportFromActiveRequest(
                        expected_portfolio_id=str(frozen.portfolio_id),
                        include_copilot_check=True,
                        history_days=frozen.history_days,
                        risk_free_rate=frozen.risk_free_rate,
                        market_shock=frozen.market_shock,
                    ),
                    user,
                    active_context=captured_context,
                    resolved_profile=captured_profile,
                )
            except Exception as exc:
                # Preserve the failed state without persisting provider responses,
                # exception text, prompts, tokens or user holdings in telemetry.
                _log.warning("copilot_runs.analysis_failed type=%s", type(exc).__name__)
                record = journal.finish(run_id, None)
            else:
                record = journal.finish(run_id, report.copilot_check)
        return ok(record.public().model_dump(mode="json"), request=request, started_at=started)
    finally:
        risk._check_capacity.release()


@router.get("/{run_id}", response_model=Envelope[RunOut])
def get_run(run_id: UUID, request: Request, user: AuthedUser = Depends(require_user)):
    record = _journal(user).get(str(run_id))
    return ok(record.public().model_dump(mode="json"), request=request)


@router.post("/{run_id}/cancel", response_model=Envelope[RunOut])
def cancel_run(run_id: UUID, request: Request, user: AuthedUser = Depends(require_user)):
    record = _journal(user).cancel(str(run_id))
    return ok(record.public().model_dump(mode="json"), request=request)
