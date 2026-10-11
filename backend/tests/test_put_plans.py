from copy import deepcopy
from dataclasses import asdict, replace
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest

from backend.app.core.config import reset_settings_cache
from backend.app.core.responses import APIError
from backend.app.services import comparison_save, copilot_scope
from backend.app.services import put_plans as service
from backend.tests.test_copilot_jobs import OTHER, USER
from backend.tests.test_copilot_put import BOOK, NOW, account, request


@pytest.fixture
def capture(monkeypatch):
    monkeypatch.setenv("MINDMARKET_CASH_SECURED_PUT_SAVE_ENABLED", "true")
    monkeypatch.setenv(
        "MINDMARKET_RISK_RUN_SIGNING_SECRET", "put-plans-test-signing-key-0000000000000000"
    )
    reset_settings_cache()
    monkeypatch.setattr(service.shared, "utcnow", lambda: NOW)
    context = account()
    result = service.copilot_put.calculate(
        context, request(), copilot_scope.context_digest(asdict(context)), now=NOW
    )
    revision = uuid4()
    receipt = service.issue(USER, context, revision, result)
    rows = {}
    monkeypatch.setattr(
        comparison_save, "_existing", lambda token, user, id: deepcopy(rows.get(id))
    )

    class Client:
        def rpc(self, name, args):
            assert name == "confirm_copilot_put_plan"
            self.args = args
            return self

        def execute(self):
            proof = comparison_save.Confirmation.model_validate_json(self.args["p_record"])
            row = {
                "user_id": str(proof.user_id),
                "portfolio_id": str(proof.portfolio_id),
                "plan_id": str(proof.plan_id),
                "record": self.args["p_record"],
                "signature": self.args["p_signature"],
            }
            rows[row["plan_id"]] = row
            return SimpleNamespace(data=[row])

    monkeypatch.setattr(service, "_client", lambda token: Client())
    yield context, result, revision, receipt, rows
    reset_settings_cache()


def test_original_save_retry_and_review(capture):
    context, result, revision, receipt, rows = capture
    id = str(result.result_id)
    saved = service.confirm("jwt", USER, BOOK, id, receipt)
    assert saved.result == result and len(rows) == 1
    assert service.confirm("jwt", USER, BOOK, id, receipt) == saved and len(rows) == 1
    stored, snap, _ = service.get_saved("jwt", USER, BOOK, id)
    assert stored == saved
    review = service.review(saved, snap, context, revision, now=NOW)
    assert review.verdict == "assumptions_need_confirmation"
    assert not review.live_quote_checked and not review.holdings_changed_by_review
    changed = service.review(saved, snap, replace(context, cash_balance=1), uuid4(), now=NOW)
    assert changed.verdict == "requires_recalculation"
    assert changed.changed_fields == ["cash_balance", "portfolio_revision"]


def test_tampering_owner_and_receipt_domains_are_rejected(capture):
    _, result, _, receipt, rows = capture
    id = str(result.result_id)
    for user, proof in [
        (OTHER, receipt),
        (USER, receipt.model_copy(update={"record": receipt.record + " "})),
        (USER, receipt.model_copy(update={"signature": "a" * 64})),
    ]:
        with pytest.raises(APIError, match="authenticated"):
            service.confirm("jwt", user, BOOK, id, proof)
    assert not rows
    service.confirm("jwt", USER, BOOK, id, receipt)
    rows[id]["record"] += " "
    with pytest.raises(APIError, match="authenticated"):
        service.get_saved("jwt", USER, BOOK, id)


def test_expired_new_save_but_existing_retry_remains_readable(capture, monkeypatch):
    from datetime import timedelta

    _, result, _, receipt, rows = capture
    id = str(result.result_id)
    monkeypatch.setattr(service.shared, "utcnow", lambda: NOW + timedelta(minutes=16))
    with pytest.raises(APIError, match="expired"):
        service.confirm("jwt", USER, BOOK, id, receipt)
    assert not rows
    monkeypatch.setattr(service.shared, "utcnow", lambda: NOW)
    saved = service.confirm("jwt", USER, BOOK, id, receipt)
    monkeypatch.setattr(service.shared, "utcnow", lambda: NOW + timedelta(days=60))
    assert service.confirm("jwt", USER, BOOK, id, receipt) == saved
    _, snap, _ = service.get_saved("jwt", USER, BOOK, id)
    assert (
        "expiry_status"
        in service.review(saved, snap, account(), snap.portfolio_revision).changed_fields
    )


