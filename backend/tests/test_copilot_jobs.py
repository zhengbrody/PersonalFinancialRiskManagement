from copy import deepcopy
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from backend.app.core.responses import APIError
from backend.app.schemas.copilot_runs import RunSnapshot
from backend.app.services import copilot_jobs as jobs
from backend.app.services import copilot_runs as runs
from backend.tests.test_copilot_candidates import task
from backend.tests.test_copilot_compare import BOOK

USER = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"
NOW = datetime(2026, 9, 11, tzinfo=timezone.utc)


class MemoryStore:
    def __init__(self):
        self.rows = {}
        self.lose_cas = False

    def get(self, id):
        return deepcopy(self.rows.get(id))

    def reserve(self, row):
        if row["id"] in self.rows:
            return False
        self.rows[row["id"]] = deepcopy(row)
        return True

    def transition(self, old, new):
        if self.lose_cas or self.rows[old["id"]]["signature"] != old["signature"]:
            return False
        self.rows[old["id"]] = deepcopy(new)
        return True


@pytest.fixture
def journal():
    store = MemoryStore()
    clock = [NOW]
    log = jobs.JobJournal(store, b"x" * 32, USER, lambda: clock[0])
    snapshot = RunSnapshot(
        portfolio_id=BOOK,
        holdings={"SPY": {"shares": 10}},
        cash_balance=1000,
        margin_loan=100,
        contributed_capital=1000,
        risk_preference=3,
        preference_source="neutral_baseline",
    )
    record = log.reserve(str(uuid4()), task(), snapshot, uuid4())
    return log, str(record.id), clock


def test_duplicate_reservation_and_claim(journal):
    log, id, _ = journal
    original = log.get(id)
    duplicate = log.reserve(id, original.task, original.snapshot, original.portfolio_revision)
    assert duplicate == original
    assert log.claim(id).attempts == 1
    assert log.claim(id) is None


def test_cas_loser_does_not_compute(journal):
    log, id, _ = journal
    log.store.lose_cas = True
    assert log.claim(id) is None


def test_cancel_blocks_late_publication(journal):
    log, id, _ = journal
    claimed = log.claim(id)
    log.cancel(id)
    late = log.publish(id, claimed.revision, error_code="analysis_failed")
    assert late.state == "cancelled" and late.result is None


def test_expired_worker_and_bounded_reauthentication_resume(journal):
    log, id, clock = journal
    first = log.claim(id)
    clock[0] += jobs.LEASE + timedelta(seconds=1)
    assert log.publish(id, first.revision).state == "interrupted"
    assert log.resume(id).state == "queued"
    second = log.claim(id)
    assert second.attempts == 2
    assert log.publish(id, first.revision).state == "running"
    clock[0] += jobs.LEASE + timedelta(seconds=1)
    assert log.resume(id).state == "interrupted"
    assert log.claim(id) is None


def test_hmac_owner_scope_and_retention(journal):
    log, id, clock = journal
    row = log.store.get(id)
    for key, owner in [(b"y" * 32, USER), (b"x" * 32, OTHER)]:
        with pytest.raises(APIError) as exc:
            runs.decode(row, key, owner, id, record_type=jobs.CandidateRunRecord)
        assert exc.value.code == "untrusted_run"
    clock[0] += jobs.LEASE + timedelta(seconds=1)
    assert log.get(id).state == "queued"  # execution and retention differ
    clock[0] = NOW + jobs.RETENTION
    with pytest.raises(APIError) as exc:
        log.get(id)
    assert exc.value.status == 410


def test_forged_index_rejected(journal):
    log, id, _ = journal
    log.store.rows[id]["state"] = "completed"
    with pytest.raises(APIError) as exc:
        log.get(id)
    assert exc.value.code == "untrusted_run"


def test_disabled_endpoint_cannot_touch_storage(test_client, mint_token, monkeypatch):
    from unittest.mock import Mock

    from backend.app.core.config import reset_settings_cache

    monkeypatch.setenv("MINDMARKET_ASYNC_ANALYSIS_ENABLED", "false")
    reset_settings_cache()
    storage = Mock(side_effect=AssertionError("disabled request must not reach DB"))
    monkeypatch.setattr(jobs, "journal", storage)
    payload = {"id": str(uuid4()), "task": task().model_dump(mode="json")}
    assert test_client.post("/api/v1/copilot/decision-runs", json=payload).status_code == 401
    response = test_client.post(
        "/api/v1/copilot/decision-runs",
        json=payload,
        headers={"Authorization": f"Bearer {mint_token(sub=USER)}"},
    )
    assert response.status_code == 503
    storage.assert_not_called()


