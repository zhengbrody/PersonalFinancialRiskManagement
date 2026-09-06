"""Run provenance/state contracts; hermetic stores are NOT a live RLS proof."""

import copy
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from backend.app.core.responses import APIError
from backend.app.schemas.copilot_runs import RunSnapshot
from backend.app.schemas.risk_check import RiskCheck
from backend.app.services import copilot_runs as runs

USER = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"
BOOK = "33333333-3333-4333-8333-333333333333"
RUN = "44444444-4444-4444-8444-444444444444"
KEY = b"test-run-key-independent-32-bytes-long"
NOW = datetime(2026, 9, 6, tzinfo=timezone.utc)


class MemoryStore:
    def __init__(self):
        self.rows = {}
        self.on_replace = None

    def get(self, run_id):
        return copy.deepcopy(self.rows.get(run_id))

    def reserve(self, row):
        if row["id"] in self.rows:
            return False
        self.rows[row["id"]] = copy.deepcopy(row)
        return True

    def replace(self, old, new):
        if self.on_replace:
            callback, self.on_replace = self.on_replace, None
            callback()
        actual = self.rows.get(old["id"])
        if not actual or actual["signature"] != old["signature"] or actual["state"] != "running":
            return False
        self.rows[new["id"]] = copy.deepcopy(new)
        return True


@pytest.fixture
def snapshot():
    return RunSnapshot(
        portfolio_id=BOOK,
        holdings={"SPY": {"shares": 2}},
        cash_balance=100,
        margin_loan=0,
        contributed_capital=1000,
        risk_preference=3,
        preference_source="neutral_baseline",
    )


@pytest.fixture
def check():
    return RiskCheck(
        portfolio_id=BOOK,
        result_id=RUN,
        computed_at=NOW.isoformat(),
        status="limited",
        summary="Coverage first.",
    )


@pytest.fixture
def journal():
    return runs.RunJournal(MemoryStore(), KEY, USER, clock=lambda: NOW)


def test_reserved_snapshot_is_independent_and_duplicate_does_not_replace(journal, snapshot):
    record, inserted = journal.reserve(RUN, snapshot)
    snapshot.holdings["SPY"]["shares"] = 999
    restored, second = journal.reserve(RUN, snapshot)
    assert inserted and not second
    assert restored.snapshot.holdings["SPY"]["shares"] == 2
    assert restored.public().model_dump().keys() == {
        "id",
        "portfolio_id",
        "state",
        "created_at",
        "expires_at",
        "updated_at",
        "result",
        "error_code",
    }
    assert "access_token" not in journal.store.rows[RUN]["record"]


@pytest.mark.parametrize(
    "mutation", ["record", "signature", "user_id", "portfolio_id", "state", "id"]
)
def test_client_tampering_rejected(journal, snapshot, mutation):
    journal.reserve(RUN, snapshot)
    row = journal.store.rows[RUN]
    row[mutation] = row[mutation] + "tampered"
    with pytest.raises(APIError) as caught:
        journal.get(RUN)
    assert caught.value.code == "untrusted_run"


def test_signed_result_not_cross_user_or_run_reusable(journal, snapshot):
    journal.reserve(RUN, snapshot)
    row = journal.store.rows[RUN]
    for uid, rid in ((OTHER, RUN), (USER, OTHER)):
        with pytest.raises(APIError) as caught:
            runs.decode(row, KEY, uid, rid)
        assert caught.value.status == 409


def test_cancel_wins_against_late_completion(journal, snapshot, check):
    journal.reserve(RUN, snapshot)
    journal.store.on_replace = lambda: journal.cancel(RUN)
    assert journal.finish(RUN, check).state == "cancelled"
    assert journal.get(RUN).result is None
    assert journal.cancel(RUN).state == "cancelled"


def test_completion_wins_against_late_cancel(journal, snapshot, check):
    journal.reserve(RUN, snapshot)
    journal.store.on_replace = lambda: journal.finish(RUN, check)
    assert journal.cancel(RUN).state == "completed"
    assert journal.get(RUN).result == check


