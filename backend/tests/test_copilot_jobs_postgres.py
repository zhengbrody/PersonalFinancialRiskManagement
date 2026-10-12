"""Real RLS and server-clock fencing, using the existing isolated DB fixture."""

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from backend.tests import test_comparison_save_postgres as db_fixtures
from backend.tests.test_copilot_compare import BOOK
from backend.tests.test_copilot_jobs import OTHER, USER

pytestmark = pytest.mark.skipif(
    not os.environ.get("MINDMARKET_TEST_PG_SOCKET"), reason="Disposable PostgreSQL not requested"
)
database = db_fixtures.database
book = db_fixtures.book
literal = db_fixtures.literal


@pytest.fixture(scope="module")
def migrated(database):
    run, _, _ = database
    root = Path(__file__).resolve().parents[2] / "supabase/migrations"
    run((root / "0014_copilot_runs.sql").read_text())
    run((root / "0016_copilot_background.sql").read_text())
    run((root / "0017_copilot_job_recovery.sql").read_text())
    integrity = (root / "0020_copilot_job_integrity.sql").read_text()
    run(integrity)
    run(integrity)  # re-runnable
    # 0014 is re-runnable too, and a re-run never undoes 0016's wider CHECK.
    run((root / "0014_copilot_runs.sql").read_text())
    return run


def seed(run, sql):
    """Arbitrary fixture rows (e.g. already running, or backdated) are seeded as
    the cluster owner with triggers off: real clients can only create a fresh
    queued reservation, which is exactly what the 0020 tests below assert."""
    run("set session_replication_role = replica; " + sql)


def insert(run, *, state="queued", lease=None):
    id = str(uuid4())
    doc = dict(
        version=2,
        id=id,
        user_id=USER,
        portfolio_id=BOOK,
        state=state,
        revision=0,
        task={},
        snapshot={},
        portfolio_revision="test",
        expires_at="2099-01-01T00:00:00Z",
        lease_until=lease,
        attempts=1 if state == "running" else 0,
        execution_deadline=lease if state == "running" else None,
    )
    raw = json.dumps(doc)
    seed(
        run,
        f"insert into copilot_runs(id,user_id,portfolio_id,state,record,signature) values ('{id}','{USER}','{BOOK}','{state}',{literal(raw)},repeat('a',64));",
    )
    return doc


def transition(run, doc, state, *, user=USER):
    new = {**doc, "state": state, "revision": 1}
    if state == "running":
        if doc["state"] == "queued":
            new["attempts"] = doc["attempts"] + 1
            new["execution_deadline"] = (
                datetime.now(timezone.utc) + timedelta(minutes=4)
            ).isoformat()
        new["lease_until"] = (datetime.now(timezone.utc) + timedelta(minutes=2)).isoformat()
    return run(
        f"select count(*) from transition_copilot_job('{doc['id']}',repeat('a',64),{literal(json.dumps(new))},repeat('b',64),'{state}');",
        user,
    ).stdout.strip()


def test_claim_is_compare_and_swap(migrated, book):
    doc = insert(migrated)
    assert transition(migrated, doc, "running") == "1"
    assert transition(migrated, doc, "running") == "0"


def test_server_rejects_expired_worker(migrated, book):
    for state in ("running", "completed", "failed"):
        doc = insert(migrated, state="running", lease="2020-01-01T00:00:00Z")
        assert transition(migrated, doc, state) == "0"


def test_cross_user_cannot_read_or_transition(migrated, book):
    doc = insert(migrated)
    assert (
        migrated(f"select count(*) from copilot_runs where id='{doc['id']}';", OTHER).stdout.strip()
        == "0"
    )
    assert transition(migrated, doc, "running", user=OTHER) == "0"


def test_cancel_fences_worker(migrated, book):
    doc = insert(migrated, state="running", lease="2099-01-01T00:00:00Z")
    assert transition(migrated, doc, "cancelled") == "1"
    assert transition(migrated, doc, "completed") == "0"


