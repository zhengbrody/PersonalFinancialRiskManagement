"""Real PostgreSQL RLS: cross-device reads, owner isolation, portfolio scope and
evidence immutability under editable-plan edits. Reuses the disposable fixture
(opt-in via MINDMARKET_TEST_PG_SOCKET; never a remote or existing database)."""

import hashlib
import hmac
import json
import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID

import numpy as np
import pandas as pd
import pytest

from backend.app.core.config import reset_settings_cache
from backend.app.core.responses import APIError
from backend.app.services import comparison_replay as replay
from backend.app.services import comparison_save as save
from backend.app.services import copilot_compare as compare
from backend.app.services import saved_plan_history as history
from backend.tests import test_comparison_save_postgres as shared
from backend.tests.test_copilot_mixed_compare import change
from libs.auth.active_portfolio import ActivePortfolioContext

pytestmark = pytest.mark.skipif(
    not os.environ.get("MINDMARKET_TEST_PG_SOCKET"), reason="Disposable PostgreSQL not requested"
)
database = shared.database
book = shared.book
USER, OTHER, BOOK = shared.USER, shared.OTHER, shared.BOOK
OTHER_BOOK = "44444444-4444-4444-8444-444444444444"


@pytest.fixture(autouse=True)
def flags(monkeypatch):
    for name in (
        "MINDMARKET_COMPARISON_REPLAY_ENABLED",
        "MINDMARKET_COMPARISON_SAVE_ENABLED",
        "MINDMARKET_PLAN_HISTORY_ENABLED",
    ):
        monkeypatch.setenv(name, "true")
    monkeypatch.setenv("MINDMARKET_RISK_RUN_SIGNING_SECRET", "history-pg-signing-key-" + "0" * 20)
    reset_settings_cache()
    yield
    reset_settings_cache()


def sql(value):
    return shared.literal(value)


class PgClient:
    """The PostgREST chain the service uses, executed AS the caller (RLS applies)."""

    def __init__(self, run, caller):
        self.run, self.caller = run, caller

    def __call__(self, token):
        return _Query(self)


class _Query:
    def __init__(self, client):
        self.client, self.where, self.n = client, [], 100

    def table(self, name):
        assert name == "comparison_confirmations"
        return self

    def select(self, columns):
        return self

    def order(self, key):
        return self

    def eq(self, key, value):
        self.where.append(f"{key} = {sql(str(value))}")
        return self

    def gt(self, key, value):
        self.where.append(f"{key} > {sql(str(value))}")
        return self

    def limit(self, n):
        self.n = n
        return self

    def execute(self):
        where = " and ".join(self.where) or "true"
        out = self.client.run(
            "select coalesce(json_agg(r), '[]') from (select user_id::text, portfolio_id::text, "
            "plan_id::text, record, signature from comparison_confirmations "
            f"where {where} order by plan_id limit {int(self.n)}) r;",
            self.client.caller,
        ).stdout.strip()
        return SimpleNamespace(data=json.loads(out))


def save_plan(run, revision):
    """A REAL signed comparison, committed by the real 0015 RPC as USER."""
    now = datetime.now(timezone.utc)
    end = pd.Timestamp(now.date()) - pd.tseries.offsets.BDay(1)
    dates = pd.bdate_range(end=end, periods=101)
    rng = np.random.default_rng(3)
    prices = pd.DataFrame(
        {
            "SGOV": 100 * np.exp(np.cumsum(rng.normal(0, 0.001, 101))),
            "SPY": 200 * np.exp(np.cumsum(rng.normal(0, 0.01, 101))),
        },
        index=dates,
    )
    context = ActivePortfolioContext(BOOK, {"SGOV": {"shares": 10}, "SPY": {"shares": 10}}, 0, 0, 0)
    result = compare.compare_change(
        context, change(ticker="SPY", amount=10, proceeds="cash"), prices, {}, now=now
    )
    receipt = replay.issue_receipt(
        USER, context, prices, [], {}, result, portfolio_revision=UUID(revision)
    )
    proof = save.Confirmation(
        user_id=USER,
        portfolio_id=BOOK,
        plan_id=result.result_id,
        confirmed_at=now,
        receipt=receipt.model_copy(update={"save_available": False}),
    )
    record = replay.canonical(proof)
    signature = hmac.new(save._key(), record.encode(), hashlib.sha256).hexdigest()
    out = run(
        f"select plan_id from confirm_copilot_comparison({sql(record)}, {sql(signature)});", USER
    )
    assert out.stdout.strip() == str(result.result_id)
    return str(result.result_id), record, signature