def test_implementation_change_requires_recalculation_but_not_historical_read(capture, monkeypatch):
    _, result, _, receipt, _ = capture
    id = str(result.result_id)
    saved = service.confirm("jwt", USER, BOOK, id, receipt)
    monkeypatch.setattr(service, "fingerprint", lambda: "new")
    assert service.get_saved("jwt", USER, BOOK, id)[0] == saved
    _, snap, _ = service.get_saved("jwt", USER, BOOK, id)
    assert (
        "implementation"
        in service.review(saved, snap, account(), snap.portfolio_revision).changed_fields
    )


def test_confirmation_is_explicit_at_api(test_client, mint_token, monkeypatch):
    guard = SimpleNamespace(confirmed=False, expected_portfolio_id=UUID(BOOK))
    spy = Mock()
    monkeypatch.setattr(service, "confirm", spy)
    response = test_client.post(
        f"/api/v1/copilot/put-plans/{uuid4()}/confirm",
        headers={"Authorization": f"Bearer {mint_token()}"},
        json={
            "confirmed": guard.confirmed,
            "expected_portfolio_id": BOOK,
            "receipt": {"record": "bad", "signature": "a" * 64, "save_available": True},
        },
    )
    assert response.status_code == 422
    spy.assert_not_called()


def test_new_save_rejects_changed_implementation(capture, monkeypatch):
    _, result, _, receipt, rows = capture
    monkeypatch.setattr(service, "fingerprint", lambda: "different")
    with pytest.raises(APIError, match="current implementation"):
        service.confirm("jwt", USER, BOOK, str(result.result_id), receipt)
    assert not rows


def test_signed_but_incorrect_calculation_fails_replay(capture):
    from backend.app.schemas.copilot_compare import ComparisonReceipt

    _, result, _, receipt, rows = capture
    snap = service.read(receipt, USER, BOOK, str(result.result_id))
    snap.result.maximum_loss += 1
    raw, signature = service.signed(snap, "receipt")
    with pytest.raises(APIError, match="reproduced"):
        service.confirm(
            "jwt",
            USER,
            BOOK,
            str(result.result_id),
            ComparisonReceipt(record=raw, signature=signature),
        )
    assert not rows


def test_revision_only_change_requires_recalculation(capture):
    context, result, _, receipt, _ = capture
    saved = service.confirm("jwt", USER, BOOK, str(result.result_id), receipt)
    _, snap, _ = service.get_saved("jwt", USER, BOOK, str(result.result_id))
    checked = service.review(saved, snap, context, uuid4(), now=NOW)
    assert checked.verdict == "requires_recalculation"
    assert checked.changed_fields == ["portfolio_revision"]


def test_history_scans_past_invalid_rows_and_binds_cursor(capture, monkeypatch):
    _, result, _, receipt, rows = capture
    service.confirm("jwt", USER, BOOK, str(result.result_id), receipt)
    valid = next(iter(rows.values()))
    records = [{**valid, "plan_id": str(UUID(int=i)), "signature": "0" * 64} for i in range(1, 22)]
    records.append(valid)
    records.sort(key=lambda row: row["plan_id"])

    class Query:
        def __init__(self):
            self.after = None

        def table(self, _):
            return self

        def select(self, _):
            return self

        def eq(self, name, value):
            assert (name, value) in [("user_id", USER), ("portfolio_id", BOOK)]
            return self

        def order(self, name):
            assert name == "plan_id"
            return self

        def gt(self, name, value):
            assert name == "plan_id"
            self.after = value
            return self

        def limit(self, count):
            assert count == 21
            return self

        def execute(self):
            return SimpleNamespace(
                data=[r for r in records if not self.after or r["plan_id"] > self.after][:21]
            )

    monkeypatch.setattr(service, "_client", lambda _: Query())
    page = service.history("jwt", USER, BOOK)
    assert not page.plans and page.skipped_records == 20 and page.next_cursor
    second = service.history("jwt", USER, BOOK, page.next_cursor)
    assert [p.plan_id for p in second.plans] == [result.result_id]
    assert second.next_cursor is None and second.skipped_records == 1
    for owner, book, cursor in [
        (OTHER, BOOK, page.next_cursor),
        (USER, str(uuid4()), page.next_cursor),
        (USER, BOOK, page.next_cursor + "a"),
    ]:
        with pytest.raises(APIError, match="Reload"):
            service.history("jwt", owner, book, cursor)


