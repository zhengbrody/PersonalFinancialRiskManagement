from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from backend.app.core.config import reset_settings_cache
from backend.app.core.responses import APIError
from backend.app.schemas.copilot_put import CashSecuredPutRequest
from backend.app.services.copilot_put import calculate
from libs.auth.active_portfolio import ActivePortfolioContext

BOOK = "33333333-3333-4333-8333-333333333333"
NOW = datetime(2026, 9, 12, tzinfo=timezone.utc)


def request(**changes):
    return CashSecuredPutRequest(
        **{
            "expected_portfolio_id": BOOK,
            "underlying": "SPY",
            "expiry": "2026-10-16",
            "strike": 100.0,
            "premium_per_share": 2.0,
            "assumed_spot": 105.0,
            "contracts": 1,
            "fees_total": 1.0,
            "other_reserved_cash": 0.0,
            "cash_buffer": 1000.0,
            "confirmed": True,
            "gross_settled_usd_cash_confirmed": True,
            "standard_contract_confirmed": True,
            **changes,
        }
    )


def account(cash=11000, holdings=None):
    return ActivePortfolioContext(BOOK, holdings or {"SGOV": {"shares": 100}}, cash, 0, 0)


def option(**changes):
    return {
        "asset_type": "option",
        "underlying": "SPY",
        "strike": 50,
        "expiry": "2026-11-20",
        "shares": 1,
        "option_side": "short",
        "option_type": "put",
        "contract_multiplier": 100,
        **changes,
    }


def test_cash_ledger_and_expiry_loss_conserve_value():
    context = account()
    original = deepcopy(context)
    out = calculate(context, request(), "snapshot", now=NOW)
    assert context == original
    assert out.assignment_notional == 10000 and out.net_premium == 199
    assert out.initial_incremental_equity == -1
    assert out.maximum_loss == 9801 and out.best_expiry_pnl == 199
    assert out.breakeven == 98.01 and out.funding_status == "covered_under_assumptions"
    zero = out.scenarios[0]
    assert zero.underlying_price == 0 and zero.candidate_incremental_pnl == -9801
    assert zero.shares_acquired == 100 and zero.cash_after_settlement == 1199
    assert zero.free_cash_after_reserves == 199 and zero.funding_gap_after_reserves == 0
    for row in out.scenarios:
        assert row.no_action_incremental_pnl == 0
        assert row.candidate_incremental_pnl == pytest.approx(
            row.cash_after_settlement
            - out.recorded_cash
            + row.shares_acquired * row.underlying_price,
            abs=0.01,
        )
    assert not out.save_available


def test_premium_and_cash_equivalent_do_not_hide_pretrade_gap():
    out = calculate(account(10801), request(), "s", now=NOW)
    assert out.pre_trade_funding_gap == 199
    assert out.funding_status == "insufficient_cash"
    # Receipt of premium would close the gap, but cannot satisfy pre-trade coverage.
    assert out.scenarios[0].funding_gap_after_reserves == 0


def test_existing_puts_and_other_cash_holds_are_reserved_once():
    out = calculate(
        account(16000, {"old-put": option()}), request(other_reserved_cash=500.0), "s", now=NOW
    )
    assert out.existing_put_reserve == 5000
    assert out.no_action_free_cash == 9500 and out.pre_trade_funding_gap == 500
    assert out.scenarios[0].cash_after_settlement == 6199
    assert out.scenarios[0].free_cash_after_reserves == -301
    assert out.scenarios[0].funding_gap_after_reserves == 301


@pytest.mark.parametrize(
    "field", ["confirmed", "gross_settled_usd_cash_confirmed", "standard_contract_confirmed"]
)
def test_consent_is_required(field):
    with pytest.raises(APIError, match="Confirm"):
        calculate(account(), request(**{field: False}), "s", now=NOW)


@pytest.mark.parametrize(
    "changes",
    [
        {"option_side": "long"},
        {"option_type": "call"},
        {"contract_multiplier": 10},
        {"option_side": None},
        {"expiry": "2026-09-12"},
        {"adjusted": True},
    ],
)
def test_existing_option_obligations_are_not_silently_ignored(changes):
    with pytest.raises(APIError):
        calculate(account(50000, {"old-option": option(**changes)}), request(), "s", now=NOW)


@pytest.mark.parametrize(
    "holding",
    [
        {"shares": -10},
        {"shares": None},
        {"shares": True},
        {"shares": 1, "currency": "EUR"},
        {"shares": 1, "asset_type": "future"},
        {"shares": 1, "option_type": "put", "strike": 100},
    ],
)
def test_unknown_funding_positions_stop_coverage(holding):
    with pytest.raises(APIError):
        calculate(account(50000, {"UNKNOWN": holding}), request(), "s", now=NOW)


