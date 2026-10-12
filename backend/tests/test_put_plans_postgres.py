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
        Path(__file__).resolve().parents[2] / "supabase/migrations/0018_put_plan_confirmations.sql"
    )
    run(migration.read_text())
    run(migration.read_text())
    return run


def proof(revision, age=10):
    raw, id = shared.record(revision, age=age)
    data = json.loads(raw)
    snap = json.loads(data["receipt"]["record"])
    snap["kind"] = "cash_secured_put"
    snap["result"]["methodology_version"] = "cash-secured-put-v1"
    snap["result"]["assumptions"]["underlying"] = "SPY"
    data["receipt"]["record"] = json.dumps(snap)
    return json.dumps(data), id


def call(record):
    return f"select plan_id from confirm_copilot_put_plan({shared.literal(record)},repeat('a',64));"


def test_concurrent_retry_one_original_plan(run, book):
    record, id = proof(book)
    with ThreadPoolExecutor(max_workers=2) as pool:
        outputs = list(pool.map(lambda _: run(call(record), USER).stdout.strip(), range(2)))
    assert outputs == [id, id]
    assert run("select count(*) from risk_plans;", USER).stdout.strip() == "1"
    assert run("select title from risk_plans;", USER).stdout.strip() == "Cash-secured Put: SPY"
    assert run("select baseline ? 'captured_put' from risk_plans;", USER).stdout.strip() == "t"
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


def test_review_after_real_confirm_writes_no_row_and_bumps_no_revision(run, book, monkeypatch):
    """Row counts in every table the feature can reach, before and after the API
    review handler, on the real database with the real confirm RPC.

    The portfolio ``comparison_revision`` is the sharpest signal: 0015's trigger
    regenerates it on ANY write to the row, so an unchanged revision proves the
    review touched neither holdings nor capital.
    """
    from dataclasses import asdict
    from datetime import datetime, timedelta, timezone
    from types import SimpleNamespace
    from uuid import UUID

    from starlette.requests import Request

    from backend.app.api.v1 import copilot_put as api
    from backend.app.core.config import reset_settings_cache
    from backend.app.schemas.put_plan import ReviewPutPlanRequest
    from backend.app.services import comparison_save, copilot_scope
    from backend.app.services import put_plans as service
    from backend.tests.test_copilot_put import request
    from libs.auth import active_portfolio
    from libs.auth.active_portfolio import ActivePortfolioContext

    monkeypatch.setenv("MINDMARKET_CASH_SECURED_PUT_SAVE_ENABLED", "true")
    monkeypatch.setenv(
        "MINDMARKET_RISK_RUN_SIGNING_SECRET", "put-plans-test-signing-key-0000000000000000"
    )
    reset_settings_cache()
    # Real wall clock on purpose: the confirm RPC fences captured_at/confirmed_at
    # against the DATABASE clock, so a fixture date would be rejected as stale.
    now = datetime.now(timezone.utc)
    context = ActivePortfolioContext(BOOK, {"SPY": {"shares": 10}}, 11000, 0, 0)
    digest = copilot_scope.context_digest(asdict(context))
    # Expiry relative to the real clock too, so this test is not a calendar bomb.
    body = request(expiry=(now + timedelta(days=60)).date().isoformat())
    result = service.copilot_put.calculate(context, body, digest, now=now)
    receipt = service.issue(USER, context, UUID(book), result)

    def existing(token, user, plan_id):
        rows = run(
            f"select row_to_json(c) from comparison_confirmations c where plan_id='{plan_id}';",
            user,
        ).stdout.strip()
        return json.loads(rows) if rows else None

    class Client:
        def rpc(self, name, params):
            assert name == "confirm_copilot_put_plan"
            self.params = params
            return self

        def execute(self):
            rows = run(
                f"select row_to_json(c) from confirm_copilot_put_plan({shared.literal(self.params['p_record'])}, {shared.literal(self.params['p_signature'])}) c;",
                USER,
            ).stdout.strip()
            return SimpleNamespace(data=[json.loads(rows)])

    monkeypatch.setattr(comparison_save, "_existing", existing)
    monkeypatch.setattr(service, "_client", lambda token: Client())
    saved = service.confirm("jwt", USER, BOOK, str(result.result_id), receipt)
    plan_id = str(saved.plan_id)

    def counts():
        return {
            table: run(f"select count(*) from {table};").stdout.strip()
            for table in ("risk_plans", "comparison_confirmations", "portfolios")
        }

    def revision():
        return run(
            f"select comparison_revision from portfolios where id='{BOOK}';", USER
        ).stdout.strip()

    before, revision_before = counts(), revision()
    assert before["risk_plans"] == "1" and before["comparison_confirmations"] == "1"

    monkeypatch.setattr(
        comparison_save, "portfolio_revision", lambda token, user, book_id: UUID(revision())
    )
    monkeypatch.setattr(
        active_portfolio, "get_active_portfolio_context", lambda access_token: context
    )
    monkeypatch.setattr(copilot_scope, "resolve_scope", lambda token, expected: digest)
    response = api.review_plan(
        UUID(plan_id),
        ReviewPutPlanRequest(expected_portfolio_id=UUID(BOOK)),
        Request({"type": "http", "headers": []}),
        SimpleNamespace(id=USER, access_token="jwt"),
    )
    assert response.status_code == 200
    body = json.loads(response.body)["data"]
    assert body["verdict"] in {"assumptions_need_confirmation", "requires_recalculation"}
    assert counts() == before
    assert revision() == revision_before
    stored = run(f"select record from comparison_confirmations where plan_id='{plan_id}';", USER)
    assert json.loads(stored.stdout)["receipt"]["record"] == receipt.record
