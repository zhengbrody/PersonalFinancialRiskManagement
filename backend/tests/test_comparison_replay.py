"""A signature authenticates captured bytes; replay never re-fetches prices."""

import hashlib
import hmac
import json
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace

import pytest

from backend.app.core.responses import APIError
from backend.app.schemas.copilot_compare import ComparisonReceipt
from backend.app.services import comparison_replay as replay
from backend.app.services import copilot_compare as compare
from backend.tests.test_copilot_mixed_compare import (
    BOOK,
    NOW,
    captured,
    change,
    quote,
)
from backend.tests.test_copilot_mixed_compare import (
    book as _book,
)
from backend.tests.test_copilot_mixed_compare import (
    prices as _prices,
)

USER = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"
SECRET = "test-independent-signing-secret-at-least-32-bytes"


@pytest.fixture
def book():
    return _book.__wrapped__()


@pytest.fixture
def prices():
    return _prices.__wrapped__()


@pytest.fixture(autouse=True)
def enabled(monkeypatch):
    settings = SimpleNamespace(
        copilot_comparison_replay_enabled=True,
        copilot_comparison_save_enabled=False,
        risk_run_signing_secret=SECRET,
    )
    monkeypatch.setattr(replay, "get_settings", lambda: settings)
    return settings


def issue(book, prices):
    rows = captured(book, prices)
    result = compare.compare_change(book, change(), prices, {}, now=NOW, option_results=rows)
    frame, _ = compare.prepare_prices(prices, sorted(prices.columns), now=NOW)
    receipt = replay.issue_receipt(USER, book, frame, rows, {}, result)
    return result, receipt


@pytest.mark.parametrize("mixed", [True, False])
def test_full_price_and_option_snapshot_reproduces_without_market_io(
    book, prices, monkeypatch, mixed
):
    if not mixed:
        book = replace(
            book, holdings={k: v for k, v in book.holdings.items() if not v.get("asset_type")}
        )
        prices = prices[["SGOV", "SPY"]].copy()
    original, receipt = issue(book, prices)
    snapshot = replay.read_receipt(receipt, USER, BOOK, str(original.result_id))

    def forbidden(*args, **kw):
        pytest.fail("Replay must not fetch live data or write an account")

    monkeypatch.setattr("backend.app.services.market_data.get_price_history", forbidden)
    monkeypatch.setattr("backend.app.services.options_analytics._default_chain_row", forbidden)
    monkeypatch.setattr("backend.app.services.risk_plans.create_plan", forbidden)
    assert replay.replay(snapshot) == original
    assert len(snapshot.option_results) == (6 if mixed else 0)
    assert replay.current_inputs_match(snapshot, book)
    assert not replay.current_inputs_match(snapshot, replace(book, cash_balance=1100))
    assert "Bearer" not in receipt.record and SECRET not in receipt.record
    prices.iloc[-1, 0] = 999
    book.holdings["SGOV"]["shares"] = 999
    assert replay.replay(snapshot) == original  # Captured, not a mutable caller reference.


def test_null_price_cell_and_integer_account_values_roundtrip(book, prices):
    prices.iloc[10, 0] = float("nan")
    original, receipt = issue(book, prices)
    assert "NaN" not in receipt.record
    assert (
        replay.replay(replay.read_receipt(receipt, USER, BOOK, str(original.result_id))) == original
    )


@pytest.mark.parametrize("field", ["cash", "quote", "matrix", "result", "assumption"])
def test_tampering_rejected_before_any_recalculation(book, prices, monkeypatch, field):
    result, receipt = issue(book, prices)
    body = json.loads(receipt.record)
    if field == "cash":
        body["account"]["cash_balance"] += 1
    if field == "quote":
        body["option_results"][0]["quantity"] *= -1
    if field == "matrix":
        body["prices"]["values"][-1][0] += 1
    if field == "result":
        body["result"]["baseline"]["net_equity"] += 1
    if field == "assumption":
        body["result"]["assumptions"]["amount"] += 1
    receipt = receipt.model_copy(update={"record": json.dumps(body)})
    monkeypatch.setattr(
        compare, "compare_change", lambda *a, **k: pytest.fail("untrusted bytes evaluated")
    )
    with pytest.raises(APIError, match="could not be verified"):
        replay.read_receipt(receipt, USER, BOOK, str(result.result_id))


