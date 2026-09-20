"""Actual replay and composition: no provider calls, no account writes."""

from datetime import timedelta
from uuid import UUID

import pytest

from backend.app.core.responses import APIError
from backend.app.schemas.funding_scenarios import FundingScenarioRequest
from backend.app.services import comparison_replay as replay
from backend.app.services import copilot_compare, funding_scenarios
from backend.tests.test_comparison_replay import SECRET, USER
from backend.tests.test_copilot_compare import BOOK, NOW, change
from backend.tests.test_copilot_compare import context as _context
from backend.tests.test_copilot_compare import prices as _prices
from backend.tests.test_copilot_put import request as put_request


@pytest.fixture
def inputs(monkeypatch):
    monkeypatch.setenv("MINDMARKET_COPILOT_COMPARISON_REPLAY_ENABLED", "true")
    from types import SimpleNamespace

    monkeypatch.setattr(
        replay,
        "get_settings",
        lambda: SimpleNamespace(
            copilot_comparison_replay_enabled=True, risk_run_signing_secret=SECRET
        ),
    )
    context, prices = _context.__wrapped__(), _prices.__wrapped__()
    comparison = copilot_compare.compare_change(
        context, change(proceeds="cash", amount=6000.0), prices, {}, now=NOW
    )
    receipt = replay.issue_receipt(
        USER, context, prices, [], {}, comparison, portfolio_revision=UUID(BOOK)
    )
    snapshot = replay.read_receipt(receipt, USER, BOOK, str(comparison.result_id))
    body = FundingScenarioRequest(
        expected_portfolio_id=BOOK,
        source_result_id=comparison.result_id,
        receipt=receipt,
        put=put_request(),
        sale_fees=10.0,
        confirmed=True,
    )
    return snapshot, body


def test_cash_debt_conservation_and_gross_assignment_shortfall(inputs):
    snapshot, body = inputs
    before = snapshot.model_dump()
    result = funding_scenarios.calculate(snapshot, body, now=NOW)
    baseline, keep, repay = result.alternatives
    assert baseline.put is None and baseline.initial_incremental_equity == 0
    assert (keep.cash_before_put, keep.margin_remaining) == (6990, 5000)
    assert (repay.cash_before_put, repay.margin_remaining, repay.debt_repaid) == (1990, 0, 5000)
    assert keep.status == "financing_rules_required"
    assert repay.status == "insufficient_cash"
    assert repay.put.pre_trade_funding_gap == 9010
    assert repay.assignment_cash_shortfall == 8811
    assert (
        keep.hypothetical_debt_if_shortfall_financed
        == repay.hypothetical_debt_if_shortfall_financed
        == 8811
    )
    assert (
        keep.cash_before_put - keep.margin_remaining
        == repay.cash_before_put - repay.margin_remaining
    )
    assert keep.initial_incremental_equity == repay.initial_incremental_equity == -11
    assert keep.put.maximum_loss == repay.put.maximum_loss == 9801
    assert all(row.put.receipt is None for row in (keep, repay))
    assert snapshot.model_dump() == before
    assert result.preferred_alternative is None and result.broker_buying_power is None


@pytest.mark.parametrize("seconds", [-1, 901])
def test_expired_or_future_capture_stops(inputs, seconds):
    snapshot, body = inputs
    with pytest.raises(APIError, match="Capture a new comparison"):
        funding_scenarios.calculate(snapshot, body, now=NOW + timedelta(seconds=seconds))


def test_protected_holding_and_unconfirmed_request_stop(inputs):
    snapshot, body = inputs
    with pytest.raises(APIError, match="protected"):
        funding_scenarios.calculate(
            snapshot, body.model_copy(update={"protected_holdings": [" sgov "]}), now=NOW
        )
    with pytest.raises(APIError, match="Confirm"):
        funding_scenarios.calculate(snapshot, body.model_copy(update={"confirmed": False}), now=NOW)


def test_modified_calculation_cannot_compose(inputs):
    snapshot, body = inputs
    altered = snapshot.model_copy(deep=True)
    altered.result.candidate.cash += 1
    with pytest.raises(APIError, match="reproduce"):
        funding_scenarios.calculate(altered, body, now=NOW)


def test_fee_cannot_consume_all_proceeds(inputs):
    snapshot, body = inputs
    with pytest.raises(APIError, match="fees"):
        funding_scenarios.calculate(
            snapshot, body.model_copy(update={"sale_fees": 6000.0}), now=NOW
        )