def test_api_duplicate_start_and_read_do_not_recompute(
    test_client, mint_token, monkeypatch, journal
):
    from unittest.mock import Mock

    log, id, _ = journal
    monkeypatch.setattr(jobs, "require_enabled", lambda: None)
    monkeypatch.setattr(jobs, "journal", lambda user: log)
    dispatch = Mock(return_value=True)
    monkeypatch.setattr(test_client.app.state.copilot_dispatcher, "submit", dispatch)
    headers = {"Authorization": f"Bearer {mint_token(sub=USER)}"}
    body = {"id": id, "task": task().model_dump(mode="json")}
    start = test_client.post("/api/v1/copilot/decision-runs", json=body, headers=headers)
    assert start.status_code == 200 and start.json()["data"]["state"] == "queued"
    claimed = log.claim(id)
    duplicate = test_client.post("/api/v1/copilot/decision-runs", json=body, headers=headers)
    assert duplicate.status_code == 200 and duplicate.json()["data"]["state"] == "running"
    assert (
        test_client.get(f"/api/v1/copilot/decision-runs/{id}", headers=headers).status_code == 200
    )
    assert dispatch.call_count == 1
    assert "snapshot" not in duplicate.json()["data"] and "user_id" not in duplicate.json()["data"]
    assert log.get(id).revision == claimed.revision


def test_worker_uses_frozen_account_one_fetch_and_revision_guard(monkeypatch):
    from dataclasses import asdict
    from types import SimpleNamespace

    from backend.app.schemas.copilot_jobs import CandidateRunRecord
    from backend.app.services import comparison_save, copilot_scope, market_data
    from backend.tests import test_copilot_compare as fixtures

    context = fixtures.context.__wrapped__()
    frame = fixtures.prices.__wrapped__()
    revision = uuid4()
    record = CandidateRunRecord(
        id=uuid4(),
        user_id=USER,
        portfolio_id=BOOK,
        portfolio_revision=revision,
        task=task(),
        snapshot=RunSnapshot(
            **asdict(context), risk_preference=3, preference_source="neutral_baseline"
        ),
        state="queued",
        created_at=NOW,
        updated_at=NOW,
        expires_at=NOW + jobs.RETENTION,
    )
    user = SimpleNamespace(id=USER, access_token="transient")
    monkeypatch.setattr(jobs.runs, "utcnow", lambda: fixtures.NOW)
    revisions = []

    def read_revision(*args):
        revisions.append(args)
        return revision

    monkeypatch.setattr(comparison_save, "portfolio_revision", read_revision)
    scopes = []
    monkeypatch.setattr(copilot_scope, "verify_scope", lambda *args: scopes.append(args))
    fetches = []

    def fetch(symbols, **kwargs):
        fetches.append(symbols)
        return frame

    monkeypatch.setattr(market_data, "get_price_history", fetch)
    monkeypatch.setattr(
        jobs, "get_settings", lambda: SimpleNamespace(copilot_comparison_replay_enabled=False)
    )
    result = jobs.compute(record, user)
    assert fetches == [["SGOV", "SPY"]]
    assert len(revisions) == 2 and len(scopes) == 2
    assert result.candidates[0].candidate.cash == 1500
    assert record.snapshot.cash_balance == 1000
    monkeypatch.setattr(comparison_save, "portfolio_revision", lambda *args: uuid4())
    with pytest.raises(APIError) as exc:
        jobs.compute(record, user)
    assert exc.value.code == "portfolio_changed"
    assert len(fetches) == 1


