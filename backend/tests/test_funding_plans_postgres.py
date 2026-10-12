"""Real owner-scoped transaction, reusing the disposable PostgreSQL fixture."""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from backend.tests import test_comparison_save_postgres as shared

pytestmark = pytest.mark.skipif(
    not os.environ.get("MINDMARKET_TEST_PG_SOCKET"), reason="Disposable PostgreSQL not requested"
)
database = shared.database
book = shared.book
USER, OTHER = shared.USER, shared.OTHER
BOOK = shared.BOOK


@pytest.fixture(scope="module")
def run(database):
    run, _, _ = database
    migration = (
        Path(__file__).resolve().parents[2]
        / "supabase/migrations/0019_funding_plan_confirmations.sql"
    )
    run(migration.read_text())
    run(migration.read_text())
    return run


def proof(revision, age=10):
    raw, id = shared.record(revision, age=age)
    data = json.loads(raw)
    snap = json.loads(data["receipt"]["record"])
    snap["kind"] = "funding_scenarios"
    snap["result"]["methodology_version"] = "funding-scenarios-v1"
    snap["result"]["sale_ticker"] = "SPY"
    data["receipt"]["record"] = json.dumps(snap)
    return json.dumps(data), id


def call(record):
    return f"select plan_id from confirm_copilot_funding_plan({shared.literal(record)},repeat('a',64));"


def test_concurrent_retry_one_original_plan(run, book):
    record, id = proof(book)
    with ThreadPoolExecutor(max_workers=2) as pool:
        outputs = list(pool.map(lambda _: run(call(record), USER).stdout.strip(), range(2)))
    assert outputs == [id, id]
    assert run("select count(*) from risk_plans;", USER).stdout.strip() == "1"
    assert run("select title from risk_plans;", USER).stdout.strip() == "Funding scenario: SPY"
    assert run("select baseline ? 'captured_funding' from risk_plans;", USER).stdout.strip() == "t"
    assert run("select count(*) from comparison_confirmations;", OTHER).stdout.strip() == "0"


def test_expired_or_edited_capture_cannot_save(run, book):
    expired, _ = proof(book, age=901)
    assert "comparison_stale" in run(call(expired), USER, check=False).stderr
    record, _ = proof(book)
    run(f"update portfolios set cash_balance=1 where id='{BOOK}';", USER)
    run(
        f"update portfolios set cash_balance=0, comparison_revision='{book}' where id='{BOOK}';",
        USER,
    )
    assert "comparison_stale" in run(call(record), USER, check=False).stderr
    assert run("select count(*) from risk_plans;", USER).stdout.strip() == "0"


def test_cross_owner_and_wrong_calculation_kind_rejected(run, book):
    record, _ = proof(book)
    assert "comparison_conflict" in run(call(record), OTHER, check=False).stderr
    wrong, _ = shared.record(book)
    assert "comparison_conflict" in run(call(wrong), USER, check=False).stderr
    assert run("select count(*) from risk_plans;", USER).stdout.strip() == "0"