def test_live_lease_cannot_be_reclaimed(migrated, book):
    doc = insert(migrated, state="running", lease="2099-01-01T00:00:00Z")
    assert transition(migrated, doc, "queued") == "0"


@pytest.mark.parametrize("violation", ["extend_deadline", "null_lease", "beyond_deadline"])
def test_database_rejects_invalid_renewal(migrated, book, violation):
    now = datetime.now(timezone.utc)
    deadline = (now + timedelta(minutes=3)).isoformat()
    doc = insert(migrated, state="running", lease=deadline)
    new = {**doc, "revision": 1}
    if violation == "extend_deadline":
        new["execution_deadline"] = (now + timedelta(minutes=4)).isoformat()
    elif violation == "null_lease":
        new["lease_until"] = None
    else:
        new["lease_until"] = (now + timedelta(minutes=4)).isoformat()
    result = migrated(
        f"select count(*) from transition_copilot_job('{doc['id']}',repeat('a',64),{literal(json.dumps(new))},repeat('b',64),'running');",
        USER,
    )
    assert result.stdout.strip() == "0"


def test_cleanup_is_bounded_owner_scoped_and_preserves_legacy(migrated, book):
    for version, count in ((2, 101), (1, 1)):
        raw = literal(json.dumps({"version": version}, separators=(",", ":")))
        seed(
            migrated,
            f"insert into copilot_runs(id,user_id,portfolio_id,state,record,signature,created_at) "
            f"select gen_random_uuid(),'{USER}','{BOOK}','queued',{raw},repeat('a',64),now()-interval '2 days' from generate_series(1,{count});",
        )
    assert migrated(f"select cleanup_copilot_jobs('{BOOK}');", OTHER).stdout.strip() == "0"
    assert migrated(f"select cleanup_copilot_jobs('{BOOK}');", USER).stdout.strip() == "100"
    assert migrated(f"select cleanup_copilot_jobs('{BOOK}');", USER).stdout.strip() == "1"
    assert migrated("select count(*) from copilot_runs;", USER).stdout.strip() == "1"


# ---- 0020: database-clock interruption, monotonic records, per-owner limit ----


def fresh_doc(state="queued", **overrides):
    now = datetime.now(timezone.utc)
    doc = dict(
        version=2,
        id=str(uuid4()),
        user_id=USER,
        portfolio_id=BOOK,
        state=state,
        revision=0,
        attempts=0,
        task={},
        snapshot={},
        portfolio_revision="test",
        created_at=now.isoformat(),
        expires_at=(now + timedelta(days=1)).isoformat(),
        lease_until=None,
        execution_deadline=None,
    )
    doc.update(overrides)
    return doc


def client_insert(run, doc, *, user=USER, check=True):
    return run(
        f"insert into copilot_runs(id,user_id,portfolio_id,state,record,signature) values "
        f"('{doc['id']}','{doc['user_id']}','{doc['portfolio_id']}','{doc['state']}',"
        f"{literal(json.dumps(doc))},repeat('a',64));",
        user,
        check=check,
    )


def test_reader_cannot_interrupt_a_live_lease_only_an_expired_one(migrated, book):
    live = insert(migrated, state="running", lease="2099-01-01T00:00:00Z")
    assert transition(migrated, live, "interrupted") == "0"
    state = migrated(f"select state from copilot_runs where id='{live['id']}';", USER)
    assert state.stdout.strip() == "running"
    dead = insert(migrated, state="running", lease="2020-01-01T00:00:00Z")
    assert transition(migrated, dead, "interrupted") == "1"


