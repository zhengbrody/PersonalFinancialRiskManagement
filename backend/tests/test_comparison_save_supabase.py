"""Opt-in local Supabase acceptance: real Auth, HTTP, PostgREST and RLS.

Requires a dedicated CLI stack named mindmarket-staging-20260906. Never links
to or accepts a hosted project. Market inputs are synthetic; authentication,
the application process, database client and RPC are not mocked.
"""

import json
import os
import secrets
import socket
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse
from uuid import uuid4

import numpy as np
import pandas as pd
import pytest
import requests

from backend.app.core.config import reset_settings_cache
from backend.app.schemas.copilot_compare import CompareChange
from backend.app.services import comparison_replay, copilot_compare
from libs.auth.active_portfolio import ActivePortfolioContext

PROJECT = "mindmarket-staging-20260906"
ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(
    not os.environ.get("MINDMARKET_TEST_SUPABASE_WORKDIR"),
    reason="Dedicated local Supabase acceptance not requested",
)


@pytest.fixture(scope="module")
def stack(tmp_path_factory):
    workdir = Path(os.environ["MINDMARKET_TEST_SUPABASE_WORKDIR"]).resolve()
    assert str(workdir) in (f"/tmp/{PROJECT}", f"/private/tmp/{PROJECT}")
    assert not (workdir / "supabase/.temp/project-ref").exists(), "Never use a linked project"
    config = (workdir / "supabase/config.toml").read_text()
    assert f'project_id = "{PROJECT}"' in config
    for kind in ("kong", "db"):
        inspected = subprocess.run(
            ["docker", "inspect", f"supabase_{kind}_{PROJECT}"],
            capture_output=True,
            text=True,
            timeout=15,
            check=True,
        )
        container = json.loads(inspected.stdout)[0]
        assert container["Config"]["Labels"]["com.supabase.cli.project"] == PROJECT
        bindings = container["NetworkSettings"]["Ports"]
        published = [row for rows in bindings.values() if rows for row in rows]
        assert published and all(
            row["HostIp"] == "127.0.0.1" for row in published
        ), "Restrict local Supabase published ports to loopback before creating fixtures"
    status = subprocess.run(
        ["supabase", "status", "--workdir", str(workdir), "--output", "json"],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    keys = json.loads(status.stdout)
    url = keys["API_URL"]
    assert urlparse(url).hostname == "127.0.0.1", "Only the isolated local stack is allowed"

    def sql(statement):
        result = subprocess.run(
            [
                "docker",
                "exec",
                "-i",
                f"supabase_db_{PROJECT}",
                "psql",
                "-XqAt",
                "-U",
                "postgres",
                "-v",
                "ON_ERROR_STOP=1",
                "-d",
                "postgres",
            ],
            input=statement,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, "Local migration/query failed; inspect local DB logs"
        return result.stdout.strip()

    # Do not restore production data or emulate auth.uid(): this is Supabase's
    # actual platform schema and Auth service. Apply only required app tables.
    migrations = ROOT / "supabase/migrations"
    for name in ("0001_init.sql", "0011_activate_portfolio.sql"):
        sql((migrations / name).read_text())
    if not sql("select to_regclass('public.copilot_preferences');"):
        sql((migrations / "0009_copilot_preferences.sql").read_text())
    if not sql("select to_regclass('public.risk_plans');"):
        sql((migrations / "0012_risk_ops.sql").read_text())
    sql((migrations / "0015_comparison_confirmations.sql").read_text())
    if not sql("select to_regclass('public.copilot_runs');"):
        sql((migrations / "0014_copilot_runs.sql").read_text())
    for name in (
        "0016_copilot_background.sql",
        "0017_copilot_job_recovery.sql",
        "0018_put_plan_confirmations.sql",
    ):
        sql((migrations / name).read_text())
    sql("notify pgrst, 'reload schema';")

    settings = {
        "SUPABASE_URL": url,
        "SUPABASE_ANON_KEY": keys["ANON_KEY"],
        "SUPABASE_JWT_SECRET": keys["JWT_SECRET"],
        "MINDMARKET_ENV": "staging",
        "MINDMARKET_COMPARISON_REPLAY_ENABLED": "true",
        "MINDMARKET_COMPARISON_SAVE_ENABLED": "true",
        "MINDMARKET_DECISION_SUPPORT_ENABLED": "true",
        "MINDMARKET_ASYNC_ANALYSIS_ENABLED": "true",
        "MINDMARKET_CASH_SECURED_PUT_ENABLED": "true",
        "MINDMARKET_CASH_SECURED_PUT_SAVE_ENABLED": "true",
        "MINDMARKET_RISK_RUN_SIGNING_SECRET": secrets.token_urlsafe(48),
        "SENTRY_DSN": "",
    }
    # Select a free loopback port; the process readiness assertion catches races.
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    control = tmp_path_factory.mktemp("worker-control")
    env = {**os.environ, **settings, "MINDMARKET_TEST_WORKER_CONTROL": str(control)}
    with pytest.MonkeyPatch.context() as patch:
        for key, value in settings.items():
            patch.setenv(key, value)
        reset_settings_cache()
        server = None

        def spawn(listen_port):
            child = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "backend.tests.supabase_worker_app:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(listen_port),
                    "--no-access-log",
                ],
                cwd=ROOT,
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            for _ in range(100):
                assert child.poll() is None, "Isolated application failed to start"
                try:
                    if (
                        requests.get(
                            f"http://127.0.0.1:{listen_port}/api/v1/health", timeout=1
                        ).status_code
                        == 200
                    ):
                        break
                except requests.ConnectionError:
                    pass
                time.sleep(0.2)
            else:
                child.terminate()
                child.wait(timeout=15)
                pytest.fail("Isolated application readiness timeout")
            return child

        def launch():
            nonlocal server
            server = spawn(port)

        @contextmanager
        def peer():
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                peer_port = sock.getsockname()[1]
            child = spawn(peer_port)
            try:
                yield f"http://127.0.0.1:{peer_port}"
            finally:
                child.terminate()
                child.wait(timeout=15)

        def crash_restart():
            server.kill()
            server.wait(timeout=15)
            (control / "hold").unlink(missing_ok=True)
            launch()

        try:
            launch()
            yield SimpleNamespace(
                url=url,
                keys=keys,
                base=base,
                sql=sql,
                control=control,
                crash_restart=crash_restart,
                peer=peer,
            )
        finally:
            if server is not None:
                server.terminate()
                server.wait(timeout=15)
            reset_settings_cache()


@pytest.fixture
def account(stack):
    users = []

    def create():
        email = f"comparison-{uuid4().hex}@example.test"
        password = secrets.token_urlsafe(32)
        admin = {
            "apikey": stack.keys["ANON_KEY"],
            "Authorization": "Bearer " + stack.keys["SERVICE_ROLE_KEY"],
        }
        response = requests.post(
            stack.url + "/auth/v1/admin/users",
            headers=admin,
            json={"email": email, "password": password, "email_confirm": True},
            timeout=15,
        )
        assert response.status_code in (200, 201), "Local fixture user creation failed"
        user = response.json()["id"]
        users.append(user)
        response = requests.post(
            stack.url + "/auth/v1/token?grant_type=password",
            headers={"apikey": stack.keys["ANON_KEY"]},
            json={"email": email, "password": password},
            timeout=15,
        )
        assert response.status_code == 200, "Real password login failed"
        token = response.json()["access_token"]
        headers = {
            "apikey": stack.keys["ANON_KEY"],
            "Authorization": "Bearer " + token,
            "Prefer": "return=representation",
        }
        response = requests.post(
            stack.url + "/rest/v1/portfolios",
            headers=headers,
            json={
                "name": "Synthetic acceptance",
                "holdings": {"SPY": {"shares": 10}},
                "cash_balance": 1000,
                "is_default": True,
            },
            timeout=15,
        )
        assert response.status_code == 201, "JWT-scoped portfolio creation failed"
        return SimpleNamespace(user=user, headers=headers, row=response.json()[0])

    try:
        yield create
    finally:
        # Only IDs created in this fixture; never enumerate/delete existing users.
        for user in users:
            response = requests.delete(
                stack.url + "/auth/v1/admin/users/" + user,
                headers={
                    "apikey": stack.keys["ANON_KEY"],
                    "Authorization": "Bearer " + stack.keys["SERVICE_ROLE_KEY"],
                },
                timeout=15,
            )
            assert response.status_code == 200, "Local fixture cleanup failed"


def capture(owner):
    now = datetime.now(timezone.utc)
    dates = pd.bdate_range(end=now.date(), periods=101)
    prices = pd.DataFrame({"SPY": 200 * np.exp(np.linspace(-0.1, 0, 101))}, index=dates)
    context = ActivePortfolioContext(owner.row["id"], {"SPY": {"shares": 10}}, 1000, 0, 0)
    change = CompareChange(
        expected_portfolio_id=context.portfolio_id, ticker="SPY", amount=500, proceeds="cash"
    )
    result = copilot_compare.compare_change(context, change, prices, {}, now=now)
    receipt = comparison_replay.issue_receipt(
        owner.user,
        context,
        prices,
        [],
        {},
        result,
        portfolio_revision=owner.row["comparison_revision"],
    )
    body = {
        "expected_portfolio_id": context.portfolio_id,
        "confirmed": True,
        "receipt": receipt.model_dump(mode="json"),
    }
    return result, body


def save(stack, owner, result, body):
    return requests.post(
        f"{stack.base}/api/v1/copilot/compare-change/{result.result_id}/confirm",
        headers=owner.headers,
        json=body,
        timeout=30,
    )


def test_real_login_http_save_retry_read_and_holdings_unchanged(stack, account):
    owner = account()
    result, body = capture(owner)
    first = save(stack, owner, result, body)
    assert first.status_code == 200, first.json().get("error")
    second = save(stack, owner, result, body)
    assert second.status_code == 200
    assert first.json()["data"] == second.json()["data"]
    url = f"{stack.base}/api/v1/copilot/compare-change/{result.result_id}/saved"
    read = requests.get(
        url, headers=owner.headers, params={"expected_portfolio_id": owner.row["id"]}, timeout=15
    )
    assert read.status_code == 200
    assert read.json()["data"]["result"] == result.model_dump(mode="json")
    rows = requests.get(stack.url + "/rest/v1/portfolios", headers=owner.headers, timeout=15)
    assert rows.json() == [owner.row]
    plans = requests.get(stack.url + "/rest/v1/risk_plans", headers=owner.headers, timeout=15)
    assert len(plans.json()) == 1


def test_real_rls_isolation_tamper_and_immutable_evidence(stack, account):
    owner, other = account(), account()
    result, body = capture(owner)
    assert save(stack, other, result, body).status_code in (403, 409)
    altered = {**body, "receipt": {**body["receipt"], "signature": "0" * 64}}
    assert save(stack, owner, result, altered).status_code in (400, 409)
    assert save(stack, owner, result, body).status_code == 200
    records = stack.url + "/rest/v1/comparison_confirmations"
    read = requests.get(records, headers=other.headers, timeout=15)
    assert read.status_code == 200 and read.json() == []
    scoped_read = requests.get(
        f"{stack.base}/api/v1/copilot/compare-change/{result.result_id}/saved",
        headers=other.headers,
        params={"expected_portfolio_id": owner.row["id"]},
        timeout=15,
    )
    assert scoped_read.status_code == 404
    update = requests.patch(
        records,
        headers=owner.headers,
        params={"plan_id": f"eq.{result.result_id}"},
        json={"record": "forged"},
        timeout=15,
    )
    assert update.status_code == 403
    anon = requests.get(records, headers={"apikey": stack.keys["ANON_KEY"]}, timeout=15)
    assert anon.status_code in (401, 403)


def test_real_postgrest_revision_rejects_edit_restore_and_no_partial_plan(stack, account):
    owner = account()
    result, body = capture(owner)
    for cash in (2000, 1000):
        response = requests.patch(
            stack.url + "/rest/v1/portfolios",
            headers=owner.headers,
            params={"id": "eq." + owner.row["id"]},
            json={"cash_balance": cash},
            timeout=15,
        )
        assert response.status_code == 200
    assert save(stack, owner, result, body).status_code == 409
    plans = requests.get(stack.url + "/rest/v1/risk_plans", headers=owner.headers, timeout=15)
    assert plans.status_code == 200 and plans.json() == []


def test_real_http_requires_jwt_and_explicit_boolean_consent(stack, account):
    owner = account()
    result, body = capture(owner)
    assert save(stack, owner, result, {**body, "confirmed": False}).status_code == 422
    assert save(stack, owner, result, {**body, "confirmed": "true"}).status_code == 422
    url = f"{stack.base}/api/v1/copilot/compare-change/{result.result_id}/confirm"
    assert requests.post(url, json=body, timeout=15).status_code == 401


def test_job_renewal_listing_cancel_and_cleanup_with_real_jwt(stack, account):
    from backend.app.core.deps_auth import AuthedUser
    from backend.app.schemas.copilot_candidates import CandidateRequest
    from backend.app.schemas.copilot_runs import RunSnapshot
    from backend.app.services import copilot_jobs as jobs

    owner, other = account(), account()
    token = owner.headers["Authorization"].removeprefix("Bearer ")
    log = jobs.journal(AuthedUser(id=owner.user, email=None, raw_claims={}, access_token=token))
    task = CandidateRequest(
        expected_portfolio_id=owner.row["id"], goal="increase_cash", amount=500.0, confirmed=True
    )
    snapshot = RunSnapshot(
        portfolio_id=owner.row["id"],
        holdings={"SPY": {"shares": 10}},
        cash_balance=1000,
        margin_loan=0,
        contributed_capital=0,
        risk_preference=3,
        preference_source="neutral_baseline",
    )
    record = log.reserve(str(uuid4()), task, snapshot, owner.row["comparison_revision"])
    id = str(record.id)
    claimed = log.claim(id)
    assert claimed is not None
    renewed = log.renew(id, claimed.revision, "evaluating")
    assert renewed and renewed.execution_deadline == claimed.execution_deadline
    assert log.renew(id, claimed.revision) is None
    endpoint = stack.base + "/api/v1/copilot/decision-runs"
    query = {"expected_portfolio_id": owner.row["id"]}
    response = requests.get(endpoint, headers=owner.headers, params=query, timeout=15)
    assert response.status_code == 200
    assert [r["id"] for r in response.json()["data"]["runs"]] == [id]
    response = requests.get(endpoint, headers=other.headers, params=query, timeout=15)
    assert response.status_code == 200 and response.json()["data"]["runs"] == []
    response = requests.post(endpoint + "/" + id + "/cancel", headers=owner.headers, timeout=15)
    assert response.status_code == 200
    assert log.publish(id, renewed.revision, error_code="analysis_failed").state == "cancelled"
    stack.sql(f"update copilot_runs set created_at=now()-interval '2 days' where id='{id}';")
    response = requests.post(endpoint + "/recover", headers=owner.headers, json=query, timeout=15)
    assert response.status_code == 200
    assert response.json()["data"]["removed"] == 1
    assert response.json()["data"]["dispatched"] == 0


def test_real_put_capture_save_retry_list_and_review(stack, account):
    from datetime import timedelta

    from backend.tests.test_copilot_put import request as put_request

    owner, other = account(), account()
    body = put_request(
        expected_portfolio_id=owner.row["id"],
        expiry=datetime.now(timezone.utc).date() + timedelta(days=30),
    ).model_dump(mode="json")
    endpoint = stack.base + "/api/v1/copilot"
    calc = requests.post(
        endpoint + "/cash-secured-put", headers=owner.headers, json=body, timeout=15
    )
    assert calc.status_code == 200
    result = calc.json()["data"]
    assert result["receipt"]["save_available"]
    payload = {
        "expected_portfolio_id": owner.row["id"],
        "confirmed": True,
        "receipt": result["receipt"],
    }
    path = endpoint + "/put-plans/" + result["result_id"] + "/confirm"
    saved = requests.post(path, headers=owner.headers, json=payload, timeout=15)
    assert saved.status_code == 200
    retry = requests.post(path, headers=owner.headers, json=payload, timeout=15)
    assert retry.json()["data"] == saved.json()["data"]
    query = {"expected_portfolio_id": owner.row["id"]}
    listing = requests.get(endpoint + "/put-plans", headers=owner.headers, params=query, timeout=15)
    assert [p["plan_id"] for p in listing.json()["data"]] == [result["result_id"]]
    assert (
        requests.get(
            endpoint + "/put-plans", headers=other.headers, params=query, timeout=15
        ).json()["data"]
        == []
    )
    # Editable RiskPlan descriptions cannot replace the signed calculation.
    edited = requests.patch(
        stack.url + "/rest/v1/risk_plans?id=eq." + result["result_id"],
        headers=owner.headers,
        json={"expected_impact": {"fake_profit": 999999}},
        timeout=15,
    )
    assert edited.status_code in (200, 204)
    review_url = endpoint + "/put-plans/" + result["result_id"] + "/review"
    reviewed = requests.post(review_url, headers=owner.headers, json=query, timeout=15)
    assert (
        reviewed.status_code == 200
        and reviewed.json()["data"]["verdict"] == "assumptions_need_confirmation"
    )
    requests.patch(
        stack.url + "/rest/v1/portfolios?id=eq." + owner.row["id"],
        headers=owner.headers,
        json={"cash_balance": 1200},
        timeout=15,
    ).raise_for_status()
    changed = requests.post(review_url, headers=owner.headers, json=query, timeout=15)
    assert changed.json()["data"]["verdict"] == "requires_recalculation"
    assert "cash_balance" in changed.json()["data"]["changed_fields"]
    retry = requests.post(path, headers=owner.headers, json=payload, timeout=15)
    assert retry.json()["data"] == saved.json()["data"]


@pytest.mark.parametrize("dispatch", ["submit", "recover_persisted"])
def test_real_background_computation_is_idempotent_and_preserves_account(stack, account, dispatch):
    owner, other = account(), account()
    endpoint = stack.base + "/api/v1/copilot/decision-runs"
    body = {
        "id": str(uuid4()),
        "task": {
            "expected_portfolio_id": owner.row["id"],
            "goal": "increase_cash",
            "amount": 500.0,
            "protected_holdings": [],
            "confirmed": True,
        },
    }
    if dispatch == "recover_persisted":
        from dataclasses import asdict

        from backend.app.core.deps_auth import AuthedUser
        from backend.app.schemas.copilot_candidates import CandidateRequest
        from backend.app.schemas.copilot_runs import RunSnapshot
        from backend.app.services import copilot_jobs as jobs
        from libs.auth.active_portfolio import get_active_portfolio_context

        user = AuthedUser(
            id=owner.user,
            email=None,
            raw_claims={},
            access_token=owner.headers["Authorization"].removeprefix("Bearer "),
        )
        # Persist without submitting to any process queue: models loss of the
        # in-memory queue before dispatch. Recovery still requires the owner's JWT.
        jobs.journal(user).reserve(
            body["id"],
            CandidateRequest(**body["task"]),
            RunSnapshot(
                **asdict(get_active_portfolio_context(access_token=user.access_token)),
                risk_preference=3,
                preference_source="neutral_baseline",
            ),
            owner.row["comparison_revision"],
        )
        started = requests.post(
            endpoint + "/recover",
            headers=owner.headers,
            json={"expected_portfolio_id": owner.row["id"]},
            timeout=15,
        )
        assert started.status_code == 200, started.text
        assert started.json()["data"]["dispatched"] == 1
    else:
        started = requests.post(endpoint, headers=owner.headers, json=body, timeout=15)
    assert started.status_code == 200, started.text
    path = endpoint + "/" + body["id"]
    for _ in range(100):
        response = requests.get(path, headers=owner.headers, timeout=15)
        assert response.status_code == 200
        run = response.json()["data"]
        if run["state"] not in ("queued", "running"):
            break
        time.sleep(0.2)
    assert run["state"] == "completed", run
    assert run["attempts"] == 1 and run["step"] == "done"
    result = run["result"]
    assert result["portfolio_id"] == owner.row["id"]
    assert result["coverage"] == "evaluated"
    assert result["baseline"]["cash"] == 1000
    assert len(result["candidates"]) == 1
    candidate = result["candidates"][0]
    assert candidate["candidate"]["cash"] == 1500
    assert candidate["baseline"] == result["baseline"]
    assert candidate["replay_receipt"]["save_available"]
    confirmation = requests.post(
        stack.base + "/api/v1/copilot/compare-change/" + candidate["result_id"] + "/confirm",
        headers=owner.headers,
        json={
            "expected_portfolio_id": owner.row["id"],
            "confirmed": True,
            "receipt": candidate["replay_receipt"],
        },
        timeout=30,
    )
    assert confirmation.status_code == 200, confirmation.text
    from datetime import timedelta

    from backend.tests.test_copilot_put import request as put_request

    put = requests.post(
        stack.base + "/api/v1/copilot/cash-secured-put",
        headers=owner.headers,
        json=put_request(
            expected_portfolio_id=owner.row["id"],
            expiry=datetime.now(timezone.utc).date() + timedelta(days=30),
        ).model_dump(mode="json"),
        timeout=15,
    )
    assert put.status_code == 200
    assert put.json()["data"]["recorded_cash"] == 1000
    assert put.json()["data"]["funding_status"] == "insufficient_cash"
    assert put.json()["data"]["pre_trade_funding_gap"] == 10000
    repeated = requests.post(endpoint, headers=owner.headers, json=body, timeout=15)
    assert repeated.status_code == 200
    assert repeated.json()["data"] == run
    assert requests.get(path, headers=other.headers, timeout=15).status_code == 404
    actual = requests.get(
        stack.url + "/rest/v1/portfolios",
        headers=owner.headers,
        params={"id": "eq." + owner.row["id"], "select": "*"},
        timeout=15,
    ).json()[0]
    for field in ("holdings", "cash_balance", "margin_loan", "comparison_revision"):
        assert actual[field] == owner.row[field]


def test_running_worker_survives_process_loss_after_real_lease_expiry(stack, account):
    from backend.app.core.deps_auth import AuthedUser
    from backend.app.services import copilot_jobs as jobs

    owner = account()
    endpoint = stack.base + "/api/v1/copilot/decision-runs"
    run_id = str(uuid4())
    body = {
        "id": run_id,
        "task": {
            "expected_portfolio_id": owner.row["id"],
            "goal": "increase_cash",
            "amount": 500.0,
            "confirmed": True,
        },
    }
    query = {"expected_portfolio_id": owner.row["id"]}
    path = endpoint + "/" + run_id
    (stack.control / "entered").unlink(missing_ok=True)
    (stack.control / "hold").touch()
    try:
        started = requests.post(endpoint, headers=owner.headers, json=body, timeout=15)
        assert started.status_code == 200
        for _ in range(100):
            if (stack.control / "entered").exists():
                break
            time.sleep(0.1)
        assert (stack.control / "entered").exists(), "Worker never reached market capture"
        before = requests.get(path, headers=owner.headers, timeout=15).json()["data"]
        assert before["state"] == "running" and before["step"] == "capturing"
        assert before["attempts"] == 1 and before["result"] is None
        # SIGKILL the owned application, without its graceful shutdown handler.
        # Keep production's 120-second lease and database clock unchanged.
        stack.crash_restart()
        early = requests.post(endpoint + "/recover", headers=owner.headers, json=query, timeout=15)
        assert early.status_code == 200
        assert early.json()["data"]["dispatched"] == 0
        deadline = time.monotonic() + 140
        while time.monotonic() < deadline:
            current = requests.get(path, headers=owner.headers, timeout=15).json()["data"]
            if current["state"] == "interrupted":
                break
            assert current["state"] == "running" and current["attempts"] == 1
            time.sleep(1)
        assert current["state"] == "interrupted"
        assert current["error_code"] == "execution_expired"
        assert current["result"] is None
        assert requests.post(endpoint + "/recover", json=query, timeout=15).status_code == 401
        recovered = requests.post(
            endpoint + "/recover", headers=owner.headers, json=query, timeout=15
        )
        assert recovered.status_code == 200
        assert recovered.json()["data"]["dispatched"] == 1
        for _ in range(100):
            final = requests.get(path, headers=owner.headers, timeout=15).json()["data"]
            if final["state"] not in ("queued", "running"):
                break
            time.sleep(0.2)
        assert final["state"] == "completed", final
        assert final["attempts"] == 2
        assert final["result"]["baseline"]["cash"] == 1000
        assert final["result"]["candidates"][0]["candidate"]["cash"] == 1500
        # A stale publication from the first attempt cannot replace this result.
        user = AuthedUser(
            id=owner.user,
            email=None,
            raw_claims={},
            access_token=owner.headers["Authorization"].removeprefix("Bearer "),
        )
        stale = jobs.journal(user).publish(run_id, before["revision"], error_code="analysis_failed")
        assert stale.public().model_dump(mode="json") == final
        again = requests.post(endpoint + "/recover", headers=owner.headers, json=query, timeout=15)
        assert again.status_code == 200 and again.json()["data"]["dispatched"] == 0
        assert requests.get(path, headers=owner.headers, timeout=15).json()["data"] == final
    finally:
        (stack.control / "hold").unlink(missing_ok=True)


def test_two_instances_claim_once_under_repeated_concurrent_submission(stack, account):
    from concurrent.futures import ThreadPoolExecutor

    owner = account()
    captures = stack.control / "captures"
    initial_captures = len(captures.read_text().splitlines()) if captures.exists() else 0
    with stack.peer() as peer:
        endpoints = [base + "/api/v1/copilot/decision-runs" for base in (stack.base, peer)]
        for round_index in range(3):
            body = {
                "id": str(uuid4()),
                "task": {
                    "expected_portfolio_id": owner.row["id"],
                    "goal": "increase_cash",
                    "amount": 500.0,
                    "confirmed": True,
                },
            }
            (stack.control / "entered").unlink(missing_ok=True)
            (stack.control / "hold").touch()
            try:
                with ThreadPoolExecutor(max_workers=8) as pool:
                    responses = list(
                        pool.map(
                            lambda i: requests.post(
                                endpoints[i % 2], headers=owner.headers, json=body, timeout=30
                            ),
                            range(8),
                        )
                    )
                assert all(r.status_code == 200 for r in responses), [
                    r.status_code for r in responses
                ]
                for _ in range(100):
                    if (stack.control / "entered").exists():
                        break
                    time.sleep(0.1)
                assert (stack.control / "entered").exists()
                # Repeated recovery on both processes must not claim an active lease.
                for endpoint in endpoints:
                    response = requests.post(
                        endpoint + "/recover",
                        headers=owner.headers,
                        json={"expected_portfolio_id": owner.row["id"]},
                        timeout=15,
                    )
                    assert response.status_code == 200
                    assert response.json()["data"]["dispatched"] == 0
                assert len(captures.read_text().splitlines()) == initial_captures + round_index + 1
            finally:
                (stack.control / "hold").unlink(missing_ok=True)
            for _ in range(100):
                final = requests.get(
                    endpoints[0] + "/" + body["id"], headers=owner.headers, timeout=15
                ).json()["data"]
                if final["state"] not in ("queued", "running"):
                    break
                time.sleep(0.2)
            assert final["state"] == "completed", final
            assert final["attempts"] == 1
            assert final["result"]["candidates"][0]["candidate"]["cash"] == 1500
            for endpoint in endpoints:
                repeated = requests.post(endpoint, headers=owner.headers, json=body, timeout=15)
                assert repeated.status_code == 200 and repeated.json()["data"] == final
        assert len(captures.read_text().splitlines()) == initial_captures + 3


def test_two_instance_burst_drains_durable_jobs_beyond_memory_capacity(stack, account):
    from concurrent.futures import ThreadPoolExecutor

    owner = account()
    captures = stack.control / "captures"
    initial = len(captures.read_text().splitlines()) if captures.exists() else 0
    bodies = [
        {
            "id": str(uuid4()),
            "task": {
                "expected_portfolio_id": owner.row["id"],
                "goal": "increase_cash",
                "amount": 500.0,
                "confirmed": True,
            },
        }
        for _ in range(12)
    ]
    with stack.peer() as peer:
        endpoints = [base + "/api/v1/copilot/decision-runs" for base in (stack.base, peer)]
        (stack.control / "hold").touch()
        try:
            with ThreadPoolExecutor(max_workers=12) as pool:
                responses = list(
                    pool.map(
                        lambda i: requests.post(
                            endpoints[i % 2], headers=owner.headers, json=bodies[i], timeout=30
                        ),
                        range(12),
                    )
                )
            assert all(r.status_code == 200 for r in responses), [r.status_code for r in responses]
            listing = requests.get(
                endpoints[0],
                headers=owner.headers,
                params={"expected_portfolio_id": owner.row["id"]},
                timeout=15,
            ).json()["data"]["runs"]
            assert {r["id"] for r in listing} == {b["id"] for b in bodies}
            assert all(r["state"] in ("queued", "running") for r in listing)
            assert sum(r["state"] == "queued" for r in listing) >= 10
        finally:
            (stack.control / "hold").unlink(missing_ok=True)
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            listing = requests.get(
                endpoints[0],
                headers=owner.headers,
                params={"expected_portfolio_id": owner.row["id"]},
                timeout=15,
            ).json()["data"]["runs"]
            if all(r["state"] == "completed" for r in listing):
                break
            assert all(r["state"] in ("queued", "running", "completed") for r in listing)
            time.sleep(0.5)
        assert len(listing) == 12 and all(r["state"] == "completed" for r in listing)
        assert all(r["attempts"] == 1 for r in listing)
        assert len({r["result"]["snapshot_id"] for r in listing}) == 12
        assert len(captures.read_text().splitlines()) == initial + 12