@pytest.mark.parametrize("user,book_id", [(OTHER, BOOK), (USER, OTHER)])
def test_tenant_and_portfolio_binding(book, prices, user, book_id):
    result, receipt = issue(book, prices)
    with pytest.raises(APIError):
        replay.read_receipt(receipt, user, book_id, str(result.result_id))
    with pytest.raises(APIError):
        replay.read_receipt(receipt, USER, BOOK, OTHER)


def test_version_change_does_not_silently_reinterpret_old_results(book, prices, monkeypatch):
    result, receipt = issue(book, prices)
    snapshot = replay.read_receipt(receipt, USER, BOOK, str(result.result_id))
    monkeypatch.setattr(replay, "implementation_fingerprint", lambda: "new-engine")
    with pytest.raises(APIError) as exc:
        replay.replay(snapshot)
    assert exc.value.code == "comparison_version_changed"


def test_signed_but_non_reproducible_result_fails_closed(book, prices):
    result, receipt = issue(book, prices)
    snapshot = replay.read_receipt(receipt, USER, BOOK, str(result.result_id))
    snapshot.result.baseline.cash += 1
    with pytest.raises(APIError) as exc:
        replay.replay(snapshot)
    assert exc.value.code == "comparison_replay_mismatch"


def test_key_rotation_domain_separation_and_default_off(book, prices, enabled):
    result, receipt = issue(book, prices)
    # Same root secret cannot sign this protocol using the journal's raw-key convention.
    raw_signature = hmac.new(SECRET.encode(), receipt.record.encode(), hashlib.sha256).hexdigest()
    with pytest.raises(APIError):
        replay.read_receipt(
            receipt.model_copy(update={"signature": raw_signature}),
            USER,
            BOOK,
            str(result.result_id),
        )
    enabled.risk_run_signing_secret = "rotated-secret-that-is-long-enough-to-use"
    with pytest.raises(APIError):
        replay.read_receipt(receipt, USER, BOOK, str(result.result_id))
    enabled.copilot_comparison_replay_enabled = False
    with pytest.raises(APIError) as exc:
        replay.signing_key()
    assert exc.value.status == 503
    enabled.copilot_comparison_replay_enabled = True
    enabled.risk_run_signing_secret = "short"
    with pytest.raises(APIError):
        replay.signing_key()


def test_snapshot_bounds_and_malformed_signed_record(book, prices, monkeypatch):
    monkeypatch.setattr(replay, "MAX_BYTES", 100)
    with pytest.raises(APIError) as exc:
        issue(book, prices)
    assert exc.value.code == "comparison_snapshot_too_large"
    raw = "{}"
    receipt = ComparisonReceipt(
        record=raw,
        signature=hmac.new(replay.signing_key(), raw.encode(), hashlib.sha256).hexdigest(),
    )
    with pytest.raises(APIError):
        replay.read_receipt(receipt, USER, BOOK, OTHER)