def test_debt_wrong_account_and_expiry_are_rejected():
    for context in [
        replace(account(), margin_loan=1),
        replace(account(), portfolio_id=str("1" * 32)),
    ]:
        with pytest.raises(APIError):
            calculate(context, request(), "s", now=NOW)
    for expiry in [NOW.date(), NOW.date() + timedelta(days=731)]:
        with pytest.raises(APIError):
            calculate(account(), request(expiry=expiry), "s", now=NOW)


@pytest.mark.parametrize(
    "changes",
    [
        {"contracts": True},
        {"strike": True},
        {"cash_buffer": float("nan")},
        {"premium_per_share": 100.0},
        {"fees_total": 200.0},
    ],
)
def test_invalid_assumptions_rejected(changes):
    with pytest.raises(ValidationError):
        request(**changes)


def test_api_auth_disable_and_scope_check(test_client, mint_token, monkeypatch):
    from backend.app.api.v1 import risk
    from backend.app.services import copilot_scope

    headers = {"Authorization": f"Bearer {mint_token()}"}
    body = request(expiry=(datetime.now(timezone.utc).date() + timedelta(days=30))).model_dump(
        mode="json"
    )
    endpoint = "/api/v1/copilot/cash-secured-put"
    assert test_client.post(endpoint, json=body).status_code == 401
    loader = Mock(return_value=account())
    monkeypatch.setattr(risk, "_resolve_active_context_or_raise", loader)
    assert test_client.post(endpoint, json=body, headers=headers).status_code == 503
    loader.assert_not_called()
    monkeypatch.setenv("MINDMARKET_DECISION_SUPPORT_ENABLED", "true")
    monkeypatch.setenv("MINDMARKET_CASH_SECURED_PUT_ENABLED", "true")
    reset_settings_cache()
    verify = Mock()
    monkeypatch.setattr(copilot_scope, "verify_scope", verify)
    try:
        result = test_client.post(endpoint, json=body, headers=headers)
        assert result.status_code == 200 and result.json()["data"]["assignment_notional"] == 10000
        verify.assert_called_once()
        verify.side_effect = APIError(409, "portfolio_changed", "Account changed")
        assert test_client.post(endpoint, json=body, headers=headers).status_code == 409
    finally:
        reset_settings_cache()


def test_contract_scaling_and_one_cent_shortfall():
    out = calculate(account(30999.99), request(contracts=3), "s", now=NOW)
    assert out.assignment_notional == 30000
    assert out.net_premium == 599 and out.maximum_loss == 29401
    assert out.pre_trade_funding_gap == 0.01
    assert out.scenarios[0].shares_acquired == 300


def test_put_capability_is_advertised_only_when_enabled(monkeypatch):
    from backend.app.services import copilot_router

    monkeypatch.setenv("MINDMARKET_DECISION_SUPPORT_ENABLED", "true")
    monkeypatch.setenv("MINDMARKET_CASH_SECURED_PUT_ENABLED", "false")
    reset_settings_cache()
    assert not copilot_router.answer(
        "What is a put?", user=object()
    ).decision_support.cash_secured_put_available
    monkeypatch.setenv("MINDMARKET_CASH_SECURED_PUT_ENABLED", "true")
    reset_settings_cache()
    try:
        assert copilot_router.answer(
            "What is a put?", user=object()
        ).decision_support.cash_secured_put_available
        assert not copilot_router.answer(
            "Explain valuation", user=object()
        ).decision_support.cash_secured_put_available
    finally:
        reset_settings_cache()


def test_ui_entered_stock_holdings_are_fundable():
    # The production normaliser labels any UI-entered non-ETF stock "equity";
    # the funding engine must accept the same long stock/ETF set the comparison does.
    from libs.auth.active_portfolio import _normalise_portfolio_row

    holdings, margin = _normalise_portfolio_row(
        {"holdings": {"AAPL": {"shares": 10, "avg_cost": 150}, "SPY": {"shares": 5}}}
    )
    assert holdings["AAPL"]["asset_type"] == "equity"
    out = calculate(
        ActivePortfolioContext(BOOK, holdings, 11000, margin, 0), request(), "s", now=NOW
    )
    assert out.funding_status == "covered_under_assumptions"
    with pytest.raises(APIError, match="Unsupported assets"):
        calculate(
            account(holdings={"BTC-USD": {"shares": 1, "asset_type": "crypto"}}),
            request(),
            "s",
            now=NOW,
        )