class ReadOnlyClient:
    """A PostgREST stand-in that answers SELECT chains and refuses every write.

    ``review`` endpoints promise to change nothing. The promise is cheap to
    break silently -- one extra ``.update()`` in a seam would still return 200
    -- so the proof is structural: any call that is not part of a select chain
    raises, and the raise is a *test* failure, not an APIError the handler
    could swallow into a 503.
    """

    WRITES = ("insert", "update", "upsert", "delete", "rpc")

    def __init__(self, answers):
        self.answers, self.writes, self._table = answers, [], None

    def table(self, name):
        self._table = name
        return self

    def select(self, *_):
        return self

    def eq(self, *_):
        return self

    def limit(self, *_):
        return self

    def order(self, *_):
        return self

    def execute(self):
        return SimpleNamespace(data=self.answers.get(self._table, []))

    def __getattr__(self, name):
        if name in self.WRITES:
            self.writes.append((self._table, name))
            raise AssertionError(f"review issued a write: {self._table}.{name}")
        raise AttributeError(name)


def test_review_endpoint_reads_only_and_persists_nothing(capture, monkeypatch):
    from starlette.requests import Request

    from backend.app.api.v1 import copilot_put as api
    from backend.app.schemas.put_plan import ReviewPutPlanRequest
    from libs.auth import active_portfolio

    context, result, revision, receipt, rows = capture
    plan_id = str(result.result_id)
    service.confirm("jwt", USER, BOOK, plan_id, receipt)
    stored_before = deepcopy(rows)
    revision_row = [{"comparison_revision": str(revision)}]
    client = ReadOnlyClient({"portfolios": revision_row})
    # The fixture's ``_existing`` reads the ``rows`` dict; every other database
    # seam the handler touches (portfolio_revision, risk_plans._client) goes
    # through this one strict client.
    monkeypatch.setattr(comparison_save, "_client", lambda token: client)
    monkeypatch.setattr(service, "_client", lambda token: client)
    monkeypatch.setattr(
        active_portfolio, "get_active_portfolio_context", lambda access_token: context
    )
    monkeypatch.setattr(
        copilot_scope,
        "resolve_scope",
        lambda token, expected: copilot_scope.context_digest(asdict(context)),
    )
    user = SimpleNamespace(id=USER, access_token="jwt")
    body = ReviewPutPlanRequest(expected_portfolio_id=UUID(BOOK))
    request_ = Request({"type": "http", "headers": []})

    response = api.review_plan(UUID(plan_id), body, request_, user)

    assert response.status_code == 200
    assert client.writes == []
    assert rows == stored_before


def test_commit_then_lost_response_retry_returns_the_one_saved_plan(capture, monkeypatch):
    """The database committed but the response never arrived. The user must be
    told the outcome is unknown (never "failed"), and retrying the SAME result
    must return the stored plan without a second write."""
    _, result, _, receipt, rows = capture
    id = str(result.result_id)
    real_client = service._client("jwt")
    calls = []

    class LostResponse:
        def rpc(self, name, args):
            calls.append(name)
            real_client.rpc(name, args)
            return self

        def execute(self):
            real_client.execute()  # the row IS written ...
            raise ConnectionError("socket closed before the response")  # ... reply lost

    monkeypatch.setattr(service, "_client", lambda token: LostResponse())
    with pytest.raises(APIError) as exc:
        service.confirm("jwt", USER, BOOK, id, receipt)
    assert exc.value.status == 503 and exc.value.code == "put_save_unconfirmed"
    assert "may already be saved" in exc.value.message
    assert len(rows) == 1 and len(calls) == 1

    retried = service.confirm("jwt", USER, BOOK, id, receipt)
    assert len(calls) == 1, "retry must read the committed row, not write again"
    assert len(rows) == 1 and retried.result == result
    assert service.get_saved("jwt", USER, BOOK, id)[0] == retried


def test_proof_stamped_outside_the_window_is_never_written(capture, monkeypatch):
    """Replay runs between the expiry gate and the proof timestamp. A proof
    that left the window during replay must not reach the database: a commit
    there would be unreadable forever (verify_row enforces the same window)."""
    from datetime import timedelta

    _, result, _, receipt, rows = capture
    clock = {"now": NOW + timedelta(seconds=899)}
    monkeypatch.setattr(service.shared, "utcnow", lambda: clock["now"])
    real = service.copilot_put.calculate

    def slow_replay(*args, **kwargs):
        clock["now"] = NOW + timedelta(seconds=901)
        return real(*args, **kwargs)

    monkeypatch.setattr(service.copilot_put, "calculate", slow_replay)
    with pytest.raises(APIError) as exc:
        service.confirm("jwt", USER, BOOK, str(result.result_id), receipt)
    assert exc.value.code == "put_plan_expired"
    assert rows == {}