def test_fresh_session_owner_read_other_user_blocked_and_edits_cannot_touch_evidence(
    database, book, monkeypatch
):
    run, _, _ = database
    run("delete from risk_plans;")
    run(
        f"insert into portfolios(id, user_id, name, holdings, is_default) values "
        f"('{OTHER_BOOK}', '{USER}', 'Second', '{{}}', false);"
    )
    plan_id, record, signature = save_plan(run, book)
    sha = hashlib.sha256(record.encode()).hexdigest()

    # A, fresh session: only JWT identity + portfolio id, no client-held receipt.
    monkeypatch.setattr(history, "_client", PgClient(run, USER))
    page = history.page("jwt", USER, BOOK)
    assert [str(p.plan_id) for p in page.plans] == [plan_id]
    assert page.plans[0].evidence_sha256 == sha
    original = history.detail("jwt", USER, BOOK, plan_id)

    # B: RLS hides the row even when B queries with A's identifiers.
    monkeypatch.setattr(history, "_client", PgClient(run, OTHER))
    assert run("select count(*) from comparison_confirmations;", OTHER).stdout.strip() == "0"
    assert history.page("jwt", USER, BOOK).plans == []
    with pytest.raises(APIError) as exc:
        history.detail("jwt", USER, BOOK, plan_id)
    assert exc.value.status == 404

    # A edits every editable plan field, including moving the plan to portfolio Q.
    run(
        f"update risk_plans set title='edited', status='active', hypothesis='changed', "
        f"expected_impact='{{\"x\":1}}', portfolio_id='{OTHER_BOOK}' where id='{plan_id}';",
        USER,
    )
    # Evidence has no UPDATE/DELETE grant for the owner.
    for statement in (
        f"update comparison_confirmations set record='{{}}' where plan_id='{plan_id}';",
        f"delete from comparison_confirmations where plan_id='{plan_id}';",
    ):
        assert "permission denied" in run(statement, USER, check=False).stderr
    stored = json.loads(
        run(
            "select json_build_object('r', record, 's', signature) from comparison_confirmations;",
            USER,
        ).stdout
    )
    assert stored == {"r": record, "s": signature}

    monkeypatch.setattr(history, "_client", PgClient(run, USER))
    after = history.detail("jwt", USER, BOOK, plan_id)
    assert after == original and after.item.evidence_sha256 == sha
    # Not shown under Q although the editable plan row now says Q.
    assert history.page("jwt", USER, OTHER_BOOK).plans == []
    with pytest.raises(APIError) as exc:
        history.detail("jwt", USER, OTHER_BOOK, plan_id)
    assert exc.value.status == 404


def test_cursor_paging_over_real_rows(database, book, monkeypatch):
    run, _, _ = database
    run("delete from risk_plans;")
    ids = []
    for _ in range(3):
        revision = run(
            f"select comparison_revision from portfolios where id='{BOOK}';", USER
        ).stdout.strip()
        ids.append(save_plan(run, revision)[0])
    monkeypatch.setattr(history, "PAGE", 2)
    monkeypatch.setattr(history, "_client", PgClient(run, USER))
    first = history.page("jwt", USER, BOOK)
    second = history.page("jwt", USER, BOOK, first.next_cursor)
    seen = [str(p.plan_id) for p in first.plans + second.plans]
    assert seen == sorted(ids) and second.next_cursor is None
    assert (datetime.now(timezone.utc) - first.plans[0].confirmed_at) < timedelta(minutes=5)