def test_api_binds_signed_owner_revision_and_current_account(inputs, monkeypatch):
    from types import SimpleNamespace

    from backend.app.api.v1 import funding_scenarios as api

    snapshot, body = inputs
    user = SimpleNamespace(id=USER, access_token="test-jwt")
    monkeypatch.setattr(
        api,
        "get_settings",
        lambda: SimpleNamespace(
            decision_support_enabled=True,
            cash_secured_put_enabled=True,
            funding_scenarios_enabled=True,
        ),
    )
    monkeypatch.setattr(
        api.risk, "_resolve_active_context_or_raise", lambda user: snapshot.account.context()
    )
    monkeypatch.setattr(api.comparison_replay, "utcnow", lambda: NOW)
    monkeypatch.setattr(api.copilot_scope, "verify_scope", lambda *args: None)
    monkeypatch.setattr(api, "ok", lambda result, **kwargs: result)
    monkeypatch.setattr(api.comparison_save, "portfolio_revision", lambda *args: UUID(BOOK))
    assert len(api.calculate(body, None, user)["alternatives"]) == 3
    with pytest.raises(APIError, match="verified"):
        api.calculate(
            body,
            None,
            SimpleNamespace(id="22222222-2222-4222-8222-222222222222", access_token="other"),
        )
    revisions = iter([UUID(BOOK), UUID(USER)])
    monkeypatch.setattr(api.comparison_save, "portfolio_revision", lambda *args: next(revisions))
    with pytest.raises(APIError, match="changed during"):
        api.calculate(body, None, user)
    monkeypatch.setattr(api.comparison_save, "portfolio_revision", lambda *args: UUID(USER))
    with pytest.raises(APIError, match="fresh comparison"):
        api.calculate(body, None, user)


def test_api_feature_disabled_before_receipt_parsing(inputs, monkeypatch):
    from types import SimpleNamespace

    from backend.app.api.v1 import funding_scenarios as api

    monkeypatch.setattr(
        api,
        "get_settings",
        lambda: SimpleNamespace(
            decision_support_enabled=True,
            cash_secured_put_enabled=True,
            funding_scenarios_enabled=False,
        ),
    )
    with pytest.raises(APIError, match="not enabled"):
        api.calculate(inputs[1], None, SimpleNamespace(id=USER, access_token="test"))


def test_public_assumptions_risk_stage_and_unknown_interest(inputs):
    snapshot, body = inputs
    result = funding_scenarios.calculate(snapshot, body, now=NOW)
    assert result.assumptions.model_dump() == body.model_dump(exclude={"receipt"})
    assert result.captured_at == snapshot.captured_at
    baseline, keep, repay = result.alternatives
    assert (
        baseline.pre_put_largest_position_weight == snapshot.result.baseline.largest_position_weight
    )
    assert (
        keep.pre_put_largest_position_weight
        == repay.pre_put_largest_position_weight
        == snapshot.result.candidate.largest_position_weight
    )
    assert keep.pre_put_var_1d_95_usd == snapshot.result.candidate.var_1d_95_usd
    for row, put_row in zip(keep.expiry_funding, keep.put.scenarios, strict=True):
        assert row.underlying_price == put_row.underlying_price
        assert row.interest_cost is None
        assert (
            row.hypothetical_debt_if_shortfall_financed
            == keep.margin_remaining + put_row.funding_gap_after_reserves
        )


def test_capacity_busy_and_release_on_error(inputs, monkeypatch):
    from threading import BoundedSemaphore
    from types import SimpleNamespace

    from backend.app.api.v1 import funding_scenarios as api

    snapshot, body = inputs
    user = SimpleNamespace(id=USER, access_token="test-jwt")
    monkeypatch.setattr(
        api,
        "get_settings",
        lambda: SimpleNamespace(
            decision_support_enabled=True,
            cash_secured_put_enabled=True,
            funding_scenarios_enabled=True,
        ),
    )
    monkeypatch.setattr(
        api.risk, "_resolve_active_context_or_raise", lambda user: snapshot.account.context()
    )
    monkeypatch.setattr(api.comparison_save, "portfolio_revision", lambda *args: UUID(BOOK))
    gate = BoundedSemaphore(1)
    monkeypatch.setattr(api.risk, "_check_capacity", gate)
    assert gate.acquire(blocking=False)
    with pytest.raises(APIError, match="Another risk analysis"):
        api.calculate(body, None, user)
    assert not gate.acquire(blocking=False)
    gate.release()

    def fail(*args, **kwargs):
        raise RuntimeError("calculation failed")

    monkeypatch.setattr(api.funding_scenarios, "calculate", fail)
    with pytest.raises(RuntimeError, match="calculation failed"):
        api.calculate(body, None, user)
    assert gate.acquire(blocking=False)
    gate.release()