def test_worker_waits_for_capacity_revalidates_then_publishes(monkeypatch, journal):
    from types import SimpleNamespace
    from unittest.mock import Mock

    from backend.app.api.v1 import risk
    from backend.app.core import deps_auth

    log, id, _ = journal
    lane = Mock()
    lane.acquire.return_value = True
    auth = Mock(return_value={"sub": USER})
    monkeypatch.setattr(risk, "_check_capacity", lane)
    monkeypatch.setattr(deps_auth, "_decode", auth)
    monkeypatch.setattr(jobs, "journal", lambda user: log)
    compute = Mock(side_effect=APIError(409, "portfolio_changed", "changed"))
    monkeypatch.setattr(jobs, "compute", compute)
    jobs.Dispatcher.run(SimpleNamespace(id=USER, access_token="transient"), id)
    lane.acquire.assert_called_once_with(timeout=1)
    lane.release.assert_called_once()
    assert auth.call_count == 3  # before queue, after queue, before publishing failure
    assert compute.call_count == 1
    assert log.get(id).state == "failed"
    assert log.get(id).error_code == "portfolio_changed"


def test_renewal_extends_lease_but_never_execution_budget(journal):
    log, id, clock = journal
    first = log.claim(id)
    clock[0] += timedelta(seconds=90)
    renewed = log.renew(id, first.revision, "evaluating")
    assert renewed.lease_until > first.lease_until
    assert renewed.execution_deadline == first.execution_deadline == NOW + jobs.MAX_EXECUTION
    assert log.renew(id, first.revision) is None
    assert log.renew(id, renewed.revision, "capturing") is None
    clock[0] = NOW + timedelta(seconds=200)
    last = log.renew(id, renewed.revision)
    assert last.lease_until == first.execution_deadline
    clock[0] = first.execution_deadline
    assert log.renew(id, last.revision) is None
    assert log.publish(id, last.revision).state == "interrupted"


def test_shutdown_discards_transient_dispatches_and_refuses_new_work():
    from types import SimpleNamespace

    dispatcher = jobs.Dispatcher()
    dispatcher.started = True  # deterministic queued-only case; no worker launched
    user = SimpleNamespace(id=USER, access_token="must not persist")
    assert dispatcher.submit(user, "queued")
    dispatcher.shutdown()
    assert dispatcher.queue.empty() and dispatcher.pending == set()
    assert not dispatcher.submit(user, "later")


def test_lease_loss_or_shutdown_prevents_publication(journal, monkeypatch):
    from threading import Event
    from types import SimpleNamespace

    from backend.app.core import deps_auth

    log, id, _ = journal
    claimed = log.claim(id)
    monkeypatch.setattr(deps_auth, "_decode", lambda *args: {})
    shutdown = Event()
    lease = jobs.ExecutionLease(log, claimed, SimpleNamespace(access_token="transient"), shutdown)
    lease.pulse("evaluating")
    shutdown.set()
    with pytest.raises(jobs.ExecutionStopped):
        lease.pulse()
    assert lease.finish().state == "interrupted"
    assert log.get(id).result is None


def test_recovery_requeues_only_trusted_recoverable_jobs(journal, monkeypatch):
    from types import SimpleNamespace

    from backend.app.core import deps_auth

    log, id, clock = journal
    log.claim(id)
    clock[0] += jobs.LEASE + timedelta(seconds=1)
    monkeypatch.setattr(
        log.store, "recent", lambda book: list(log.store.rows.values()), raising=False
    )
    monkeypatch.setattr(jobs, "journal", lambda user: log)
    monkeypatch.setattr(jobs, "require_enabled", lambda: None)
    monkeypatch.setattr(deps_auth, "_decode", lambda *args: {})
    dispatcher = jobs.Dispatcher()
    dispatcher.started = True
    dispatched, untrusted = dispatcher.recover(SimpleNamespace(id=USER, access_token="fresh"), BOOK)
    assert dispatched == 1 and untrusted == 0
    assert log.get(id).state == "queued"
    assert dispatcher.queue.qsize() == 1
    dispatcher.shutdown()


def test_recent_ignores_invalid_documents_and_untrusted_signatures(journal, monkeypatch):
    log, id, _ = journal
    valid = log.store.get(id)
    rows = [valid, {**valid, "record": "[]"}, {**valid, "signature": "a" * 64}]
    monkeypatch.setattr(log.store, "recent", lambda _: rows, raising=False)
    records, untrusted = log.recent(BOOK)
    assert [str(record.id) for record in records] == [id]
    assert untrusted == 2
