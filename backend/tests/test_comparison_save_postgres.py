"""Opt-in REAL PostgreSQL RLS/atomicity tests, never a remote or existing DB.

Run with MINDMARKET_TEST_PG_SOCKET=/tmp/mindmarket-pg.<private-temp-dir>,
MINDMARKET_TEST_PG_BIN=<postgres-bin-dir>, MINDMARKET_TEST_PG_PORT=55439.
The cluster must already run with no TCP listener. A uniquely named disposable
database is created/dropped here; production DSNs are intentionally unsupported.
"""

import getpass
import json
import os
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.tests.test_comparison_replay import OTHER, USER
from backend.tests.test_copilot_mixed_compare import BOOK

pytestmark = pytest.mark.skipif(
    not os.environ.get("MINDMARKET_TEST_PG_SOCKET"), reason="Disposable PostgreSQL not requested"
)


def literal(value):
    return "'" + value.replace("'", "''") + "'"


@pytest.fixture(scope="module")
def database():
    socket = Path(os.environ["MINDMARKET_TEST_PG_SOCKET"]).resolve()
    assert str(socket).startswith(("/tmp/mindmarket-pg.", "/private/tmp/mindmarket-pg."))
    psql = str(Path(os.environ["MINDMARKET_TEST_PG_BIN"]) / "psql")
    env = {k: v for k, v in os.environ.items() if not k.startswith("PG")}
    name = "mm_comparison_test_" + uuid4().hex
    base = [
        psql,
        "-XqAt",
        "-v",
        "ON_ERROR_STOP=1",
        "-h",
        str(socket),
        "-p",
        os.environ.get("MINDMARKET_TEST_PG_PORT", "55439"),
        "-U",
        getpass.getuser(),
    ]

    def run(sql, user=None, check=True, db=name):
        if user:
            sql = f"set role authenticated; set request.jwt.claim.sub = {literal(user)}; " + sql
        proc = subprocess.run(
            base + ["-d", db], input=sql, text=True, capture_output=True, timeout=12, env=env
        )
        if check:
            assert proc.returncode == 0, proc.stderr
        return proc

    run(f'create database "{name}";', db="postgres")
    try:
        run("""
            create role authenticated nologin;
            create role anon nologin;
            create schema auth;
            create table auth.users(id uuid primary key);
            create function auth.uid() returns uuid language sql stable as $$
                select nullif(current_setting('request.jwt.claim.sub', true), '')::uuid
            $$;
            grant usage on schema auth, public to authenticated, anon;
            grant execute on function auth.uid() to authenticated, anon;
        """)
        root = Path(__file__).resolve().parents[2] / "supabase" / "migrations"
        for filename in ("0001_init.sql", "0012_risk_ops.sql", "0011_activate_portfolio.sql"):
            run((root / filename).read_text())
        run("grant select, insert, update, delete on all tables in schema public to authenticated;")
        # Hosted Supabase may install extensions outside public. The revision
        # trigger must use the built-in UUID generator, not an extension lookup.
        run('create schema extensions; alter extension "uuid-ossp" set schema extensions;')
        migration = (root / "0015_comparison_confirmations.sql").read_text()
        run(migration)
        run(migration)  # New migration is safe to apply twice.
        run(f"insert into auth.users values ('{USER}'), ('{OTHER}');")
        yield run, base + ["-d", name], env
    finally:
        run(f'drop database "{name}" with (force);', db="postgres")
        # Cluster roles cannot be dropped with the DB, and are test-created only.
        run("drop role authenticated; drop role anon;", db="postgres")


@pytest.fixture
def book(database):
    run, _, _ = database
    run("delete from public.portfolios;")
    run(f"""insert into public.portfolios(id, user_id, name, holdings, is_default)
        values ('{BOOK}', '{USER}', 'Fixture', '{{"SPY":{{"shares":10}}}}', true);""")
    revision = run(
        f"select comparison_revision from portfolios where id='{BOOK}';", USER
    ).stdout.strip()
    return revision


