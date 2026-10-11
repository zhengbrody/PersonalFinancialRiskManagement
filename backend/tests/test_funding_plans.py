"""Signed combined-plan boundaries with the real deterministic replay engine."""

from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.app.core.config import reset_settings_cache
from backend.app.core.responses import APIError
from backend.app.services import comparison_save, signed_plan_records
from backend.app.services import funding_plans as service
from backend.tests import test_funding_scenarios as fixtures
from backend.tests.test_funding_scenarios import BOOK, NOW, USER

inputs = fixtures.inputs


@pytest.fixture
def capture(inputs, monkeypatch, request):
    source, body = inputs
    if getattr(request, "param", False):
        body.risk = fixtures.expiry_risk(source, body)
    monkeypatch.setenv(
        "MINDMARKET_RISK_RUN_SIGNING_SECRET", "funding-test-signing-0000000000000000000000"
    )
    reset_settings_cache()
    # Existing source fixture configures signing and all source replay boundaries.
    monkeypatch.setattr(service, "require_enabled", lambda: None)
    monkeypatch.setattr(service.replay, "utcnow", lambda: NOW)
    result = service.funding_scenarios.calculate(source, body, now=NOW)
    receipt = service.issue(USER, source, body, result)
    rows = {}
    monkeypatch.setattr(
        comparison_save, "_existing", lambda token, user, id: deepcopy(rows.get(id))
    )

    class Client:
        def rpc(self, name, args):
            assert name == "confirm_copilot_funding_plan"
            self.args = args
            return self

        def execute(self):
            proof = comparison_save.Confirmation.model_validate_json(self.args["p_record"])
            row = {
                name: str(getattr(proof, name)) for name in ("user_id", "portfolio_id", "plan_id")
            }
            row.update(record=self.args["p_record"], signature=self.args["p_signature"])
            rows[row["plan_id"]] = row
            return SimpleNamespace(data=[row])

    monkeypatch.setattr(service, "_client", lambda _: Client())
    yield source, result, receipt, rows
    reset_settings_cache()


def test_confirm_retry_historical_read_and_review(capture, monkeypatch):
    source, result, receipt, rows = capture
    id = str(result.result_id)
    saved = service.confirm("jwt", USER, BOOK, id, receipt)
    assert saved.result == result and len(rows) == 1
    assert service.confirm("jwt", USER, BOOK, id, receipt) == saved
    original, snapshot, _ = service.get_saved("jwt", USER, BOOK, id)
    assert original == saved
    review = service.review(
        saved, snapshot, source.account.context(), source.portfolio_revision, now=NOW
    )
    assert review.verdict == "assumptions_need_confirmation"
    changed = service.review(
        saved, snapshot, replace(source.account.context(), cash_balance=1), uuid4(), now=NOW
    )
    assert changed.verdict == "requires_recalculation"
    assert set(changed.changed_fields) >= {"cash_balance", "portfolio_revision"}
    monkeypatch.setattr(service, "fingerprint", lambda: "new-version")
    monkeypatch.setattr(service.replay, "utcnow", lambda: NOW + timedelta(days=5))
    assert service.get_saved("jwt", USER, BOOK, id)[0] == saved
    assert service.confirm("jwt", USER, BOOK, id, receipt) == saved


@pytest.mark.parametrize(
    "case", ["signature", "owner", "portfolio", "id", "expired", "version", "output"]
)
def test_untrusted_or_changed_first_save_is_rejected(capture, monkeypatch, case):
    source, result, receipt, rows = capture
    user, book, id = USER, BOOK, str(result.result_id)
    if case == "signature":
        receipt = receipt.model_copy(update={"signature": "0" * 64})
    elif case == "owner":
        user = str(uuid4())
    elif case == "portfolio":
        book = str(uuid4())
    elif case == "id":
        id = str(uuid4())
    elif case == "expired":
        monkeypatch.setattr(service.replay, "utcnow", lambda: NOW + timedelta(seconds=901))
    elif case == "version":
        monkeypatch.setattr(service, "fingerprint", lambda: "changed")
    else:
        snap = service.read(receipt, user, book, id)
        snap.result.alternatives[1].cash_before_put += 1
        raw, signature = signed_plan_records.sign(snap, service.DOMAIN, "receipt")
        receipt = receipt.model_copy(update={"record": raw, "signature": signature})
    with pytest.raises(APIError):
        service.confirm("jwt", user, book, id, receipt)
    assert not rows


def test_tampered_confirmation_cannot_be_read(capture):
    _, result, receipt, rows = capture
    id = str(result.result_id)
    service.confirm("jwt", USER, BOOK, id, receipt)
    rows[id]["signature"] = "0" * 64
    with pytest.raises(APIError):
        service.get_saved("jwt", USER, BOOK, id)


