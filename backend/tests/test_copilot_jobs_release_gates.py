"""Release-gate checks for the decision-support routes: flags off, no key, drain.

Production ships every new flag at ``false`` and (until an operator provisions
it) no ``MINDMARKET_RISK_RUN_SIGNING_SECRET``. Every new route must then answer
with a deliberate status -- 503 (disabled / not configured), 404, 409 or 422 --
never a 200 that pretends the feature exists and never a 500 that pages Sentry
on every probe. The matrix below is the full new surface; a route added later
without a gate shows up here as a 200 or a 500.
"""

from uuid import uuid4

import pytest

from backend.app.core.config import reset_settings_cache
from backend.tests.test_copilot_candidates import task
from backend.tests.test_copilot_jobs import USER
from backend.tests.test_copilot_put import request as put_request

FLAGS = (
    "MINDMARKET_DECISION_SUPPORT_ENABLED",
    "MINDMARKET_ASYNC_ANALYSIS_ENABLED",
    "MINDMARKET_CASH_SECURED_PUT_ENABLED",
    "MINDMARKET_CASH_SECURED_PUT_SAVE_ENABLED",
    "MINDMARKET_FUNDING_SCENARIOS_ENABLED",
    "MINDMARKET_FUNDING_SCENARIOS_SAVE_ENABLED",
)
RID = str(uuid4())
RECEIPT = {"record": "{}", "signature": "a" * 64, "save_available": True}
PUT = put_request().model_dump(mode="json")
BOOK = PUT["expected_portfolio_id"]
TASK = task().model_dump(mode="json")
FUNDING = {
    "expected_portfolio_id": BOOK,
    "source_result_id": RID,
    "receipt": RECEIPT,
    "put": PUT,
    "sale_fees": 10.0,
    "confirmed": True,
}
# (method, path, json body) -- every route the branch adds under /api/v1/copilot.
ROUTES = [
    ("GET", f"/api/v1/copilot/decision-runs?expected_portfolio_id={BOOK}", None),
    ("POST", "/api/v1/copilot/decision-runs", {"id": RID, "task": TASK}),
    ("POST", "/api/v1/copilot/decision-runs/recover", {"expected_portfolio_id": BOOK}),
    ("GET", f"/api/v1/copilot/decision-runs/{RID}", None),
    ("POST", f"/api/v1/copilot/decision-runs/{RID}/resume", None),
    ("POST", f"/api/v1/copilot/decision-runs/{RID}/cancel", None),
    ("POST", "/api/v1/copilot/cash-secured-put", PUT),
    (
        "POST",
        f"/api/v1/copilot/put-plans/{RID}/confirm",
        {"expected_portfolio_id": BOOK, "confirmed": True, "receipt": RECEIPT},
    ),
    ("GET", f"/api/v1/copilot/put-plans?expected_portfolio_id={BOOK}", None),
    ("GET", f"/api/v1/copilot/put-plans/history?expected_portfolio_id={BOOK}", None),
    ("POST", f"/api/v1/copilot/put-plans/{RID}/review", {"expected_portfolio_id": BOOK}),
    ("POST", "/api/v1/copilot/funding-scenarios", FUNDING),
    (
        "POST",
        f"/api/v1/copilot/funding-plans/{RID}/confirm",
        {"expected_portfolio_id": BOOK, "confirmed": True, "receipt": RECEIPT},
    ),
    ("GET", f"/api/v1/copilot/funding-plans/{RID}?expected_portfolio_id={BOOK}", None),
    ("POST", f"/api/v1/copilot/funding-plans/{RID}/review", {"expected_portfolio_id": BOOK}),
    (
        "POST",
        "/api/v1/copilot/task-state/confirm",
        {
            "task_state": {"record": "{}", "signature": "a" * 64},
            "expected_portfolio_id": BOOK,
            "goal": "increase_cash",
            "amount": 500.0,
            "protected_holdings": [],
            "run_id": RID,
            "confirmed": True,
        },
    ),
    (
        "POST",
        "/api/v1/copilot/task-state/resume",
        {"task_state": {"record": "{}", "signature": "a" * 64}, "expected_portfolio_id": BOOK},
    ),
]


def _call(client, method, path, body, headers):
    if method == "GET":
        return client.get(path, headers=headers)
    return client.post(path, json=body, headers=headers)


@pytest.fixture
def storage_attempts(monkeypatch):
    """Count attempts to open a database client. A raise would be the wrong
    sentinel: RunStore.__init__ catches Exception and answers 503, so an
    AssertionError there would be swallowed and the test would pass while
    storage was in fact reached."""
    from libs.auth import client as supabase_client

    calls = []

    def record(*args, **kwargs):
        calls.append((args, kwargs))
        raise RuntimeError("no database in this test")

    monkeypatch.setattr(supabase_client, "get_supabase", record)
    return calls


