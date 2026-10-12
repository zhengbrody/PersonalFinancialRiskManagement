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

    def active(self):
        return [deepcopy(r) for r in self.rows.values() if r["state"] in ("queued", "running")]

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
        implementation=jobs.execution_fingerprint(),
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


@pytest.mark.parametrize("drift", [None, "different-version"])
def test_version_drift_cannot_claim_but_old_record_remains_readable(journal, drift):
    log, id, _ = journal
    row, original = log.read(id)
    changed = original.model_copy(update={"implementation": drift})
    log.store.rows[id] = runs.encode(changed, log.key)
    assert log.get(id).state == "queued"
    assert log.claim(id) is None
    stopped = log.get(id)
    assert stopped.state == "failed" and stopped.error_code == "execution_version_changed"
    assert stopped.attempts == 0 and stopped.result is None


def test_execution_rechecks_version_before_any_provider_access(journal):
    log, id, _ = journal
    record = log.get(id).model_copy(update={"implementation": "different-version"})
    with pytest.raises(APIError, match="version changed"):
        jobs.compute(record, None)


# ---- signing purpose, fair dispatch, truthful start, database-clock interrupt ----


def test_job_records_use_a_purpose_key_not_the_raw_root(monkeypatch, journal):
    import hashlib
    import hmac

    from backend.app.core.config import reset_settings_cache

    root = "job-signing-root-0000000000000000000000000"
    monkeypatch.setenv("MINDMARKET_RISK_RUN_SIGNING_SECRET", root)
    reset_settings_cache()
    try:
        derived = jobs.key()
        assert derived != root.encode()
        assert (
            derived
            == hmac.new(root.encode(), b"mindmarket:copilot-job:v2", hashlib.sha256).digest()
        )
        log, id, _ = journal
        record = log.get(id)
        raw_signed = runs.encode(record, root.encode())  # a record MACed with the raw root
        with pytest.raises(APIError) as exc:
            runs.decode(raw_signed, derived, USER, id, record_type=jobs.CandidateRunRecord)
        assert exc.value.code == "untrusted_run"
        # Version-one foreground runs keep the raw root (existing stored runs).
        monkeypatch.setenv("MINDMARKET_COPILOT_RUNS_ENABLED", "true")
        reset_settings_cache()
        assert runs.signing_key() == root.encode()
    finally:
        reset_settings_cache()


def test_dispatch_is_fair_per_owner_and_bounded_globally():
    from types import SimpleNamespace

    dispatcher = jobs.Dispatcher()
    dispatcher.started = True
    a, b = SimpleNamespace(id="owner-a", access_token="t"), SimpleNamespace(
        id="owner-b", access_token="t"
    )
    assert dispatcher.submit(a, "a1")
    assert dispatcher.submit(a, "a1"), "re-submitting the same job is idempotent"
    assert not dispatcher.has_capacity(a) and not dispatcher.submit(a, "a2")
    assert dispatcher.has_capacity(b) and dispatcher.submit(b, "b1")
    for owner in ("c", "d"):
        assert dispatcher.submit(SimpleNamespace(id=owner, access_token="t"), owner + "1")
    late = SimpleNamespace(id="e", access_token="t")
    assert not dispatcher.has_capacity(late) and not dispatcher.submit(late, "e1")
    dispatcher.shutdown()


def test_active_count_counts_only_live_trusted_jobs(journal):
    log, id, clock = journal
    assert log.active_count() == 1  # the queued reservation
    assert log.active_count(exclude=id) == 0
    log.claim(id)
    assert log.active_count() == 1  # running with a live lease
    clock[0] += jobs.LEASE + timedelta(seconds=1)
    assert log.active_count() == 0  # lease expired: no longer holding anything
    clock[0] -= jobs.LEASE + timedelta(seconds=1)
    log.store.rows[id]["signature"] = "a" * 64
    assert log.active_count() == 0  # untrusted rows are not counted


def test_reader_does_not_interrupt_when_the_database_refuses(journal):
    """The application clock only PROPOSES expiry; migration 0020 lets the
    database refuse while its own clock still sees a live lease."""
    log, id, clock = journal
    claimed = log.claim(id)
    clock[0] += jobs.LEASE + timedelta(seconds=1)  # app clock runs fast
    log.store.lose_cas = True  # database refuses the interruption
    current = log.get(id)
    assert current.state == "running" and current.revision == claimed.revision


def test_resume_is_refused_while_another_job_is_active(journal):
    log, id, clock = journal
    log.claim(id)
    clock[0] += jobs.LEASE + timedelta(seconds=1)
    assert log.get(id).state == "interrupted"
    other = log.reserve(str(uuid4()), task(), log.read(id)[1].snapshot, uuid4())
    assert other.state == "queued"
    with pytest.raises(APIError) as exc:
        log.resume(id)
    assert exc.value.status == 429 and exc.value.code == "too_many_active_runs"
    assert log.get(id).state == "interrupted"