def test_confirm_api_requires_consent_and_releases_capacity(capture, monkeypatch):
    from unittest.mock import Mock

    from starlette.requests import Request

    from backend.app.api.v1 import funding_plans as api
    from backend.app.schemas.funding_plan import ConfirmFundingPlan

    _, result, receipt, _ = capture
    body = ConfirmFundingPlan(expected_portfolio_id=BOOK, confirmed=False, receipt=receipt)
    user = SimpleNamespace(id=USER, access_token="jwt")
    capacity = Mock()
    capacity.acquire.return_value = True
    monkeypatch.setattr(api.risk, "_check_capacity", capacity)
    req = Request({"type": "http", "headers": []})
    with pytest.raises(APIError, match="confirmation_required"):
        api.confirm(result.result_id, body, req, user)
    capacity.acquire.assert_not_called()
    body.confirmed = True
    monkeypatch.setattr(service, "confirm", Mock(side_effect=APIError(409, "changed", "Changed")))
    with pytest.raises(APIError):
        api.confirm(result.result_id, body, req, user)
    capacity.release.assert_called_once()
    capacity.reset_mock()
    capacity.acquire.return_value = False
    with pytest.raises(APIError, match="risk_busy"):
        api.confirm(result.result_id, body, req, user)
    capacity.release.assert_not_called()


def test_first_save_source_revision_mismatch_rejected(capture):
    _, result, receipt, rows = capture
    snap = service.read(receipt, USER, BOOK, str(result.result_id))
    snap.portfolio_revision = uuid4()
    raw, signature = signed_plan_records.sign(snap, service.DOMAIN, "receipt")
    altered = receipt.model_copy(update={"record": raw, "signature": signature})
    with pytest.raises(APIError, match="funding_source_mismatch"):
        service.confirm("jwt", USER, BOOK, str(result.result_id), altered)
    assert not rows


@pytest.mark.parametrize("capture", [True], indirect=True)
def test_common_expiry_output_roundtrips_signed_save(capture):
    source, result, receipt, rows = capture
    assert result.account_risk is not None
    saved = service.confirm("jwt", USER, BOOK, str(result.result_id), receipt)
    assert saved.result.account_risk == result.account_risk
    original, snapshot, _ = service.get_saved("jwt", USER, BOOK, str(result.result_id))
    assert original.result.account_risk == result.account_risk
    assert service.confirm("jwt", USER, BOOK, str(result.result_id), receipt) == saved
    assert len(rows) == 1


@pytest.mark.parametrize("capture", [True], indirect=True)
@pytest.mark.parametrize("field", ["equity", "prices", "omit"])
def test_signed_but_unreproducible_common_expiry_rejected(capture, field):
    _, result, receipt, rows = capture
    id = str(result.result_id)
    snap = service.read(receipt, USER, BOOK, id)
    if field == "equity":
        snap.result.account_risk.scenarios[0].outcomes[1].net_equity_after_interest += 1
    elif field == "prices":
        snap.result.account_risk.assumptions.scenarios[0].prices["SPY"] += 1
    else:
        snap.result.account_risk = None
    raw, signature = signed_plan_records.sign(snap, service.DOMAIN, "receipt")
    altered = receipt.model_copy(update={"record": raw, "signature": signature})
    with pytest.raises(APIError):
        service.confirm("jwt", USER, BOOK, id, altered)
    assert not rows


def test_review_endpoint_reads_only_and_persists_nothing(capture, monkeypatch):
    from dataclasses import asdict
    from uuid import UUID

    from starlette.requests import Request

    from backend.app.api.v1 import funding_plans as api
    from backend.app.schemas.funding_plan import ReviewFundingPlanRequest
    from backend.app.services import copilot_scope
    from backend.tests.test_put_plans import ReadOnlyClient
    from libs.auth import active_portfolio

    source, result, receipt, rows = capture
    plan_id = str(result.result_id)
    service.confirm("jwt", USER, BOOK, plan_id, receipt)
    stored_before = deepcopy(rows)
    context = source.account.context()
    client = ReadOnlyClient(
        {"portfolios": [{"comparison_revision": str(source.portfolio_revision)}]}
    )
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
    request_ = Request({"type": "http", "headers": []})

    response = api.review(
        UUID(plan_id), ReviewFundingPlanRequest(expected_portfolio_id=UUID(BOOK)), request_, user
    )

    assert response.status_code == 200
    assert client.writes == []
    assert rows == stored_before