def test_server_restart_expires_without_recomputing(journal, snapshot, check):
    journal.reserve(RUN, snapshot)
    restarted = runs.RunJournal(journal.store, KEY, USER, clock=lambda: NOW + runs.RUN_TTL)
    assert restarted.get(RUN).state == "interrupted"
    assert restarted.finish(RUN, check).result is None
    assert restarted.get(RUN).error_code == "run_expired"


def test_failure_is_machine_code_only(journal, snapshot):
    journal.reserve(RUN, snapshot)
    record = journal.finish(RUN, None)
    assert record.state == "failed" and record.error_code == "analysis_failed"
    assert journal.cancel(RUN).state == "failed"


def test_result_scope_validated(journal, snapshot, check):
    journal.reserve(RUN, snapshot)
    with pytest.raises(ValueError):
        journal.finish(RUN, check.model_copy(update={"portfolio_id": OTHER}))
    assert journal.get(RUN).state == "running"


def test_record_size_cap_and_key_rotation(journal, snapshot):
    record, _ = journal.reserve(RUN, snapshot)
    with pytest.raises(APIError):
        runs.decode(journal.store.rows[RUN], b"a-different-independent-key-32-bytes", USER, RUN)
    record.snapshot.holdings["SPY"]["extra"] = "x" * runs.MAX_RECORD_BYTES
    with pytest.raises(APIError) as caught:
        runs.encode(record, KEY)
    assert caught.value.code == "run_too_large"


@pytest.mark.parametrize("enabled,key", [(False, KEY.decode()), (True, ""), (True, "short")])
def test_feature_fails_closed(monkeypatch, enabled, key):
    monkeypatch.setattr(
        runs,
        "get_settings",
        lambda: SimpleNamespace(copilot_runs_enabled=enabled, risk_run_signing_secret=key),
    )
    with pytest.raises(APIError) as caught:
        runs.signing_key()
    assert caught.value.status == 503


def test_feature_independent_signing_key(monkeypatch):
    monkeypatch.setattr(
        runs,
        "get_settings",
        lambda: SimpleNamespace(copilot_runs_enabled=True, risk_run_signing_secret=KEY.decode()),
    )
    assert runs.signing_key() == KEY


@pytest.fixture
def run_api(monkeypatch, journal, check):
    from backend.app.api.v1 import copilot_runs as api
    from backend.app.services.risk_profile import ResolvedRiskPreference
    from libs.auth.active_portfolio import ActivePortfolioContext

    calls = []
    context = ActivePortfolioContext(BOOK, {"SPY": {"shares": 2}}, 100, 0, 1000)
    monkeypatch.setattr(api, "_journal", lambda user: journal)
    monkeypatch.setattr(api.risk, "_resolve_active_context_or_raise", lambda user: context)
    monkeypatch.setattr(
        api.risk_profile,
        "resolve_risk_preference",
        lambda user: ResolvedRiskPreference(3, "neutral_baseline"),
    )

    def compute(body, user, **kwargs):
        calls.append(kwargs)
        context.holdings["SPY"]["shares"] = 999  # changed live book during computation
        assert kwargs["active_context"].holdings["SPY"]["shares"] == 2
        return SimpleNamespace(copilot_check=check)

    monkeypatch.setattr(api.risk, "compute_active_report", compute)
    return api, calls


def test_api_auth_and_disabled_no_storage(test_client, mint_token, monkeypatch):
    assert (
        test_client.post(
            "/api/v1/copilot/runs", json={"id": RUN, "expected_portfolio_id": BOOK}
        ).status_code
        == 401
    )
    monkeypatch.setattr(
        runs,
        "get_settings",
        lambda: SimpleNamespace(copilot_runs_enabled=False, risk_run_signing_secret=""),
    )
    response = test_client.post(
        "/api/v1/copilot/runs",
        headers={"Authorization": f"Bearer {mint_token(sub=USER)}"},
        json={"id": RUN, "expected_portfolio_id": BOOK},
    )
    assert response.status_code == 503


