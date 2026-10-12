"""Authenticated background candidate runs; reuse copilot_runs and signed saves."""

from dataclasses import asdict
from uuid import UUID

from fastapi import APIRouter, Depends, Request

from ...core.deps_auth import AuthedUser, require_user
from ...core.responses import APIError, ok
from ...schemas.copilot_jobs import (
    CandidateRunList,
    CandidateRunOut,
    RecoverCandidateRuns,
    StartCandidateRun,
)
from ...schemas.copilot_runs import RunSnapshot
from ...schemas.envelope import Envelope
from ...services import comparison_save, risk_profile
from ...services import copilot_jobs as jobs
from . import risk

router = APIRouter(prefix="/api/v1/copilot/decision-runs", tags=["copilot"])


def _dispatcher(request):
    return request.app.state.copilot_dispatcher


@router.get("", response_model=Envelope[CandidateRunList])
def recent(expected_portfolio_id: UUID, request: Request, user: AuthedUser = Depends(require_user)):
    records, untrusted = jobs.journal(user).recent(str(expected_portfolio_id))
    return ok(
        CandidateRunList(
            runs=[r.public() for r in records], untrusted_records=untrusted
        ).model_dump(mode="json"),
        request=request,
    )


@router.post("/recover", response_model=Envelope[CandidateRunList])
def recover(body: RecoverCandidateRuns, request: Request, user: AuthedUser = Depends(require_user)):
    jobs.require_enabled()
    context = risk._resolve_active_context_or_raise(user)
    expected = str(body.expected_portfolio_id)
    if context.portfolio_id != expected:
        raise APIError(409, "portfolio_changed", "Select the requested portfolio before recovery.")
    log = jobs.journal(user)
    removed = log.store.cleanup(expected)
    dispatched, _ = _dispatcher(request).recover(user, expected)
    records, untrusted = log.recent(expected)
    return ok(
        CandidateRunList(
            runs=[r.public() for r in records],
            untrusted_records=untrusted,
            dispatched=dispatched,
            removed=removed,
        ).model_dump(mode="json"),
        request=request,
    )


@router.post("", response_model=Envelope[CandidateRunOut])
def start(body: StartCandidateRun, request: Request, user: AuthedUser = Depends(require_user)):
    jobs.require_enabled()
    if not body.task.confirmed:
        raise APIError(
            422, "constraints_unconfirmed", "Confirm your constraints before calculating."
        )
    if body.task_state is not None:
        _bind_confirmed_task(body, user)
    log = jobs.journal(user)
    id = str(body.id)
    try:
        record = log.get(id)
    except APIError as exc:
        if exc.status != 404:
            raise
        context = risk._resolve_active_context_or_raise(user)
        if context.portfolio_id != str(body.task.expected_portfolio_id):
            raise APIError(409, "portfolio_changed", "Select the requested portfolio.")
        # Cheap refusals before anything is written: one active job per owner,
        # and no reservation the dispatcher could not start right now.
        # Exclude this id: a concurrent duplicate of the SAME request (another
        # instance may have reserved it after our lookup) is idempotent, not a
        # second active job.
        if log.active_count(exclude=id) >= jobs.MAX_ACTIVE_PER_USER:
            raise jobs.too_many_active()
        if not _dispatcher(request).has_capacity(user):
            raise jobs.queue_full(saved=False)
        profile = risk_profile.resolve_risk_preference(user)
        revision = comparison_save.portfolio_revision(
            user.access_token, user.id, context.portfolio_id
        )
        snapshot = RunSnapshot(
            **asdict(context),
            risk_preference=profile.value,
            preference_source=profile.source,
            preference_confirmed_at=profile.confirmed_at,
        )
        record = log.reserve(id, body.task, snapshot, revision)
    if record.task != body.task:
        raise APIError(409, "run_conflict", "This run ID belongs to different constraints.")
    if record.state == "queued" and not _dispatcher(request).submit(user, id):
        # Truthful: the record is durably queued but nothing will run it until a
        # retry of this same id (idempotent) or an explicit recovery.
        raise jobs.queue_full(saved=True)
    return ok(record.public().model_dump(mode="json"), request=request)


def _bind_confirmed_task(body, user):
    from ...schemas.copilot_task_state import TaskStateToken
    from ...services import copilot_runs
    from ...services import copilot_task_state as tasks

    record = tasks.verify(TaskStateToken.model_validate(body.task_state.model_dump()), user.id)
    confirmed = record.confirmed
    if (
        confirmed is None
        or confirmed.stale
        or record.status == "closed"
        or tasks.is_expired(record, copilot_runs.utcnow())
        or str(record.portfolio_id) != str(body.task.expected_portfolio_id)
        or confirmed.run_id != body.id
        or confirmed.goal != body.task.goal
        or confirmed.amount != body.task.amount
        or sorted(confirmed.protected_holdings) != sorted(body.task.protected_holdings)
    ):
        raise APIError(
            409,
            "task_state_mismatch",
            "This calculation does not match the confirmed version of the task.",
        )


@router.get("/{id}", response_model=Envelope[CandidateRunOut])
def read(id: UUID, request: Request, user: AuthedUser = Depends(require_user)):
    # Stored results stay readable on rollback; key + user auth are still required.
    record = jobs.journal(user).get(str(id))
    return ok(record.public().model_dump(mode="json"), request=request)


@router.post("/{id}/resume", response_model=Envelope[CandidateRunOut])
def resume(id: UUID, request: Request, user: AuthedUser = Depends(require_user)):
    jobs.require_enabled()
    record = jobs.journal(user).resume(str(id))
    if record.state == "queued" and not _dispatcher(request).submit(user, str(id)):
        raise jobs.queue_full(saved=True)
    return ok(record.public().model_dump(mode="json"), request=request)


@router.post("/{id}/cancel", response_model=Envelope[CandidateRunOut])
def cancel(id: UUID, request: Request, user: AuthedUser = Depends(require_user)):
    record = jobs.journal(user).cancel(str(id))
    return ok(record.public().model_dump(mode="json"), request=request)
