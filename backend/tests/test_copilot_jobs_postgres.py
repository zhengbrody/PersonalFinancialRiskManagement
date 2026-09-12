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
    return run


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
    run(
        f"insert into copilot_runs(id,user_id,portfolio_id,state,record,signature) values ('{id}','{USER}','{BOOK}','{state}',{literal(raw)},repeat('a',64));",
        USER,
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
        migrated(
            f"insert into copilot_runs(id,user_id,portfolio_id,state,record,signature,created_at) "
            f"select gen_random_uuid(),'{USER}','{BOOK}','queued',{raw},repeat('a',64),now()-interval '2 days' from generate_series(1,{count});",
            USER,
        )
    assert migrated(f"select cleanup_copilot_jobs('{BOOK}');", OTHER).stdout.strip() == "0"
    assert migrated(f"select cleanup_copilot_jobs('{BOOK}');", USER).stdout.strip() == "100"
    assert migrated(f"select cleanup_copilot_jobs('{BOOK}');", USER).stdout.strip() == "1"
    assert migrated("select count(*) from copilot_runs;", USER).stdout.strip() == "1"
