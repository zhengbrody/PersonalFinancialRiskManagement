"""Bounded background candidate execution using the original run store and HMAC.

One daemon worker per process; at most four dispatches (including active). JWTs
are transient memory only, released on completion. Recovery requires an explicit
resume request with a freshly verified JWT. Nothing publishes after the lease
expires; Python/provider code itself is not preemptible. No automatic trades.
"""

import json
import logging
from copy import deepcopy
from dataclasses import asdict
from datetime import timedelta
from queue import Empty, Full, Queue
from threading import Event, Lock, Thread
from uuid import UUID

from ..core.config import get_settings
from ..core.responses import APIError
from ..schemas.copilot_jobs import CandidateRunRecord
from . import copilot_runs as runs

RETENTION = timedelta(days=1)
LEASE = timedelta(seconds=120)
MAX_EXECUTION = timedelta(minutes=5)
_log = logging.getLogger(__name__)


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
    def recent(self, portfolio_id):
        return self._execute(
            lambda: self.client.table("copilot_runs")
            .select("*")
            .eq("user_id", self.user_id)
            .eq("portfolio_id", portfolio_id)
            .order("created_at", desc=True)
            .limit(40)
        )

    def cleanup(self, portfolio_id):
        value = self._execute(
            lambda: self.client.rpc("cleanup_copilot_jobs", {"p_portfolio_id": portfolio_id})
        )
        return int(value or 0)

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
                "execution_deadline": self.clock() + MAX_EXECUTION,
                "step": "capturing",
                "error_code": None,
                "revision": record.revision + 1,
                "updated_at": self.clock(),
            }
        )
        return claimed if self.store.transition(row, runs.encode(claimed, self.key)) else None

    def recent(self, portfolio_id):
        records, untrusted = [], 0
        for row in self.store.recent(portfolio_id):
            try:
                # Only version-two records belong to this view. Parsing grants no trust.
                document = json.loads(row["record"])
                if not isinstance(document, dict):
                    raise ValueError("Invalid stored document")
                if document.get("version") != 2:
                    continue
                record = runs.decode(
                    row, self.key, self.user_id, row["id"], record_type=CandidateRunRecord
                )
                if str(record.portfolio_id) != portfolio_id:
                    raise ValueError("Wrong portfolio index")
                if record.expires_at > self.clock():
                    records.append(self.get(str(record.id)))
            except (APIError, ValueError, KeyError, TypeError):
                untrusted += 1
            if len(records) >= 20:
                break
        return records, untrusted

    def renew(self, id, revision, step=None):
        row, record = self.read(id)
        now = self.clock()
        deadline = record.execution_deadline or record.lease_until
        if (
            record.state != "running"
            or record.revision != revision
            or record.lease_until <= now
            or deadline is None
            or deadline <= now
        ):
            return None
        steps = {"queued": 0, "capturing": 1, "evaluating": 2, "done": 3}
        if step is not None and steps[step] < steps[record.step]:
            return None
        updated = CandidateRunRecord.model_validate(
            {
                **record.model_dump(),
                "revision": record.revision + 1,
                "updated_at": now,
                "lease_until": min(now + LEASE, deadline),
                "step": step or record.step,
            }
        )
        return updated if self.store.transition(row, runs.encode(updated, self.key)) else None

    def interrupt(self, id, revision):
        row, record = self.read(id)
        if record.state != "running" or record.revision != revision:
            return record
        return self.change(row, record, state="interrupted", error_code="execution_expired")

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
                row,
                record,
                state="queued",
                step="queued",
                lease_until=None,
                execution_deadline=None,
                error_code=None,
            )
        return record


def journal(user):
    return JobJournal(JobStore(user.access_token, user.id), key(), user.id)


def compute(record, user, progress=None):
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
    if progress:
        progress("capturing")
    provenance = {}
    prices = market_data.get_price_history(symbols, days=365, provenance=provenance)
    now = runs.utcnow()
    from .copilot_compare import prepare_prices

    frame, _ = prepare_prices(prices, symbols, now=now)
    options = comparison_options.capture_options(specs, frame.iloc[-1].to_dict(), now=now)
    if progress:
        progress("evaluating")
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


class ExecutionStopped(Exception):
    """Lost lease, expired authentication or shutdown; never publish this result."""