def test_api_idempotent_recovery_and_no_client_results(test_client, mint_token, run_api):
    _, calls = run_api
    headers = {"Authorization": f"Bearer {mint_token(sub=USER)}"}
    payload = {"id": RUN, "expected_portfolio_id": BOOK}
    for _ in range(2):
        response = test_client.post("/api/v1/copilot/runs", headers=headers, json=payload)
        assert response.status_code == 200, response.text
        assert response.json()["data"]["state"] == "completed"
    assert len(calls) == 1
    assert test_client.get(f"/api/v1/copilot/runs/{RUN}", headers=headers).json()["data"]["result"]
    assert (
        test_client.post(
            "/api/v1/copilot/runs", headers=headers, json={**payload, "result": {}}
        ).status_code
        == 422
    )
    assert (
        test_client.post(
            "/api/v1/copilot/runs",
            headers=headers,
            json={**payload, "expected_portfolio_id": OTHER},
        ).status_code
        == 409
    )


def test_api_rejects_stale_active_portfolio_before_compute(test_client, mint_token, run_api):
    _, calls = run_api
    response = test_client.post(
        "/api/v1/copilot/runs",
        headers={"Authorization": f"Bearer {mint_token(sub=USER)}"},
        json={"id": RUN, "expected_portfolio_id": OTHER},
    )
    assert response.status_code == 409 and calls == []


def test_api_failure_persisted_and_capacity_released(
    test_client, mint_token, run_api, monkeypatch, caplog
):
    api, _ = run_api

    def fail(*a, **k):
        raise RuntimeError("private holdings and token must not reach logs")

    monkeypatch.setattr(api.risk, "compute_active_report", fail)
    headers = {"Authorization": f"Bearer {mint_token(sub=USER)}"}
    response = test_client.post(
        "/api/v1/copilot/runs", headers=headers, json={"id": RUN, "expected_portfolio_id": BOOK}
    )
    assert response.json()["data"]["state"] == "failed"
    assert "private holdings" not in caplog.text
    assert api.risk._check_capacity.acquire(blocking=False)
    api.risk._check_capacity.release()


def test_api_capacity_prevents_reservation(test_client, mint_token, run_api, journal):
    api, calls = run_api
    assert api.risk._check_capacity.acquire(blocking=False)
    try:
        response = test_client.post(
            "/api/v1/copilot/runs",
            headers={"Authorization": f"Bearer {mint_token(sub=USER)}"},
            json={"id": RUN, "expected_portfolio_id": BOOK},
        )
        assert response.status_code == 429 and calls == [] and journal.store.rows == {}
    finally:
        api.risk._check_capacity.release()


def test_store_filters_owner_and_cas_and_sanitizes_failure(monkeypatch, caplog):
    from libs.auth import client

    operations = []

    class Query:
        data = []

        def __getattr__(self, name):
            def call(*args, **kwargs):
                operations.append((name, args, kwargs))
                return self

            return call

    monkeypatch.setattr(
        client, "get_supabase", lambda **kw: operations.append(("auth", kw)) or Query()
    )
    store = runs.RunStore("verified-user-jwt", USER)
    store.get(RUN)
    store.reserve({"id": RUN})
    store.replace({"id": RUN, "signature": "old"}, {"signature": "new"})
    assert ("auth", {"access_token": "verified-user-jwt"}) in operations
    assert operations.count(("eq", ("user_id", USER), {})) == 2
    assert ("eq", ("signature", "old"), {}) in operations
    assert ("eq", ("state", "running"), {}) in operations
    assert (
        "upsert",
        ({"id": RUN},),
        {"on_conflict": "id", "ignore_duplicates": True},
    ) in operations
    with pytest.raises(APIError) as caught:
        store._execute(lambda: 1 / 0)
    assert caught.value.status == 503
    assert "verified-user-jwt" not in caplog.text