def test_fresh_queued_reservation_is_the_only_insertable_record(migrated, book):
    assert client_insert(migrated, fresh_doc()).returncode == 0
    seed(migrated, "delete from copilot_runs;")
    old = fresh_doc(created_at=(datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat())
    for doc in (
        old,
        fresh_doc(state="running", lease_until="2099-01-01T00:00:00Z"),
        fresh_doc(revision=3),
        fresh_doc(attempts=1),
    ):
        result = client_insert(migrated, doc, check=False)
        assert result.returncode != 0 and "copilot_job_replay" in result.stderr, doc
    assert migrated("select count(*) from copilot_runs;", USER).stdout.strip() == "0"


def test_direct_update_cannot_roll_a_record_back(migrated, book):
    doc = fresh_doc()
    client_insert(migrated, doc)
    advanced = {**doc, "state": "interrupted", "revision": 5, "attempts": 2}
    seed(
        migrated,
        f"update copilot_runs set state='interrupted', record={literal(json.dumps(advanced))} "
        f"where id='{doc['id']}';",
    )
    for older in (
        {**doc, "state": "queued", "revision": 2, "attempts": 0},  # restored old record
        {**advanced, "revision": 6, "attempts": 0},  # attempts reset
        {**advanced, "revision": 5},  # same revision, different bytes
    ):
        older_raw = json.dumps({**older, "nonce": str(uuid4())})
        result = migrated(
            f"update copilot_runs set state='{older['state']}', record={literal(older_raw)} "
            f"where id='{doc['id']}';",
            USER,
            check=False,
        )
        assert result.returncode != 0 and "copilot_job_rollback" in result.stderr, older
    stored = migrated(f"select record from copilot_runs where id='{doc['id']}';", USER)
    assert json.loads(stored.stdout.strip())["attempts"] == 2


def test_one_active_job_per_owner_including_requeue(migrated, book):
    first = fresh_doc()
    client_insert(migrated, first)
    second = client_insert(migrated, fresh_doc(), check=False)
    assert second.returncode != 0 and "copilot_job_limit" in second.stderr
    # A running job with an EXPIRED lease is not active: a new one may start...
    seed(migrated, "delete from copilot_runs;")
    insert(migrated, state="running", lease="2020-01-01T00:00:00Z")
    assert client_insert(migrated, fresh_doc()).returncode == 0
    # ...but re-queueing an interrupted job while another is active is refused.
    blocked = insert(migrated, state="interrupted")
    requeue = {**blocked, "state": "queued", "revision": 1}
    result = migrated(
        f"select count(*) from transition_copilot_job('{blocked['id']}',repeat('a',64),"
        f"{literal(json.dumps(requeue))},repeat('b',64),'queued');",
        USER,
        check=False,
    )
    assert result.returncode != 0 and "copilot_job_limit" in result.stderr


def test_concurrent_starts_admit_exactly_one(migrated, book):
    from concurrent.futures import ThreadPoolExecutor

    docs = [fresh_doc() for _ in range(4)]
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda d: client_insert(migrated, d, check=False), docs))
    assert sum(r.returncode == 0 for r in results) == 1
    assert migrated("select count(*) from copilot_runs;", USER).stdout.strip() == "1"


def test_legacy_version_one_rows_are_unaffected(migrated, book):
    for _ in range(2):  # no limit, no freshness rule for version-one checks
        migrated(
            f"insert into copilot_runs(id,user_id,portfolio_id,state,record,signature) values "
            f"(gen_random_uuid(),'{USER}','{BOOK}','running',"
            f"{literal(json.dumps({'version': 1}))},repeat('a',64));",
            USER,
        )
    migrated(f"update copilot_runs set record={literal(json.dumps({'version': 1, 'x': 1}))};", USER)


