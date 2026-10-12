"""Explicit confirmation and authenticated resumption of an open decision task.

Both endpoints require the CURRENT user JWT (no stored credential) and use only
caller-scoped storage (RLS). Account data is never taken from the request:
confirmation checks the active portfolio, resumption re-reads the run record
and compares its captured portfolio revision with the current one.
"""

from fastapi import APIRouter, Depends, Request

from ...core.config import get_settings
from ...core.deps_auth import AuthedUser, require_user
from ...core.responses import APIError, ok
from ...schemas.copilot_task_state import (
    ConfirmTaskParameters,
    ResumeTask,
    TaskResumeOut,
    TaskStateEnvelope,
)
from ...schemas.envelope import Envelope
from ...services import comparison_save, copilot_runs
from ...services import copilot_jobs as jobs
from ...services import copilot_task_state as tasks
from . import risk

router = APIRouter(prefix="/api/v1/copilot/task-state", tags=["copilot"])


def _require_enabled():
    if not get_settings().decision_support_enabled:
        raise APIError(503, "task_state_unavailable", "Decision tasks are not enabled.")


def _verified(token, user, expected):
    record = tasks.verify(token, user.id)
    if str(record.portfolio_id) != str(expected):
        raise APIError(409, "portfolio_changed", "This task belongs to a different portfolio.")
    context = risk._resolve_active_context_or_raise(user)
    if context.portfolio_id != str(expected):
        raise APIError(409, "portfolio_changed", "Select this task's portfolio to continue.")
    return record


@router.post("/confirm", response_model=Envelope[TaskStateEnvelope])
def confirm(
    body: ConfirmTaskParameters, request: Request, user: AuthedUser = Depends(require_user)
):
    """The ONLY way a parameter becomes confirmed: an explicit typed submission."""
    _require_enabled()
    if body.confirmed is not True:
        raise APIError(422, "constraints_unconfirmed", "Confirm your constraints first.")
    record = _verified(body.task_state, user, body.expected_portfolio_id)
    now = copilot_runs.utcnow()
    if tasks.is_expired(record, now) or record.status == "closed":
        raise APIError(410, "task_expired", "This task expired. Ask again to start a new one.")
    updated = tasks.confirm(
        record,
        goal=body.goal,
        amount=body.amount,
        protected_holdings=body.protected_holdings,
        run_id=body.run_id,
        now=now,
    )
    outcome = "continued" if updated is not record else "unrelated"
    return ok(tasks.envelope(updated, outcome).model_dump(mode="json"), request=request)


@router.post("/resume", response_model=Envelope[TaskResumeOut])
def resume(body: ResumeTask, request: Request, user: AuthedUser = Depends(require_user)):
    """Re-authenticate, re-bind and either continue from the durable confirmed
    run or report that the account changed (old result stale)."""
    _require_enabled()
    record = _verified(body.task_state, user, body.expected_portfolio_id)
    now = copilot_runs.utcnow()

    def out(outcome, rec, run=None, dispatched=False):
        payload = TaskResumeOut(
            outcome=outcome,
            state=rec.view(),
            token=tasks.issue(rec),
            run=run.public() if run is not None else None,
            dispatched=dispatched,
        )
        return ok(payload.model_dump(mode="json"), request=request)

    if record.status == "closed":
        return out("closed", record)
    if tasks.is_expired(record, now):
        return out("expired", tasks.close(record, now))
    confirmed = record.confirmed
    if confirmed is None:
        return out(record.status, record)
    if confirmed.stale:
        return out("stale_account_changed", record)

    log = jobs.journal(user)
    if log.newer_task_version(record.portfolio_id, record.task_id, confirmed.version):
        # Another tab confirmed (and started) a newer version: this token's run
        # is superseded and is neither presented nor re-dispatched.
        return out("superseded", record)
    try:
        run = log.get(str(confirmed.run_id))
    except APIError as exc:
        if exc.status in (404, 410):
            return out("run_missing", record)
        raise
    task = run.task
    if (
        str(run.portfolio_id) != str(record.portfolio_id)
        or task.goal != confirmed.goal
        or task.amount != confirmed.amount
        or sorted(task.protected_holdings) != sorted(confirmed.protected_holdings)
    ):
        raise APIError(409, "run_conflict", "The stored run does not match the confirmed task.")
    revision = comparison_save.portfolio_revision(
        user.access_token, user.id, str(record.portfolio_id)
    )
    if revision != run.portfolio_revision:
        # Account changed since capture: never present or continue the old run.
        return out("stale_account_changed", tasks.mark_stale(record, now), run)
    if run.state == "completed":
        return out("completed", record, run)
    if run.state in ("failed", "cancelled"):
        return out("run_failed", record, run)
    dispatched = False
    if run.state in ("queued", "interrupted"):
        jobs.require_enabled()
        run = log.resume(str(confirmed.run_id))
        if run.state == "queued":
            dispatched = request.app.state.copilot_dispatcher.submit(user, str(confirmed.run_id))
            if not dispatched:
                raise jobs.queue_full(saved=True)
    return out("continuing", record, run, dispatched)
