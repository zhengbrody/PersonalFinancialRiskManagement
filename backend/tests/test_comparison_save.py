"""API trust/confirmation tests. DB locking/RLS is tested separately on PostgreSQL."""

import json
from datetime import timedelta
from types import SimpleNamespace
from uuid import UUID

import pytest

from backend.app.core.responses import APIError
from backend.app.services import comparison_replay as replay
from backend.app.services import comparison_save as save
from backend.app.services import copilot_compare as compare
from backend.tests.test_comparison_replay import OTHER, SECRET, USER
from backend.tests.test_copilot_mixed_compare import BOOK, NOW, captured, change
from backend.tests.test_copilot_mixed_compare import book as _book
from backend.tests.test_copilot_mixed_compare import prices as _prices

REV = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")


@pytest.fixture
def setup(monkeypatch):
    settings = SimpleNamespace(
        copilot_comparison_save_enabled=True,
        copilot_comparison_replay_enabled=True,
        risk_run_signing_secret=SECRET,
    )
    monkeypatch.setattr(save, "get_settings", lambda: settings)
    monkeypatch.setattr(replay, "get_settings", lambda: settings)
    clock = {"now": NOW + timedelta(seconds=10)}
    monkeypatch.setattr(replay, "utcnow", lambda: clock["now"])
    book, prices = _book.__wrapped__(), _prices.__wrapped__()
    options = captured(book, prices)
    result = compare.compare_change(book, change(), prices, {}, now=NOW, option_results=options)
    receipt = replay.issue_receipt(USER, book, prices, options, {}, result, portfolio_revision=REV)
    state = {"row": None, "writes": 0, "fail": None, "lose_response": False}

    def existing(token, user, plan):
        assert token == "jwt"
        row = state["row"]
        return row if row and row["user_id"] == user and row["plan_id"] == plan else None

    class DB:
        def rpc(self, name, params):
            assert name == "confirm_copilot_comparison"
            assert set(params) == {"p_record", "p_signature"}
            self.params = params
            return self

        def execute(self):
            if state["fail"]:
                raise RuntimeError(state["fail"])
            if not state["row"]:
                proof = json.loads(self.params["p_record"])
                state["row"] = {k: proof[k] for k in ("user_id", "portfolio_id", "plan_id")}
                state["row"].update(
                    record=self.params["p_record"], signature=self.params["p_signature"]
                )
                state["writes"] += 1
            if state["lose_response"]:
                raise RuntimeError("private provider exception")
            return SimpleNamespace(data=[state["row"]])

    monkeypatch.setattr(save, "_existing", existing)
    monkeypatch.setattr(save, "_client", lambda token: DB())
    return SimpleNamespace(
        result=result, receipt=receipt, clock=clock, state=state, settings=settings
    )


def confirm(s, **kw):
    return save.confirm("jwt", USER, BOOK, str(s.result.result_id), kw.get("receipt", s.receipt))


def test_confirm_exact_result_and_retry_after_book_or_time_changes(setup, monkeypatch):
    s = setup
    saved = confirm(s)
    assert saved.result == s.result
    assert saved.plan_id == s.result.result_id
    assert s.state["writes"] == 1
    s.clock["now"] += timedelta(days=2)
    monkeypatch.setattr(replay, "replay", lambda *a: pytest.fail("retry must not recompute"))
    assert confirm(s) == saved
    assert save.get_saved("jwt", USER, BOOK, str(saved.result_id)) == saved
    assert s.state["writes"] == 1


def test_response_lost_after_commit_retries_without_second_plan(setup):
    s = setup
    s.state["lose_response"] = True
    with pytest.raises(APIError) as error:
        confirm(s)
    assert error.value.code == "comparison_save_unconfirmed"
    assert "private" not in error.value.message
    assert confirm(s).result == s.result
    assert s.state["writes"] == 1


@pytest.mark.parametrize("delta", [-1, 901])
def test_new_confirmation_requires_recent_capture(setup, delta):
    setup.clock["now"] = NOW + timedelta(seconds=delta)
    with pytest.raises(APIError) as e:
        confirm(setup)
    assert e.value.code == "comparison_expired"
    assert setup.state["writes"] == 0


def test_legacy_receipt_cannot_save_even_if_client_sets_hint(setup):
    snapshot = replay.read_receipt(setup.receipt, USER, BOOK, str(setup.result.result_id))
    receipt = replay.issue_receipt(
        USER,
        snapshot.account.context(),
        snapshot.prices.frame(),
        snapshot.option_results,
        snapshot.sources,
        snapshot.result,
    )
    with pytest.raises(APIError) as e:
        confirm(setup, receipt=receipt.model_copy(update={"save_available": True}))
    assert e.value.code == "comparison_expired"
    assert setup.state["writes"] == 0