def test_authenticated_verify_flow_is_read_only_and_reports_stale_inputs(
    test_client, mint_token, monkeypatch, enabled, book, prices
):
    from backend.app.api.v1 import copilot_compare as api

    monkeypatch.setattr(api, "get_settings", lambda: enabled)
    monkeypatch.setattr(api.market_data, "get_price_history", lambda *a, **k: prices)
    monkeypatch.setattr(api.comparison_options.options_analytics, "_default_chain_row", quote)
    current = {"book": book}
    monkeypatch.setattr(api.risk, "_resolve_active_context_or_raise", lambda user: current["book"])
    monkeypatch.setattr(
        "libs.auth.active_portfolio.get_active_portfolio_context", lambda **k: current["book"]
    )
    token = mint_token(sub=USER)
    headers = {"Authorization": f"Bearer {token}"}
    response = test_client.post(
        "/api/v1/copilot/compare-change", headers=headers, json=change().model_dump(mode="json")
    )
    assert response.status_code == 200, response.text
    result = response.json()["data"]
    assert result["replay_receipt"] is not None
    path = f"/api/v1/copilot/compare-change/{result['result_id']}/verify"
    body = {"expected_portfolio_id": BOOK, "receipt": result["replay_receipt"]}
    monkeypatch.setattr(
        api.market_data,
        "get_price_history",
        lambda *a, **k: pytest.fail("market call on verification"),
    )
    verified = test_client.post(path, headers=headers, json=body)
    assert verified.status_code == 200, verified.text
    assert verified.json()["data"]["inputs_match_now"] is True
    assert verified.json()["data"]["result"]["replay_receipt"] is None
    current["book"] = replace(book, margin_loan=4000)
    stale = test_client.post(path, headers=headers, json=body)
    assert stale.status_code == 200 and not stale.json()["data"]["inputs_match_now"]
    snapshot = replay.read_receipt(
        ComparisonReceipt(**body["receipt"]), USER, BOOK, result["result_id"]
    )
    monkeypatch.setattr(replay, "utcnow", lambda: snapshot.captured_at + timedelta(hours=1))
    assert not test_client.post(path, headers=headers, json=body).json()["data"]["recent_capture"]
    assert test_client.post(path, json=body).status_code == 401
    assert (
        test_client.post(
            path, headers={"Authorization": f"Bearer {mint_token(sub=OTHER)}"}, json=body
        ).status_code
        == 409
    )
    current["book"] = replace(book, portfolio_id=OTHER)
    assert test_client.post(path, headers=headers, json=body).status_code == 409
    api.risk._check_capacity.acquire()
    try:
        assert test_client.post(path, headers=headers, json=body).status_code == 429
    finally:
        api.risk._check_capacity.release()


def _side(**over):
    from backend.app.schemas.copilot_compare import ComparisonSide

    base = dict(
        gross_assets=42207.0,
        net_equity=40207.0,
        cash=5300.0,
        margin=2000.0,
        leverage=1.0497425821374387,
        largest_position_weight=0.8266074186468692,
        annual_volatility=0.11678841029345419,
        var_1d_95_usd=468.85435645168354,
        cvar_1d_95_usd=618.2610535451386,
    )
    base.update(over)
    return ComparisonSide(**base)


def test_replay_accepts_a_last_bit_floating_point_difference():
    """Production case: an unmodified re-run landed on the neighbouring double.

    IEEE-754 reductions are not bit-reproducible, so byte equality refused a
    calculation that had not changed. 468.8543564516835 vs 468.85435645168354
    is one unit in the last place.
    """
    assert replay.reproduces(_side(var_1d_95_usd=468.8543564516835), _side())


def test_replay_still_rejects_a_materially_changed_number():
    # A cent on a $468 figure is ~2e-5 relative — far outside the 1e-9 window.
    assert not replay.reproduces(_side(var_1d_95_usd=468.86), _side())
    assert not replay.reproduces(_side(net_equity=40207.01), _side())


def test_replay_requires_exact_equality_for_everything_that_is_not_a_float():
    assert not replay._same({"ticker": "SPY"}, {"ticker": "AAPL"})
    assert not replay._same({"proceeds": "cash"}, {"proceeds": "repay_margin"})
    assert not replay._same({"a": 1}, {"b": 1})
    assert not replay._same([1.0, 2.0], [1.0])
    # A bool must never be compared as the number it would coerce to.
    assert not replay._same({"x": True}, {"x": 1})
    assert not replay._same({"x": False}, {"x": 0.0})
    # None stays distinguishable from zero.
    assert not replay._same({"x": None}, {"x": 0.0})