class ExecutionLease:
    def __init__(self, log, record, user, shutdown):
        self.log, self.record, self.user, self.shutdown = log, record, user, shutdown
        self.lock = Lock()
        self.stopped = Event()
        self.lost = False
        self.thread = Thread(target=self._loop, daemon=True, name="copilot-lease")

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.stopped.set()
        self.thread.join(timeout=1)

    def pulse(self, step=None):
        from ..core.deps_auth import _decode

        with self.lock:
            if self.lost or self.shutdown.is_set():
                self.lost = True
                raise ExecutionStopped()
            try:
                _decode(self.user.access_token, get_settings())
                current = self.log.renew(str(self.record.id), self.record.revision, step)
                if current is None:
                    raise ExecutionStopped()
                self.record = current
            except Exception:
                self.lost = True
                raise ExecutionStopped() from None

    def _loop(self):
        while not self.stopped.wait(20):
            try:
                self.pulse()
            except ExecutionStopped:
                return

    def finish(self, result=None, error_code=None):
        from ..core.deps_auth import _decode

        with self.lock:
            if self.lost or self.shutdown.is_set():
                return self.log.interrupt(str(self.record.id), self.record.revision)
            _decode(self.user.access_token, get_settings())
            return self.log.publish(str(self.record.id), self.record.revision, result, error_code)


class Dispatcher:
    def __init__(self):
        self.queue = Queue(maxsize=4)
        self.pending = set()
        self.lock = Lock()
        self.started = False
        self.stopping = Event()
        self.worker = None

    def submit(self, user, id):
        identity = (user.id, id)
        with self.lock:
            if self.stopping.is_set():
                return False
            if identity in self.pending:
                return True
            if len(self.pending) >= 4:
                return False
            try:
                self.queue.put_nowait((user, id))
            except Full:
                return False
            self.pending.add(identity)
            if not self.started:
                self.worker = Thread(target=self._loop, daemon=True, name="copilot-worker")
                self.worker.start()
                self.started = True
        return True

    def shutdown(self):
        self.stopping.set()
        # Drop queued in-memory JWTs; the durable queued rows remain recoverable.
        while True:
            try:
                user, id = self.queue.get_nowait()
            except Empty:
                break
            with self.lock:
                self.pending.discard((user.id, id))
            self.queue.task_done()
        if self.worker:
            self.worker.join(timeout=1)

    def recover(self, user, portfolio_id):
        from ..core.deps_auth import _decode

        _decode(user.access_token, get_settings())
        require_enabled()
        log = journal(user)
        records, untrusted = log.recent(portfolio_id)
        dispatched = 0
        for record in reversed(records):
            if record.state == "interrupted" and record.attempts < 2:
                record = log.resume(str(record.id))
            if record.state == "queued" and self.submit(user, str(record.id)):
                dispatched += 1
            if dispatched >= 4:
                break
        return dispatched, untrusted

    def _loop(self):
        while not self.stopping.is_set():
            try:
                user, id = self.queue.get(timeout=0.5)
            except Empty:
                continue
            try:
                self.run(user, id, self.stopping)
            except Exception as exc:
                _log.warning("copilot_job.worker_failed type=%s", type(exc).__name__)
            finally:
                with self.lock:
                    self.pending.discard((user.id, id))
                self.queue.task_done()
            if not self.stopping.is_set():
                try:
                    record = journal(user).get(id)
                    self.recover(user, str(record.portfolio_id))
                except Exception:
                    pass  # expired auth cannot be elevated for recovery
            del user

    @staticmethod
    def run(user, id, shutdown=None):
        from ..api.v1 import risk
        from ..core.deps_auth import _decode

        shutdown = shutdown or Event()
        _decode(user.access_token, get_settings())
        # Short waits make process shutdown observable even when another analysis owns the lane.
        import time

        deadline = time.monotonic() + 120
        while not shutdown.is_set():
            if risk._check_capacity.acquire(timeout=1):
                break
            if time.monotonic() >= deadline:
                return
        else:
            return
        try:
            _decode(user.access_token, get_settings())
            log = journal(user)
            record = log.claim(id)
            if record is None:
                return
            with ExecutionLease(log, record, user, shutdown) as lease:
                try:
                    result = compute(record, user, progress=lease.pulse)
                except ExecutionStopped:
                    log.interrupt(id, lease.record.revision)
                except Exception as exc:
                    code = (
                        "portfolio_changed"
                        if isinstance(exc, APIError) and exc.code == "portfolio_changed"
                        else "analysis_failed"
                    )
                    lease.finish(error_code=code)
                else:
                    lease.finish(result=result)
        finally:
            risk._check_capacity.release()
