"""Cash conservation, same-frame math, unsupported assets and tenant binding."""

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from backend.app.core.responses import APIError
from backend.app.schemas.copilot_compare import CompareChange
from backend.app.services import copilot_compare as service
from libs.auth.active_portfolio import ActivePortfolioContext

BOOK = "33333333-3333-4333-8333-333333333333"
NOW = datetime(2026, 9, 6, tzinfo=timezone.utc)


@pytest.fixture
def context():
    return ActivePortfolioContext(
        BOOK, {"SGOV": {"shares": 100}, "SPY": {"shares": 10}}, 1000, 5000, 7500
    )


@pytest.fixture
def prices():
    dates = pd.bdate_range(end="2026-09-04", periods=101)
    x = np.arange(len(dates))
    spy = np.exp(0.005 * x + 0.05 * np.sin(x / 3))
    return pd.DataFrame(
        {"SGOV": 100 * np.exp(0.0001 * (x - 100)), "SPY": 200 * spy / spy[-1]}, index=dates
    )


def change(**kwargs):
    return CompareChange(
        **{
            "expected_portfolio_id": BOOK,
            "ticker": "SGOV",
            "amount": 1000,
            "proceeds": "repay_margin",
            **kwargs,
        }
    )


def compare(context, prices, **kwargs):
    return service.compare_change(
        context, change(**kwargs), prices, {"SGOV": "fixture", "SPY": "fixture"}, now=NOW
    )


def test_repayment_conserves_equity_without_double_counting_cash(context, prices):
    original = deepcopy(context)
    result = compare(context, prices)
    assert result.baseline.net_equity == result.candidate.net_equity == 8000
    assert result.baseline.gross_assets == 13000
    assert result.candidate.gross_assets == 12000
    assert result.candidate.cash == 1000
    assert result.candidate.margin == 4000
    assert result.candidate.leverage == 1.5
    assert context == original
    assert result.observations == 100 and result.price_as_of == "2026-09-04"
    assert "SGOV" not in result.snapshot_digest
    assert len(result.snapshot_digest) == 64


def test_keep_cash_preserves_gross_and_loan(context, prices):
    result = compare(context, prices, proceeds="cash")
    assert result.candidate.net_equity == result.baseline.net_equity
    assert result.candidate.cash == 2000
    assert result.candidate.margin == 5000
    assert result.candidate.gross_assets == result.baseline.gross_assets


def test_both_engine_calls_share_return_frame_and_use_equity_dollar_basis(
    context, prices, monkeypatch
):
    calls = []
    real = service.compute_portfolio_metrics

    def compute(positions, returns, **kwargs):
        metrics = real(positions, returns, **kwargs)
        calls.append((returns, metrics))
        return metrics

    monkeypatch.setattr(service, "compute_portfolio_metrics", compute)
    result = compare(context, prices, ticker="SPY", amount=2000)
    assert calls[0][0] is calls[1][0]
    assert len(calls[1][0]) == result.observations
    assert result.candidate.cvar_1d_95_usd == pytest.approx(calls[1][1].cvar_95_daily * 8000)
    assert result.candidate.annual_volatility < result.baseline.annual_volatility


def test_complete_sale_to_cash_is_valid(context, prices):
    context = replace(context, holdings={"SPY": {"shares": 10}}, cash_balance=0, margin_loan=0)
    result = compare(context, prices, ticker="SPY", amount=2000, proceeds="cash")
    assert result.candidate.cash == result.candidate.net_equity == 2000
    assert result.candidate.largest_position_weight == 0
    assert result.candidate.var_1d_95_usd == 0


@pytest.mark.parametrize("kind", ["option", "crypto", "real_estate", "cash", "unknown"])
def test_never_silently_drops_unsupported_assets(context, prices, kind):
    context.holdings["OTHER"] = {"shares": 1, "asset_type": kind}
    message = "identified US-listed" if kind == "option" else "supports long stocks"
    with pytest.raises(APIError, match=message):
        compare(context, prices)


@pytest.mark.parametrize(
    "patch",
    [{"shares": -1}, {"shares": float("nan")}, {"shares": None}, {"shares": 1, "strike": 400}],
)
def test_invalid_or_disguised_option_legs_block(context, prices, patch):
    context.holdings["SPY"] = patch
    with pytest.raises(APIError):
        compare(context, prices)


@pytest.mark.parametrize(
    "kwargs,code",
    [
        ({"amount": 6000}, "repayment_exceeds_loan"),
        ({"amount": 10001, "proceeds": "cash"}, "reduction_exceeds_holding"),
        ({"ticker": "AAPL"}, "ticker_not_held"),
        ({"amount": 1.001}, "invalid_comparison_inputs"),
    ],
)
def test_explicit_constraints_not_silently_resized(context, prices, kwargs, code):
    with pytest.raises(APIError) as exc:
        compare(context, prices, **kwargs)
    assert exc.value.code == code


@pytest.mark.parametrize("amount", [0, -1, float("inf"), True, "1000"])
def test_amount_schema_rejects_invalid_inputs(amount):
    with pytest.raises(ValidationError):
        change(amount=amount)


