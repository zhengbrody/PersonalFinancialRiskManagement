"""Bounded background candidate execution using the original run store and HMAC.

One daemon worker per process; at most four dispatches (including active). JWTs
are transient memory only, released on completion. Recovery requires an explicit
resume request with a freshly verified JWT. Nothing publishes after the lease
expires; Python/provider code itself is not preemptible. No automatic trades.
"""

from copy import deepcopy
from dataclasses import asdict
from datetime import timedelta
from queue import Full, Queue
from threading import Lock, Thread
from uuid import UUID

from ..core.config import get_settings
from ..core.responses import APIError
from ..schemas.copilot_jobs import CandidateRunRecord
from . import copilot_runs as runs

RETENTION = timedelta(days=1)
LEASE = timedelta(seconds=120)


def key():
    secret = get_settings().risk_run_signing_secret.encode()
    if len(secret) < 32:
        raise APIError(503, "jobs_unavailable", "Background analysis signing is not configured.")
    return secret


def require_enabled():
    if not get_settings().async_analysis_enabled or not get_settings().decision_support_enabled:
        raise APIError(503, "jobs_unavailable", "Background candidate analysis is not enabled.")
    key()


class JobStore(runs.RunStore):
    def transition(self, old, new):
        return bool(
            self._execute(
                lambda: self.client.rpc(
                    "transition_copilot_job",
                    {
                        "p_id": old["id"],
                        "p_old_signature": old["signature"],
                        "p_record": new["record"],
                        "p_signature": new["signature"],
                        "p_state": new["state"],
                    },
                )
            )
        )


class JobJournal:
    def __init__(self, store, signing_key, user_id, clock=runs.utcnow):
        self.store, self.key, self.user_id, self.clock = store, signing_key, user_id, clock

    def read(self, id):
        row = self.store.get(id)
        if row is None:
            raise APIError(404, "run_not_found", "Analysis not found.")
        record = runs.decode(row, self.key, self.user_id, id, record_type=CandidateRunRecord)
        if record.expires_at <= self.clock():
            raise APIError(410, "run_expired", "This analysis is past its retention period.")
        return row, record

    def change(self, row, record, **changes):
        updated = CandidateRunRecord.model_validate(
            {
                **record.model_dump(),
                **changes,
                "revision": record.revision + 1,
                "updated_at": self.clock(),
            }
        )
        if self.store.transition(row, runs.encode(updated, self.key)):
            return updated
        return self.read(str(record.id))[1]

    def get(self, id):
        row, record = self.read(id)
        if record.state == "running" and record.lease_until <= self.clock():
            return self.change(row, record, state="interrupted", error_code="execution_expired")
        return record

    def reserve(self, id, task, snapshot, revision):
        now = self.clock()
        record = CandidateRunRecord(
            id=UUID(id),
            user_id=UUID(self.user_id),
            portfolio_id=snapshot.portfolio_id,
            snapshot=snapshot,
            portfolio_revision=revision,
            task=task,
            state="queued",
            created_at=now,
            updated_at=now,
            expires_at=now + RETENTION,
        )
        inserted = self.store.reserve(runs.encode(record, self.key))
        actual = record if inserted else self.get(id)
        if actual.task != task:
            raise APIError(409, "run_conflict", "This run ID belongs to different constraints.")
        return actual

    def claim(self, id):
        row, record = self.read(id)
        if record.state != "queued" or record.attempts >= 2:
            return None
        claimed = CandidateRunRecord.model_validate(
            {
                **record.model_dump(),
                "state": "running",
                "attempts": record.attempts + 1,
                "lease_until": self.clock() + LEASE,
                "step": "capturing",
                "error_code": None,
                "revision": record.revision + 1,
                "updated_at": self.clock(),
            }
        )
        return claimed if self.store.transition(row, runs.encode(claimed, self.key)) else None

    def publish(self, id, revision, result=None, error_code=None):
        row, record = self.read(id)
        if (
            record.state != "running"
            or record.revision != revision
            or record.lease_until <= self.clock()
        ):
            return self.get(id)
        return self.change(
            row,
            record,
            state="completed" if result is not None else "failed",
            step="done",
            result=result,
            error_code=error_code,
        )

    def cancel(self, id):
        row, record = self.read(id)
        if record.state in {"queued", "running", "interrupted"}:
            return self.change(row, record, state="cancelled", result=None)
        return record

    def resume(self, id):
        record = self.get(id)
        if record.state == "interrupted" and record.attempts < 2:
            row, record = self.read(id)
            return self.change(
                row, record, state="queued", step="queued", lease_until=None, error_code=None
            )
        return record