@pytest.mark.parametrize("secret", ["", "k" * 32], ids=["no-signing-key", "key-present"])
@pytest.mark.parametrize(
    "method,path,body", ROUTES, ids=[f"{m} {p.split('?')[0]}" for m, p, _ in ROUTES]
)
def test_every_new_route_answers_deliberately_when_flags_are_off(
    test_client, mint_token, monkeypatch, storage_attempts, secret, method, path, body
):
    for flag in FLAGS:
        monkeypatch.setenv(flag, "false")
    monkeypatch.setenv("MINDMARKET_RISK_RUN_SIGNING_SECRET", secret)
    reset_settings_cache()
    headers = {"Authorization": f"Bearer {mint_token(sub=USER)}"}

    assert _call(test_client, method, path, body, None).status_code == 401, "auth gate first"
    response = _call(test_client, method, path, body, headers)
    assert response.status_code not in (200, 500), (method, path, response.status_code)
    assert response.status_code in (404, 409, 503), (method, path, response.status_code)
    envelope = response.json()
    assert envelope["data"] is None and envelope["error"]["code"], envelope
    # The bodies above validate, so a 422 would mean validation -- not the
    # feature gate -- produced the refusal, and the gate itself went untested.
    assert envelope["error"]["code"] != "validation_failed", envelope
    # Flags off + no key is a pure configuration answer; the database is never
    # opened for it. (Key present + flags off keeps stored reads/cancel
    # reachable by design -- see api/v1/copilot_jobs.read -- so storage may be
    # touched in that case for the id-addressed routes only.)
    if not secret:
        assert storage_attempts == [], (method, path, "opened storage without a signing key")


def test_app_lifespan_owns_the_dispatcher_and_drains_it_on_shutdown(monkeypatch):
    """Deploys stop the container (SIGTERM -> uvicorn lifespan shutdown). The
    worker must stop claiming, drop the in-memory JWTs it was holding, and leave
    the durable record exactly as it was -- ``queued`` -- so an explicit,
    re-authenticated recovery can pick it up on the new version."""
    from types import SimpleNamespace

    from fastapi.testclient import TestClient

    from backend.app.main import create_app
    from backend.app.services import copilot_jobs as jobs

    monkeypatch.setenv("MINDMARKET_ENV", "dev")
    reset_settings_cache()
    app = create_app()
    with TestClient(app):
        dispatcher = app.state.copilot_dispatcher
        assert isinstance(dispatcher, jobs.Dispatcher)
        dispatcher.started = True  # no worker thread: the queued-only case
        user = SimpleNamespace(id=USER, access_token="jwt-that-must-not-outlive-shutdown")
        assert dispatcher.submit(user, "job-1")
        assert dispatcher.pending == {(USER, "job-1")}
    # Lifespan exit ran Dispatcher.shutdown().
    assert dispatcher.stopping.is_set()
    assert dispatcher.queue.empty() and dispatcher.pending == set()
    assert not dispatcher.submit(user, "job-2"), "a draining dispatcher refuses new work"
    # Nothing that could be persisted or re-dispatched later holds the token.
    assert all(
        "jwt-that-must-not-outlive-shutdown" not in repr(v) for v in vars(dispatcher).values()
    )


def test_worker_stops_waiting_for_capacity_on_shutdown_without_claiming(monkeypatch):
    """The lane may be held by a foreground analysis for up to 120s. A shutdown
    during that wait must return within the poll interval and never claim."""
    import time
    from threading import Event, Thread
    from types import SimpleNamespace
    from unittest.mock import Mock

    from backend.app.api.v1 import risk
    from backend.app.core import deps_auth
    from backend.app.services import copilot_jobs as jobs

    monkeypatch.setattr(deps_auth, "_decode", lambda *args: {})
    journal = Mock()
    monkeypatch.setattr(jobs, "journal", journal)
    assert risk._check_capacity.acquire(blocking=False), "test needs the lane"
    shutdown = Event()
    try:
        worker = Thread(
            target=jobs.Dispatcher.run,
            args=(SimpleNamespace(id=USER, access_token="jwt"), "job", shutdown),
            daemon=True,
        )
        started = time.monotonic()
        worker.start()
        time.sleep(0.2)
        shutdown.set()
        worker.join(timeout=5)
        assert not worker.is_alive(), "worker kept waiting for the lane after shutdown"
        assert time.monotonic() - started < 5
    finally:
        risk._check_capacity.release()
    journal.assert_not_called()
    # The lane was never taken by the worker: it is free again exactly once.
    assert risk._check_capacity.acquire(blocking=False)
    risk._check_capacity.release()


