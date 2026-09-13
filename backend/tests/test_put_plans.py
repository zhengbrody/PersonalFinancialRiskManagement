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