def test_untrusted_receipt_and_cross_user_cannot_write(setup):
    with pytest.raises(APIError):
        confirm(setup, receipt=setup.receipt.model_copy(update={"record": "{}"}))
    with pytest.raises(APIError):
        save.confirm("jwt", OTHER, BOOK, str(setup.result.result_id), setup.receipt)
    assert setup.state["writes"] == 0


@pytest.mark.parametrize("mutation", ["signature", "record", "user_id", "portfolio_id", "plan_id"])
def test_saved_proof_tampering_and_row_rebinding_fail_closed(setup, mutation):
    confirm(setup)
    setup.state["row"][mutation] = "bad" if mutation in ("record", "signature") else OTHER
    with pytest.raises(APIError):
        save._verified_row(setup.state["row"], USER, BOOK, str(setup.result.result_id))


def test_version_drift_and_atomic_stale_guard(setup, monkeypatch):
    setup.state["fail"] = "comparison_stale: private account"
    with pytest.raises(APIError) as e:
        confirm(setup)
    assert e.value.code == "comparison_stale"
    assert setup.state["writes"] == 0
    monkeypatch.setattr(replay, "implementation_fingerprint", lambda: "changed")
    with pytest.raises(APIError) as e:
        confirm(setup)
    assert e.value.code == "comparison_version_changed"


def test_default_off_and_deleted_record(setup):
    with pytest.raises(APIError) as e:
        save.get_saved("jwt", USER, BOOK, str(setup.result.result_id))
    assert e.value.status == 404
    setup.settings.copilot_comparison_save_enabled = False
    with pytest.raises(APIError) as e:
        confirm(setup)
    assert e.value.status == 503


def test_http_explicit_confirmation_scope_capacity_and_retrieval(setup, test_client, mint_token):
    from backend.app.api.v1 import copilot_compare as api

    # The repository fake asserts the route passes a caller JWT, not a service key.
    token = mint_token(sub=USER)
    # Replace fake expected token without changing production dependency injection.
    old_existing = save._existing
    from unittest.mock import patch

    path = f"/api/v1/copilot/compare-change/{setup.result.result_id}"
    headers = {"Authorization": f"Bearer {token}"}
    body = {"expected_portfolio_id": BOOK, "receipt": setup.receipt.model_dump(mode="json")}
    assert test_client.post(path + "/confirm", json={**body, "confirmed": True}).status_code == 401
    for value in (False, "true", 1, None):
        assert (
            test_client.post(
                path + "/confirm", headers=headers, json={**body, "confirmed": value}
            ).status_code
            == 422
        )
    assert (
        test_client.post(
            path + "/confirm", headers=headers, json={**body, "confirmed": True, "baseline": {}}
        ).status_code
        == 422
    )
    api.risk._check_capacity.acquire()
    try:
        assert (
            test_client.post(
                path + "/confirm", headers=headers, json={**body, "confirmed": True}
            ).status_code
            == 429
        )
    finally:
        api.risk._check_capacity.release()
    with patch.object(
        save,
        "_existing",
        lambda t, u, p: old_existing("jwt", u, p) if t == token else pytest.fail("wrong JWT"),
    ):
        response = test_client.post(
            path + "/confirm", headers=headers, json={**body, "confirmed": True}
        )
        assert response.status_code == 200, response.text
        assert response.json()["data"]["result"] == setup.result.model_dump(mode="json")
        assert (
            test_client.get(
                path + f"/saved?expected_portfolio_id={BOOK}", headers=headers
            ).status_code
            == 200
        )
        assert (
            test_client.get(
                path + f"/saved?expected_portfolio_id={OTHER}", headers=headers
            ).status_code
            == 409
        )
    assert setup.state["writes"] == 1


def test_real_resolver_preserves_option_identity_and_adjustment_flags(monkeypatch):
    from libs.auth import active_portfolio as active

    book = _book.__wrapped__()
    row = {"id": BOOK, "holdings": book.holdings, "margin_loan": 5000, "cash_balance": 1000}
    monkeypatch.setattr(active, "_fetch_db_portfolio", lambda **kw: row)
    context = active.get_active_portfolio_context(access_token="jwt")
    from backend.app.services.comparison_options import option_specs

    specs = option_specs(context.holdings, now=NOW)
    assert len(specs) == 6
    assert sorted(s.quantity for s in specs) == [-1, -1, -1, 1, 1, 1]
    first = next(k for k, h in row["holdings"].items() if h.get("asset_type") == "option")
    row["holdings"][first]["adjusted"] = True
    context = active.get_active_portfolio_context(access_token="jwt")
    assert context.holdings[first]["adjusted"] is True
    with pytest.raises(APIError):
        option_specs(context.holdings, now=NOW)