def test_overlapping_transactions_cannot_both_start(migrated, database, book):
    """Deterministic race: the first start holds its transaction open; the
    second must WAIT on the owner lock and then see the first, not read a
    pre-commit snapshot with zero active jobs and admit itself too."""
    import subprocess
    import time

    _, base, env = database
    first, second = fresh_doc(), fresh_doc()

    def sql(doc, hold):
        return (
            f"set role authenticated; set request.jwt.claim.sub = {literal(USER)}; begin; "
            f"insert into copilot_runs(id,user_id,portfolio_id,state,record,signature) values "
            f"('{doc['id']}','{USER}','{BOOK}','queued',{literal(json.dumps(doc))},repeat('a',64)); "
            f"select pg_sleep({hold}); commit;"
        )

    holder = subprocess.Popen(
        base,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    holder.stdin.write(sql(first, 1.5))
    holder.stdin.close()
    time.sleep(0.5)  # the first insert is in, uncommitted
    late = subprocess.run(
        base, input=sql(second, 0), text=True, capture_output=True, env=env, timeout=12
    )
    holder.wait(timeout=12)
    assert holder.returncode == 0, holder.stderr.read()
    assert late.returncode != 0 and "copilot_job_limit" in late.stderr
    assert migrated("select count(*) from copilot_runs;", USER).stdout.strip() == "1"


# ---- anti-replay: delete + re-insert, column-only edits, foreign limit calls ----


def test_fresh_job_row_cannot_be_deleted_to_replay_its_reservation(migrated, book):
    """The attack: run a job (attempts=1), delete the row, re-insert the original
    signed reservation (revision 0, attempts 0) to get a third attempt."""
    original = fresh_doc()
    assert client_insert(migrated, original).returncode == 0
    assert transition(migrated, original, "running") == "1"
    deleted = migrated(f"delete from copilot_runs where id='{original['id']}';", USER, check=False)
    assert deleted.returncode != 0 and "copilot_job_replay" in deleted.stderr
    replay = client_insert(migrated, original, check=False)
    assert replay.returncode != 0
    stored = migrated(f"select record from copilot_runs where id='{original['id']}';", USER)
    assert json.loads(stored.stdout.strip())["attempts"] == 1
    # Moving the row aside (new id) to free the original id is refused as well.
    moved = migrated(
        f"update copilot_runs set id=gen_random_uuid() where id='{original['id']}';",
        USER,
        check=False,
    )
    assert moved.returncode != 0 and "copilot_job_rollback" in moved.stderr


def test_deletable_rows_are_exactly_those_that_can_never_be_reinserted(migrated, book):
    seed(migrated, "delete from copilot_runs;")
    old = fresh_doc(created_at=(datetime.now(timezone.utc) - timedelta(minutes=6)).isoformat())
    seed(
        migrated,
        f"insert into copilot_runs(id,user_id,portfolio_id,state,record,signature) values "
        f"('{old['id']}','{USER}','{BOOK}','queued',{literal(json.dumps(old))},repeat('a',64));",
    )
    migrated(f"delete from copilot_runs where id='{old['id']}';", USER)
    again = client_insert(migrated, old, check=False)
    assert again.returncode != 0 and "copilot_job_replay" in again.stderr
    assert migrated("select count(*) from copilot_runs;", USER).stdout.strip() == "0"
    # Version-one rows remain freely deletable.
    migrated(
        f"insert into copilot_runs(id,user_id,portfolio_id,state,record,signature) values "
        f"(gen_random_uuid(),'{USER}','{BOOK}','running',{literal(json.dumps({'version': 1}))},repeat('a',64));"
        "delete from copilot_runs;",
        USER,
    )


def test_column_only_state_change_is_refused(migrated, book):
    seed(migrated, "delete from copilot_runs;")
    doc = fresh_doc()
    client_insert(migrated, doc)
    for sql in ("set state='completed'", "set signature=repeat('c',64)"):
        result = migrated(f"update copilot_runs {sql} where id='{doc['id']}';", USER, check=False)
        assert result.returncode != 0 and "copilot_job_rollback" in result.stderr, sql
    assert (
        migrated(f"select state from copilot_runs where id='{doc['id']}';", USER).stdout.strip()
        == "queued"
    )


def test_job_limit_cannot_be_called_for_another_user(migrated, book):
    result = migrated(f"select enforce_copilot_job_limit('{OTHER}', gen_random_uuid());", USER, check=False)
    assert result.returncode != 0 and "copilot_job_forbidden" in result.stderr
    assert migrated(f"select enforce_copilot_job_limit('{USER}', gen_random_uuid());", USER).returncode == 0


def test_portfolio_deletion_cascades_through_a_fresh_job(migrated, book):
    seed(migrated, "delete from copilot_runs;")
    client_insert(migrated, fresh_doc())
    migrated(f"delete from portfolios where id='{BOOK}';", USER)
    assert migrated("select count(*) from copilot_runs;", USER).stdout.strip() == "0"