def test_save_window_is_anchored_at_the_original_reduction_capture(inputs, monkeypatch):
    """Adding Put assumptions later must not restart the fifteen-minute clock.

    Source reduction captured at T0; the combined scenario is composed at
    T0+10min (allowed: the source is still fresh); saving at T0+15min+1s is
    rejected even though the combined result itself is only ~5 minutes old.
    """
    source, body = inputs
    monkeypatch.setenv(
        "MINDMARKET_RISK_RUN_SIGNING_SECRET", "funding-test-signing-0000000000000000000000"
    )
    reset_settings_cache()
    monkeypatch.setattr(service, "require_enabled", lambda: None)
    rows = {}
    monkeypatch.setattr(comparison_save, "_existing", lambda token, user, id: rows.get(id))
    composed_at = NOW + timedelta(minutes=10)
    result = service.funding_scenarios.calculate(source, body, now=composed_at)
    receipt = service.issue(USER, source, body, result)
    snap = service.read(receipt, USER, BOOK, str(result.result_id))
    assert snap.captured_at == source.captured_at == NOW
    assert snap.result.computed_at == composed_at

    monkeypatch.setattr(service.replay, "utcnow", lambda: NOW + timedelta(minutes=15, seconds=1))
    with pytest.raises(APIError, match="funding_plan_expired"):
        service.confirm("jwt", USER, BOOK, str(result.result_id), receipt)
    assert not rows
    # Inside the window measured from the ORIGINAL capture, the same save proceeds
    # past the expiry gate (the next gate is the implementation fingerprint, so a
    # different error here would mean the clock was re-anchored).
    monkeypatch.setattr(service.replay, "utcnow", lambda: NOW + timedelta(minutes=14, seconds=59))
    monkeypatch.setattr(service, "fingerprint", lambda: "sentinel-past-the-expiry-gate")
    with pytest.raises(APIError, match="funding_implementation_changed"):
        service.confirm("jwt", USER, BOOK, str(result.result_id), receipt)


def test_commit_then_lost_response_retry_returns_the_one_saved_plan(capture, monkeypatch):
    _, result, receipt, rows = capture
    id = str(result.result_id)
    real_client = service._client("jwt")
    calls = []

    class LostResponse:
        def rpc(self, name, args):
            calls.append(name)
            real_client.rpc(name, args)
            return self

        def execute(self):
            real_client.execute()
            raise ConnectionError("socket closed before the response")

    monkeypatch.setattr(service, "_client", lambda token: LostResponse())
    with pytest.raises(APIError) as exc:
        service.confirm("jwt", USER, BOOK, id, receipt)
    assert exc.value.status == 503 and exc.value.code == "funding_save_unconfirmed"
    assert len(rows) == 1 and len(calls) == 1

    retried = service.confirm("jwt", USER, BOOK, id, receipt)
    assert len(calls) == 1 and len(rows) == 1 and retried.result == result
    assert service.get_saved("jwt", USER, BOOK, id)[0] == retried


def test_proof_stamped_outside_the_window_is_never_written(capture, monkeypatch):
    _, result, receipt, rows = capture
    clock = {"now": NOW + timedelta(seconds=899)}
    monkeypatch.setattr(service.replay, "utcnow", lambda: clock["now"])
    real = service.funding_scenarios.calculate

    def slow_replay(*args, **kwargs):
        clock["now"] = NOW + timedelta(seconds=901)
        return real(*args, **kwargs)

    monkeypatch.setattr(service.funding_scenarios, "calculate", slow_replay)
    with pytest.raises(APIError) as exc:
        service.confirm("jwt", USER, BOOK, str(result.result_id), receipt)
    assert exc.value.code == "funding_plan_expired"
    assert rows == {}


def test_confirm_authenticates_the_receipt_before_taking_the_lane(capture, monkeypatch):
    from unittest.mock import Mock

    from starlette.requests import Request

    from backend.app.api.v1 import funding_plans as api
    from backend.app.schemas.funding_plan import ConfirmFundingPlan

    _, result, receipt, rows = capture
    capacity = Mock()
    capacity.acquire.return_value = True
    monkeypatch.setattr(api.risk, "_check_capacity", capacity)
    req = Request({"type": "http", "headers": []})
    forged = receipt.model_copy(update={"signature": "a" * 64})
    for user_id, proof in ((USER, forged), (str(uuid4()), receipt)):
        body = ConfirmFundingPlan(expected_portfolio_id=BOOK, confirmed=True, receipt=proof)
        with pytest.raises(APIError) as exc:
            api.confirm(result.result_id, body, req, SimpleNamespace(id=user_id, access_token="j"))
        assert exc.value.code == "untrusted_funding_plan"
    capacity.acquire.assert_not_called()
    assert rows == {}