def journal(user):
    return JobJournal(JobStore(user.access_token, user.id), key(), user.id)


def compute(record, user):
    from libs.auth.active_portfolio import ActivePortfolioContext

    from . import (
        comparison_options,
        comparison_replay,
        comparison_save,
        copilot_candidates,
        copilot_scope,
        market_data,
    )

    expected = str(record.portfolio_id)
    if (
        comparison_save.portfolio_revision(user.access_token, user.id, expected)
        != record.portfolio_revision
    ):
        raise APIError(409, "portfolio_changed", "Portfolio changed; start a fresh analysis.")
    frozen = record.snapshot
    context = ActivePortfolioContext(
        expected,
        deepcopy(frozen.holdings),
        frozen.cash_balance,
        frozen.margin_loan,
        frozen.contributed_capital,
    )
    digest = copilot_scope.context_digest(asdict(context))
    copilot_scope.verify_scope(user.access_token, expected, digest)
    specs = comparison_options.option_specs(context.holdings)
    symbols = sorted(
        {
            t
            for t, h in context.holdings.items()
            if str(h.get("asset_type") or "public_security").lower() != "option"
        }
        | {s.underlying for s in specs}
    )
    provenance = {}
    prices = market_data.get_price_history(symbols, days=365, provenance=provenance)
    now = runs.utcnow()
    from .copilot_compare import prepare_prices

    frame, _ = prepare_prices(prices, symbols, now=now)
    options = comparison_options.capture_options(specs, frame.iloc[-1].to_dict(), now=now)
    batch = copilot_candidates.evaluate(
        context,
        record.task,
        frame,
        provenance.get("by_ticker", {}),
        now=now,
        option_results=options,
    )
    copilot_scope.verify_scope(user.access_token, expected, digest)
    if (
        comparison_save.portfolio_revision(user.access_token, user.id, expected)
        != record.portfolio_revision
    ):
        raise APIError(409, "portfolio_changed", "Portfolio changed during calculation.")
    if get_settings().copilot_comparison_replay_enabled:
        for result in batch.candidates:
            result.replay_receipt = comparison_replay.issue_receipt(
                user.id,
                context,
                frame,
                options,
                provenance.get("by_ticker", {}),
                result,
                portfolio_revision=record.portfolio_revision,
            )
    return batch


class Dispatcher:
    def __init__(self):
        self.queue = Queue(maxsize=4)
        self.pending = set()
        self.lock = Lock()
        self.started = False

    def submit(self, user, id):
        identity = (user.id, id)
        with self.lock:
            if identity in self.pending:
                return True
            if len(self.pending) >= 4:
                return False  # committed queued record is recoverable by explicit resume
            try:
                self.queue.put_nowait((user, id))
            except Full:
                return False
            self.pending.add(identity)
            if not self.started:
                Thread(target=self._loop, daemon=True, name="copilot-worker").start()
                self.started = True
        return True

    def _loop(self):
        while True:
            user, id = self.queue.get()
            try:
                self.run(user, id)
            except Exception:
                # No exception strings: provider errors can contain credentials.
                pass  # durable lease/queued state remains visible and recoverable
            finally:
                with self.lock:
                    self.pending.discard((user.id, id))
                self.queue.task_done()
                del user  # do not retain an expired JWT in an idle worker frame

    @staticmethod
    def run(user, id):
        from ..api.v1 import risk
        from ..core.deps_auth import _decode

        # Reverify expiry and signature before IO. No long-lived worker credential.
        _decode(user.access_token, get_settings())
        if not risk._check_capacity.acquire(timeout=120):
            return  # queued, never pretend that an analysis started
        try:
            _decode(user.access_token, get_settings())  # token may expire while queued
            log = journal(user)
            record = log.claim(id)
            if record is None:
                return
            try:
                result = compute(record, user)
                _decode(user.access_token, get_settings())
            except Exception as exc:
                code = (
                    "portfolio_changed"
                    if isinstance(exc, APIError) and exc.code == "portfolio_changed"
                    else "analysis_failed"
                )
                log.publish(id, record.revision, error_code=code)
            else:
                log.publish(id, record.revision, result=result)
        finally:
            risk._check_capacity.release()


dispatcher = Dispatcher()