def record(revision, age=10, result_id=None):
    now = datetime.now(timezone.utc)
    result_id = result_id or str(uuid4())
    snapshot = {
        "user_id": USER,
        "account": {"portfolio_id": BOOK},
        "portfolio_revision": revision,
        "captured_at": (now - timedelta(seconds=age)).isoformat(),
        "result": {
            "portfolio_id": BOOK,
            "result_id": result_id,
            "assumptions": {"ticker": "SPY", "amount": 10, "proceeds": "cash"},
            "baseline": {"cash": 0},
            "candidate": {"cash": 10},
            "methodology_version": "test",
            "limitations": ["fixture only"],
        },
    }
    proof = {
        "user_id": USER,
        "portfolio_id": BOOK,
        "plan_id": result_id,
        "confirmed_at": now.isoformat(),
        "receipt": {"record": json.dumps(snapshot)},
    }
    return json.dumps(proof), result_id


def call(proof):
    # SQL tests deliberately don't claim HMAC authenticity. API tests cover that
    # separate boundary; RLS alone cannot prove a backend-originated calculation.
    return f"select plan_id from confirm_copilot_comparison({literal(proof)}, '{'a' * 64}');"


def test_rls_immutable_evidence_and_plan_cascade(database, book):
    run, _, _ = database
    proof, plan = record(book)
    assert run(call(proof), USER).stdout.strip() == plan
    assert run("select count(*) from comparison_confirmations;", USER).stdout.strip() == "1"
    assert run("select count(*) from comparison_confirmations;", OTHER).stdout.strip() == "0"
    assert run(call(proof), OTHER, check=False).returncode != 0
    assert (
        run(
            "update comparison_confirmations set signature=repeat('b',64);", USER, check=False
        ).returncode
        != 0
    )
    assert run("delete from comparison_confirmations;", USER, check=False).returncode != 0
    assert (
        run(f"select comparison_revision from portfolios where id='{BOOK}';", USER).stdout.strip()
        == book
    )
    assert (
        run("set role anon; select count(*) from comparison_confirmations;", check=False).returncode
        != 0
    )
    run(f"update risk_plans set title='Edited notes' where id='{plan}';", USER)
    assert run("select record from comparison_confirmations;", USER).stdout.strip() == proof
    run(f"delete from risk_plans where id='{plan}';", USER)
    assert run("select count(*) from comparison_confirmations;").stdout.strip() == "0"


def test_two_concurrent_confirmations_create_one_plan(database, book):
    run, _, _ = database
    proof, plan = record(book)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: run(call(proof), USER).stdout.strip(), range(2)))
    assert results == [plan, plan]
    assert run("select count(*) from risk_plans;").stdout.strip() == "1"
    assert run("select count(*) from comparison_confirmations;").stdout.strip() == "1"


def test_edit_and_revert_rejects_old_revision_without_partial_plan(database, book):
    run, _, _ = database
    proof, _ = record(book)
    run(f"update portfolios set cash_balance=1 where id='{BOOK}';", USER)
    run(
        f"update portfolios set cash_balance=0, comparison_revision='{book}' where id='{BOOK}';",
        USER,
    )
    result = run(call(proof), USER, check=False)
    assert "comparison_stale" in result.stderr
    assert run("select count(*) from risk_plans;").stdout.strip() == "0"


def test_default_switch_and_expired_capture_reject(database, book):
    run, _, _ = database
    old, _ = record(book, age=901)
    assert "comparison_stale" in run(call(old), USER, check=False).stderr
    proof, _ = record(book)
    other_book = str(uuid4())
    run(f"insert into portfolios(id,name) values('{other_book}','Second');", USER)
    run(f"select id from activate_portfolio('{other_book}');", USER)
    assert "comparison_stale" in run(call(proof), USER, check=False).stderr
    assert run("select count(*) from risk_plans;").stdout.strip() == "0"