def test_storage_integrity_refusals_keep_their_meaning():
    from types import SimpleNamespace

    store = jobs.JobStore.__new__(jobs.JobStore)
    store.user_id = USER
    for text, code in (
        ("P0001 copilot_job_limit", "too_many_active_runs"),
        ("P0001 copilot_job_replay", "run_conflict"),
        ("P0001 copilot_job_rollback", "run_conflict"),
        ("connection reset", "run_storage_unavailable"),
    ):

        def build(text=text):
            return SimpleNamespace(execute=lambda: (_ for _ in ()).throw(RuntimeError(text)))

        with pytest.raises(APIError) as exc:
            store._guarded(build)
        assert exc.value.code == code


@pytest.fixture
def start_api(test_client, mint_token, monkeypatch, journal):
    from unittest.mock import Mock

    from backend.app.api.v1 import risk
    from backend.app.services import comparison_save, risk_profile

    log, existing, _ = journal
    monkeypatch.setattr(jobs, "require_enabled", lambda: None)
    monkeypatch.setattr(jobs, "journal", lambda user: log)
    snapshot = log.read(existing)[1].snapshot
    from libs.auth.active_portfolio import ActivePortfolioContext

    context = ActivePortfolioContext(
        str(snapshot.portfolio_id),
        snapshot.holdings,
        snapshot.cash_balance,
        snapshot.margin_loan,
        snapshot.contributed_capital,
    )
    monkeypatch.setattr(risk, "_resolve_active_context_or_raise", lambda user: context)
    monkeypatch.setattr(
        risk_profile,
        "resolve_risk_preference",
        lambda user: Mock(value=3, source="neutral_baseline", confirmed_at=None),
    )
    monkeypatch.setattr(comparison_save, "portfolio_revision", lambda *a: uuid4())
    dispatcher = test_client.app.state.copilot_dispatcher
    headers = {"Authorization": f"Bearer {mint_token(sub=USER)}"}

    def post(id):
        body = {"id": id, "task": task().model_dump(mode="json")}
        return test_client.post("/api/v1/copilot/decision-runs", json=body, headers=headers)

    return log, existing, dispatcher, post


def test_start_refuses_a_second_active_job_without_writing(start_api, monkeypatch):
    log, existing, dispatcher, post = start_api
    reserve = []
    monkeypatch.setattr(log, "reserve", lambda *a: reserve.append(a))
    response = post(str(uuid4()))
    assert response.status_code == 429
    assert response.json()["error"]["code"] == "too_many_active_runs"
    assert reserve == []


def test_start_never_reports_queued_when_nothing_will_run_it(start_api, monkeypatch):
    log, existing, dispatcher, post = start_api
    log.cancel(existing)  # free the owner's active slot
    # Queue full before reserving: nothing is written.
    monkeypatch.setattr(dispatcher, "has_capacity", lambda user: False)
    new_id = str(uuid4())
    response = post(new_id)
    assert response.status_code == 429
    error = response.json()["error"]
    assert error["code"] == "analysis_queue_full" and "Nothing was saved" in error["message"]
    assert error["details"] == {"saved": False}
    assert new_id not in log.store.rows
    # Capacity looked free, but the slot was taken before submit: saved, not started.
    monkeypatch.setattr(dispatcher, "has_capacity", lambda user: True)
    monkeypatch.setattr(dispatcher, "submit", lambda user, id: False)
    response = post(new_id)
    assert response.status_code == 429
    assert "Saved as queued but not started" in response.json()["error"]["message"]
    assert response.json()["error"]["details"] == {"saved": True}
    assert log.get(new_id).state == "queued"
    # Retrying the SAME id once a slot frees dispatches it, without duplicating.
    submitted = []
    monkeypatch.setattr(dispatcher, "submit", lambda user, id: submitted.append(id) or True)
    response = post(new_id)
    assert response.status_code == 200 and response.json()["data"]["state"] == "queued"
    assert submitted == [new_id]
    assert sum(1 for r in log.store.rows if r == new_id) == 1


def test_concurrent_duplicate_of_the_same_run_is_idempotent_not_a_second_job(
    start_api, monkeypatch
):
    """Two instances receive the SAME request: ours looks it up (404), then the
    other instance reserves that id before our active-job pre-check runs. That
    record is this request, not another active job: answer 200 with it."""
    log, existing, dispatcher, post = start_api
    log.cancel(existing)  # the owner has no other active job
    snapshot = log.read(existing)[1].snapshot
    new_id = str(uuid4())
    original_get, raced = log.get, []

    def racing_get(id):
        if id == new_id and not raced:
            raced.append(id)
            log.reserve(new_id, task(), snapshot, uuid4())  # the other instance wins
            raise APIError(404, "run_not_found", "Run not found.")
        return original_get(id)

    monkeypatch.setattr(log, "get", racing_get)
    monkeypatch.setattr(dispatcher, "submit", lambda user, id: True)
    response = post(new_id)
    assert raced == [new_id]
    assert response.status_code == 200, response.json()
    assert response.json()["data"]["id"] == new_id