# Every route that needs the signing secret once its feature is ON, plus the
# pre-existing compare-change, whose receipts the funding flow consumes.
COMPARE = (
    "POST",
    "/api/v1/copilot/compare-change",
    {"expected_portfolio_id": BOOK, "ticker": "SPY", "amount": 1000, "proceeds": "cash"},
)
SIGNED_ROUTES = [*ROUTES, COMPARE]
ON_FLAGS = (
    *FLAGS,
    "MINDMARKET_COMPARISON_REPLAY_ENABLED",
    "MINDMARKET_COMPARISON_SAVE_ENABLED",
)


class _LaneSpy:
    """Stands in for the one process-wide analysis lane and records every
    attempt to take it. A configuration refusal must come first."""

    def __init__(self):
        self.acquired = 0

    def acquire(self, blocking=True):
        self.acquired += 1
        return True

    def release(self):
        pass


@pytest.mark.parametrize("secret", ["", "k" * 31], ids=["absent", "too-short"])
@pytest.mark.parametrize(
    "method,path,body", SIGNED_ROUTES, ids=[f"{m} {p.split('?')[0]}" for m, p, _ in SIGNED_ROUTES]
)
def test_flags_on_without_a_usable_signing_key_refuse_before_lane_and_storage(
    test_client, mint_token, monkeypatch, storage_attempts, secret, method, path, body
):
    from backend.app.api.v1 import risk

    for flag in ON_FLAGS:
        monkeypatch.setenv(flag, "true")
    monkeypatch.setenv("MINDMARKET_RISK_RUN_SIGNING_SECRET", secret)
    reset_settings_cache()
    lane = _LaneSpy()
    monkeypatch.setattr(risk, "_check_capacity", lane)
    headers = {"Authorization": f"Bearer {mint_token(sub=USER)}"}

    response = _call(test_client, method, path, body, headers)
    envelope = response.json()
    assert response.status_code == 503, (method, path, response.status_code, envelope)
    assert envelope["data"] is None
    assert envelope["error"]["code"] in {
        "jobs_unavailable",
        "put_signing_unavailable",
        "plan_signing_unavailable",
        "comparison_replay_unavailable",
    }, envelope
    assert lane.acquired == 0, (method, path, "took the analysis lane before the key gate")
    assert storage_attempts == [], (method, path, "opened storage without a usable key")


def test_funding_scenarios_checks_save_signing_before_the_lane(
    test_client, mint_token, monkeypatch, storage_attempts
):
    """Today the replay receipt and the funding-save receipt share one root
    secret, so the replay gate happens to refuse first. Pin the ORDER anyway:
    if the save gate refuses, no receipt is read and the lane is untouched."""
    from backend.app.api.v1 import risk
    from backend.app.core.responses import APIError
    from backend.app.services import comparison_replay, funding_plans

    for flag in ON_FLAGS:
        monkeypatch.setenv(flag, "true")
    monkeypatch.setenv("MINDMARKET_RISK_RUN_SIGNING_SECRET", "k" * 32)
    reset_settings_cache()
    lane = _LaneSpy()
    monkeypatch.setattr(risk, "_check_capacity", lane)

    def refuse():
        raise APIError(503, "plan_signing_unavailable", "Plan verification is not configured.")

    reads = []
    monkeypatch.setattr(funding_plans, "require_enabled", refuse)
    monkeypatch.setattr(comparison_replay, "read_receipt", lambda *a, **k: reads.append(a))
    headers = {"Authorization": f"Bearer {mint_token(sub=USER)}"}
    response = test_client.post("/api/v1/copilot/funding-scenarios", json=FUNDING, headers=headers)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "plan_signing_unavailable"
    assert reads == [] and lane.acquired == 0 and storage_attempts == []


@pytest.mark.parametrize(
    "enabled",
    ["MINDMARKET_COMPARISON_REPLAY_ENABLED", "MINDMARKET_COMPARISON_SAVE_ENABLED"],
    ids=["replay-only", "save-only"],
)
def test_compare_change_checks_each_signing_feature_before_the_lane(
    test_client, mint_token, monkeypatch, storage_attempts, enabled
):
    """Each flag that makes compare-change sign a receipt is gated on its own;
    the save gate must not be the only thing protecting the replay case."""
    from backend.app.api.v1 import risk

    for flag in ON_FLAGS:
        monkeypatch.setenv(flag, "false")
    monkeypatch.setenv(enabled, "true")
    if enabled.endswith("SAVE_ENABLED"):
        # Saving requires replay receipts; only the key is missing.
        monkeypatch.setenv("MINDMARKET_COMPARISON_REPLAY_ENABLED", "true")
    monkeypatch.setenv("MINDMARKET_RISK_RUN_SIGNING_SECRET", "")
    reset_settings_cache()
    lane = _LaneSpy()
    monkeypatch.setattr(risk, "_check_capacity", lane)
    method, path, body = COMPARE
    response = _call(
        test_client, method, path, body, {"Authorization": f"Bearer {mint_token(sub=USER)}"}
    )
    assert response.status_code == 503, response.json()
    assert lane.acquired == 0 and storage_attempts == []