@pytest.mark.parametrize("operation", ["edit", "switch", "new_default"])
def test_confirm_waits_for_concurrent_portfolio_write(database, book, operation):
    run, command, env = database
    proof, _ = record(book)
    editor = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    try:
        mutation = f"update portfolios set cash_balance=42 where id='{BOOK}';"
        if operation == "switch":
            other = str(uuid4())
            mutation = f"insert into portfolios(id,name) values('{other}','Other'); select count(*) from activate_portfolio('{other}');"
        if operation == "new_default":
            mutation = "insert into portfolios(name,is_default) values('New default',true);"
        editor.stdin.write(
            f"set role authenticated; set request.jwt.claim.sub='{USER}'; begin; {mutation} select 'locked';\n"
        )
        editor.stdin.flush()
        if operation == "switch":
            assert editor.stdout.readline().strip() == "1"
        assert editor.stdout.readline().strip() == "locked"
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(run, "/* mm_confirm_race */ " + call(proof), USER, False)
            deadline = time.monotonic() + 5
            waiting = False
            while time.monotonic() < deadline:
                result = run(
                    "select count(*) from pg_stat_activity where wait_event_type='Lock' and query like '%mm_confirm_race%';"
                ).stdout.strip()
                if result == "1":
                    waiting = True
                    break
                time.sleep(0.02)
            editor.stdin.write("commit;\n")
            editor.stdin.flush()
            assert waiting, "confirmation did not reach the real database lock"
            assert "comparison_stale" in future.result(timeout=8).stderr
        assert run("select count(*) from risk_plans;").stdout.strip() == "0"
        assert run("select count(*) from comparison_confirmations;").stdout.strip() == "0"
    finally:
        editor.communicate("rollback;\n", timeout=5)


def test_signed_service_roundtrip_uses_real_transaction_not_editable_plan(
    database, book, monkeypatch
):
    from uuid import UUID

    from backend.app.schemas.copilot_compare import CompareChange
    from backend.app.services import comparison_replay as replay
    from backend.app.services import comparison_save as save
    from backend.app.services.copilot_compare import compare_change
    from backend.tests.test_comparison_replay import SECRET
    from backend.tests.test_copilot_mixed_compare import prices as price_fixture
    from libs.auth.active_portfolio import ActivePortfolioContext

    run, _, _ = database
    settings = SimpleNamespace(
        copilot_comparison_save_enabled=True,
        copilot_comparison_replay_enabled=True,
        risk_run_signing_secret=SECRET,
    )
    monkeypatch.setattr(save, "get_settings", lambda: settings)
    monkeypatch.setattr(replay, "get_settings", lambda: settings)
    now = datetime.now(timezone.utc)
    context = ActivePortfolioContext(BOOK, {"SPY": {"shares": 10}}, 0, 0, 0)
    prices = price_fixture.__wrapped__()[["SPY"]]
    result = compare_change(
        context,
        CompareChange(expected_portfolio_id=BOOK, ticker="SPY", amount=100.0, proceeds="cash"),
        prices,
        {},
        now=now,
    )
    receipt = replay.issue_receipt(
        USER, context, prices, [], {}, result, portfolio_revision=UUID(book)
    )

    def existing(token, user, plan_id):
        assert token == "test-jwt"
        rows = run(
            f"select row_to_json(c) from comparison_confirmations c where plan_id='{plan_id}';",
            user,
        ).stdout.strip()
        return json.loads(rows) if rows else None

    class Client:
        def rpc(self, name, params):
            assert name == "confirm_copilot_comparison"
            self.params = params
            return self

        def execute(self):
            rows = run(
                f"select row_to_json(c) from confirm_copilot_comparison({literal(self.params['p_record'])}, {literal(self.params['p_signature'])}) c;",
                USER,
            ).stdout.strip()
            return SimpleNamespace(data=[json.loads(rows)])

    monkeypatch.setattr(save, "_existing", existing)
    monkeypatch.setattr(save, "_client", lambda token: Client())
    saved = save.confirm("test-jwt", USER, BOOK, str(result.result_id), receipt)
    assert saved.result == result
    from backend.app.services.plan_review import build_review

    baseline = json.loads(
        run(f"select baseline from risk_plans where id='{saved.plan_id}';", USER).stdout
    )
    assert baseline == {"captured_comparison": result.baseline.model_dump(mode="json")}
    assert (
        build_review(baseline, {"annual_volatility": 0.0001, "leverage": 1})["verdict"]
        == "inconclusive"
    )
    run(
        f"update risk_plans set expected_impact='{{\"cash\":99999999}}' where id='{saved.plan_id}';",
        USER,
    )
    assert save.get_saved("test-jwt", USER, BOOK, str(saved.plan_id)).result == result
    assert save.confirm("test-jwt", USER, BOOK, str(saved.plan_id), receipt) == saved