@pytest.mark.parametrize(
    "defect",
    ["missing", "short", "stale", "future", "last_nan", "duplicates", "gaps", "nonnumeric"],
)
def test_bad_data_blocks_whole_comparison(context, prices, defect):
    if defect == "missing":
        prices = prices.drop(columns="SPY")
    if defect == "short":
        prices = prices.tail(30)
    if defect == "stale":
        prices.index -= pd.Timedelta(days=14)
    if defect == "future":
        prices.index += pd.Timedelta(days=14)
    if defect == "last_nan":
        prices.iloc[-1, 0] = np.nan
    if defect == "duplicates":
        prices = pd.concat([prices, prices.tail(1)])
    if defect == "gaps":
        prices.iloc[30:45, 0] = np.nan
    if defect == "nonnumeric":
        prices = prices.astype(str)
    with pytest.raises(APIError):
        compare(context, prices)


@pytest.mark.parametrize("loan", [13000, 12900])
def test_impaired_equity_or_extreme_leverage_is_not_capped(context, prices, loan):
    with pytest.raises(APIError) as exc:
        compare(replace(context, margin_loan=loan), prices)
    assert exc.value.code == "unsupported_leverage"


def test_digest_changes_with_data_or_assumption(context, prices):
    first = compare(context, prices)
    assert first.snapshot_digest == compare(context, prices).snapshot_digest
    assert first.snapshot_digest != compare(context, prices, amount=900).snapshot_digest
    prices.iloc[20, 0] += 0.01
    assert first.snapshot_digest != compare(context, prices).snapshot_digest


@pytest.mark.parametrize(
    "holding", [{"shares": True}, {"shares": 1, "currency": "CAD"}, {"shares": 1e100}]
)
def test_quantity_currency_and_valuation_guards(context, prices, holding):
    context.holdings["SPY"] = holding
    with pytest.raises(APIError):
        compare(context, prices)


def test_exchange_suffix_cannot_be_mistaken_for_usd(context, prices):
    context.holdings["SHOP.TO"] = {"shares": 1}
    with pytest.raises(APIError, match="FX-aware"):
        compare(context, prices)


def test_missing_entire_date_is_not_labeled_a_one_day_return(context, prices):
    prices = prices.drop(prices.index[20])
    result = compare(context, prices)
    assert result.observations == 98  # Missing day AND its multiday successor omitted.


@pytest.fixture
def endpoint(monkeypatch, context, prices):
    from backend.app.api.v1 import copilot_compare as api

    state = {"context": context, "fetches": 0, "tokens": [], "after": lambda: None}

    def resolve(*, access_token):
        state["tokens"].append(access_token)
        return state["context"]

    def history(*args, **kwargs):
        state["fetches"] += 1
        state["after"]()
        return prices

    monkeypatch.setattr("libs.auth.active_portfolio.get_active_portfolio_context", resolve)
    monkeypatch.setattr(
        api.risk,
        "_resolve_active_context_or_raise",
        lambda user: resolve(access_token=user.access_token),
    )
    monkeypatch.setattr(api.market_data, "get_price_history", history)
    return state


def post(client, token, **kwargs):
    return client.post(
        "/api/v1/copilot/compare-change",
        headers={"Authorization": f"Bearer {token}"},
        json=change(**kwargs).model_dump(mode="json"),
    )


def test_authenticated_endpoint_fetches_once_and_checks_book_twice(
    test_client, mint_token, endpoint
):
    token = mint_token()
    response = post(test_client, token)
    assert response.status_code == 200, response.text
    assert endpoint["fetches"] == 1
    assert endpoint["tokens"] == [token, token]


def test_auth_gate_and_wrong_book_never_fetch(test_client, mint_token, endpoint):
    assert (
        test_client.post(
            "/api/v1/copilot/compare-change", json=change().model_dump(mode="json")
        ).status_code
        == 401
    )
    assert (
        post(
            test_client, mint_token(), expected_portfolio_id="22222222-2222-4222-8222-222222222222"
        ).status_code
        == 409
    )
    assert endpoint["fetches"] == 0


def test_changed_inputs_reject_result(test_client, mint_token, endpoint):
    endpoint["after"] = lambda: endpoint.update(
        context=replace(endpoint["context"], margin_loan=100)
    )
    assert post(test_client, mint_token()).status_code == 409


def test_unsupported_book_blocked_before_network(test_client, mint_token, endpoint):
    endpoint["context"].holdings["OPT"] = {"shares": -1, "asset_type": "option"}
    assert post(test_client, mint_token()).status_code == 422
    assert endpoint["fetches"] == 0


def test_capacity_and_release_on_validation_failure(test_client, mint_token, endpoint):
    from backend.app.api.v1 import risk

    risk._check_capacity.acquire()
    try:
        assert post(test_client, mint_token()).status_code == 429
    finally:
        risk._check_capacity.release()
    assert post(test_client, mint_token(), ticker="AAPL").status_code == 422
    assert post(test_client, mint_token()).status_code == 200


def test_largest_position_weight_uses_the_invested_basis_not_gross(context, prices):
    """Concentration must match `/risk` — invested book, cash excluded.

    A stock-only numerator over a gross total containing cash always reports a
    smaller, friendlier number than the rest of the product does for the same
    account, and on a mixed book this is the only concentration figure returned.
    """
    cash_heavy = replace(context, cash_balance=20000, margin_loan=0)
    baseline = compare(cash_heavy, prices, ticker="SPY", amount=1, proceeds="cash").baseline

    values = {
        "SGOV": 100 * float(prices["SGOV"].iloc[-1]),
        "SPY": 10 * float(prices["SPY"].iloc[-1]),
    }
    invested = sum(values.values())
    assert baseline.largest_position_weight == pytest.approx(max(values.values()) / invested)
    # The pre-fix figure divided by gross (invested + cash) — strictly smaller.
    assert baseline.largest_position_weight > max(values.values()) / (invested + 20000)
    assert baseline.cash == pytest.approx(20000)
