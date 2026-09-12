from copy import deepcopy
from dataclasses import replace

import pytest

from backend.app.core.responses import APIError
from backend.app.schemas.copilot_candidates import CandidateRequest
from backend.app.services import copilot_candidates as service
from backend.tests import test_copilot_compare as fixtures

BOOK, NOW = fixtures.BOOK, fixtures.NOW
context, prices = fixtures.context, fixtures.prices


def task(**changes):
    return CandidateRequest(
        **dict(
            expected_portfolio_id=BOOK,
            goal="increase_cash",
            amount=500.0,
            protected_holdings=[],
            confirmed=True,
            **changes,
        )
    )


def test_shared_capture_conservation_and_liquidity(context, prices):
    original = deepcopy(context)
    result = service.evaluate(
        context, task(), prices, {"SPY": "fixture", "SGOV": "fixture"}, now=NOW
    )
    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.assumptions.ticker == "SPY"
    assert candidate.baseline == result.baseline
    assert candidate.candidate.cash - candidate.baseline.cash == 500
    assert candidate.candidate.net_equity == candidate.baseline.net_equity
    assert "SGOV" in result.excluded
    assert result.task.confirmed and context == original


def test_constraints_block_all_candidates(context, prices):
    request = task().model_copy(update={"protected_holdings": ["SPY"]})
    result = service.evaluate(context, request, prices, {}, now=NOW)
    assert result.candidates == [] and result.preferred_result_id is None
    assert result.coverage == "insufficient_data"
    assert set(result.excluded) == {"SGOV", "SPY"}


def test_confirmation_and_scope_required(context, prices):
    for changes, code in [
        ({"confirmed": False}, "constraints_unconfirmed"),
        ({"protected_holdings": ["FAKE"]}, "unknown_protected_holding"),
        ({"amount": 0.111}, "invalid_amount"),
    ]:
        with pytest.raises(APIError) as exc:
            service.evaluate(context, task().model_copy(update=changes), prices, {}, now=NOW)
        assert exc.value.code == code


def test_stale_data_never_ranks(context, prices):
    with pytest.raises(APIError) as exc:
        service.evaluate(context, task(), prices.iloc[:-20], {}, now=NOW)
    assert exc.value.code == "comparison_data_stale"


def test_two_candidates_share_frame_and_time(context, prices, monkeypatch):
    book = replace(context, holdings={"SPY": {"shares": 10}, "QQQ": {"shares": 20}}, margin_loan=0)
    frame = prices.rename(columns={"SGOV": "QQQ"})
    frame["QQQ"] = frame["SPY"] * 0.5
    real = service.copilot_compare.compare_change
    calls = []

    def capture(ctx, change, data, sources, **kw):
        calls.append((id(data), kw["now"]))
        return real(ctx, change, data, sources, **kw)

    monkeypatch.setattr(service.copilot_compare, "compare_change", capture)
    result = service.evaluate(book, task(), frame, {}, now=NOW)
    assert len(result.candidates) == 2
    assert len(set(calls)) == 1
    assert all(c.baseline == result.baseline for c in result.candidates)


def test_liquidity_buffer_is_preserved_even_with_positive_covariance(context, prices):
    frame = prices.copy()
    frame["SGOV"] = frame["SPY"] * 0.5
    result = service.evaluate(context, task(), frame, {}, now=NOW)
    assert [c.assumptions.ticker for c in result.candidates] == ["SPY"]
    assert result.excluded["SGOV"] == "Preserved as a liquidity buffer."


def test_option_underlying_is_not_an_automatic_sale(context, prices):
    holdings = {
        **context.holdings,
        "SPY270115C00200000": {
            "asset_type": "option",
            "underlying": "SPY",
            "option_type": "call",
            "option_side": "sell",
            "shares": -1,
            "strike": 200,
            "expiry": "2027-01-15",
            "contract_multiplier": 100,
        },
    }
    result = service.evaluate(replace(context, holdings=holdings), task(), prices, {}, now=NOW)
    assert result.candidates == []
    assert result.excluded["SPY"] == "Existing option relationship must be preserved."


@pytest.mark.parametrize("field", ["amount", "baseline", "portfolio", "preferred"])
def test_batch_contract_rejects_misattributed_results(context, prices, field):
    from pydantic import ValidationError

    from backend.app.schemas.copilot_candidates import CandidateBatch

    result = service.evaluate(context, task(), prices, {}, now=NOW).model_dump()
    if field == "amount":
        result["candidates"][0]["assumptions"]["amount"] = 999.0
    elif field == "baseline":
        result["candidates"][0]["baseline"]["cash"] = 999.0
    elif field == "portfolio":
        result["candidates"][0]["portfolio_id"] = "11111111-1111-4111-8111-111111111111"
    else:
        result["preferred_result_id"] = "11111111-1111-4111-8111-111111111111"
    with pytest.raises(ValidationError):
        CandidateBatch.model_validate(result)