@pytest.mark.parametrize("sell_underlying", [False, True])
def test_same_underlying_puts_reserve_gross_cash_without_netting(inputs, sell_underlying):
    from backend.app.services import comparison_options
    from backend.tests.test_copilot_mixed_compare import symbol
    from backend.tests.test_copilot_put import option

    snapshot, body = inputs
    context = snapshot.account.context()
    ticker = symbol("SPY", "2026-11-20", "put", 50)
    context.holdings[ticker] = option()
    frame = snapshot.prices.frame()

    def quote(underlying, expiry, kind, strike):
        return {"contract_symbol": ticker, "strike": strike, "bid": 0.95, "ask": 1.05}

    option_rows = comparison_options.capture_options(
        comparison_options.option_specs(context.holdings, now=NOW),
        frame.iloc[-1].to_dict(),
        now=NOW,
        chain_fn=quote,
    )
    result = copilot_compare.compare_change(
        context,
        (
            snapshot.result.assumptions.model_copy(update={"ticker": "SPY", "amount": 1000.0})
            if sell_underlying
            else snapshot.result.assumptions
        ),
        frame,
        {},
        now=NOW,
        option_results=option_rows,
    )
    receipt = replay.issue_receipt(
        USER, context, frame, option_rows, {}, result, portfolio_revision=UUID(BOOK)
    )
    source = replay.read_receipt(receipt, USER, BOOK, str(result.result_id))
    updated = body.model_copy(update={"source_result_id": result.result_id, "receipt": receipt})
    if sell_underlying:
        with pytest.raises(APIError, match="option underlying"):
            funding_scenarios.calculate(source, updated, now=NOW)
        return
    combined = funding_scenarios.calculate(source, updated, now=NOW)
    for row in combined.alternatives[1:]:
        assert row.put.existing_put_reserve == 5000
        assert row.put.assignment_notional == 10000
        assert row.put.pre_trade_funding_gap == 16000 - row.cash_before_put
        assert row.pre_put_var_1d_95_usd is None  # Mixed account: do not invent historical VaR.


def expiry_risk(snapshot, body):
    from backend.app.schemas.funding_risk import FundingRiskAssumptions

    prices = snapshot.prices.frame().iloc[-1].to_dict()
    prices[body.put.underlying] = body.put.strike * 0.5
    return FundingRiskAssumptions(
        annual_borrowing_rate=0.12,
        scenarios=[{"label": "explicit terminal prices", "prices": prices}],
    )


def test_composition_includes_common_expiry_ledger(inputs):
    snapshot, body = inputs
    body.risk = expiry_risk(snapshot, body)
    result = funding_scenarios.calculate(snapshot, body, now=NOW)
    risk = result.account_risk
    assert risk is not None and risk.assumptions == body.risk
    assert risk.source_result_id == result.source_result_id
    assert risk.portfolio_id == result.portfolio_id
    assert risk.captured_at == result.captured_at
    baseline, keep, repay = risk.scenarios[0].outcomes
    assert baseline.assignment_shares == {}
    assert keep.assignment_shares == repay.assignment_shares == {body.put.underlying: 100}
    assert baseline.interest_cost > 0 and keep.interest_cost > 0
    assert repay.interest_cost == 0
    assert keep.principal_debt == baseline.principal_debt
    assert repay.principal_debt == 0
    assert risk.preferred_alternative is None
    assert result.assumptions.risk == body.risk


def test_composition_rejects_missing_terminal_prices(inputs):
    snapshot, body = inputs
    body.risk = expiry_risk(snapshot, body)
    body.risk.scenarios[0].prices.pop(snapshot.result.assumptions.ticker)
    with pytest.raises(APIError, match="incomplete_expiry_prices"):
        funding_scenarios.calculate(snapshot, body, now=NOW)
