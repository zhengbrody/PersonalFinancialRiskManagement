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


def _book(context, frame, dollars):
    last = frame.iloc[-1]
    holdings = {t: {"shares": round(usd / last[t], 2)} for t, usd in dollars.items()}
    return replace(context, holdings=holdings, margin_loan=0, cash_balance=500)


def _fat_tail_frame(prices):
    # A: ordinary daily noise; B: quiet tape with four -5% gap days (fat left
    # tail, LOW volatility); C: ordinary noise. Selling A lowers volatility and
    # concentration but RAISES the account's 1-day CVaR. Deterministic seed.
    import numpy as np
    import pandas as pd

    rng = np.random.default_rng(4)
    n = len(prices)
    ra = rng.normal(0, 0.012, n)
    rb = rng.normal(0, 0.003, n)
    rb[[10, 35, 60, 85]] = -0.05
    rc = rng.normal(0, 0.010, n)
    return pd.DataFrame(
        {
            "A": 100 * np.cumprod(1 + ra),
            "B": 100 * np.cumprod(1 + rb),
            "C": 100 * np.cumprod(1 + rc),
        },
        index=prices.index,
    )


def test_larger_tail_loss_is_never_preferred(context, prices):
    frame = _fat_tail_frame(prices)
    book = _book(context, frame, {"A": 4000, "B": 3500, "C": 3500})
    request = task().model_copy(update={"amount": 1000.0})
    result = service.evaluate(book, request, frame, {}, now=NOW)
    by_ticker = {c.assumptions.ticker: c for c in result.candidates}
    sell_a = by_ticker["A"]
    # Precondition that makes this test discriminating: selling A improves
    # volatility and concentration but worsens the dollar tail loss.
    assert sell_a.candidate.annual_volatility < result.baseline.annual_volatility
    assert sell_a.candidate.largest_position_weight < result.baseline.largest_position_weight
    assert sell_a.candidate.cvar_1d_95_usd > result.baseline.cvar_1d_95_usd
    assert result.preferred_result_id is None
    assert "does not worsen" not in result.judgment


def _dominant_frame(prices):
    import numpy as np

    frame = prices.rename(columns={"SGOV": "QQQ"}).copy()
    rng = np.random.default_rng(0)
    frame["QQQ"] = frame["SPY"].iloc[0] * np.cumprod(1 + rng.normal(0, 0.03, len(frame)))
    return frame


def test_dominant_candidate_is_preferred_only_while_every_metric_is_known(
    context, prices, monkeypatch
):
    frame = _dominant_frame(prices)
    last = frame.iloc[-1]
    book = replace(
        context,
        holdings={
            "SPY": {"shares": 10},
            "QQQ": {"shares": round(3 * 10 * last["SPY"] / last["QQQ"])},
        },
        margin_loan=0,
        cash_balance=1000,
    )
    result = service.evaluate(book, task(), frame, {}, now=NOW)
    preferred = next(c for c in result.candidates if c.result_id == result.preferred_result_id)
    others = [result.baseline, *(c.candidate for c in result.candidates if c is not preferred)]
    for other in others:
        assert preferred.candidate.annual_volatility < other.annual_volatility
        assert preferred.candidate.largest_position_weight < other.largest_position_weight
        assert preferred.candidate.cvar_1d_95_usd < other.cvar_1d_95_usd
    assert "does not worsen any compared risk dimension" in result.judgment

    # Any unknown compared dimension on the would-be winner blocks the ranking.
    real = service.copilot_compare.compare_change
    for field in ("cvar_1d_95_usd", "annual_volatility", "largest_position_weight"):

        def blind(ctx, change, data, sources, *, field=field, **kw):
            comparison = real(ctx, change, data, sources, **kw)
            if change.ticker == preferred.assumptions.ticker:
                setattr(comparison.candidate, field, None)
            return comparison

        monkeypatch.setattr(service.copilot_compare, "compare_change", blind)
        blocked = service.evaluate(book, task(), frame, {}, now=NOW)
        assert blocked.preferred_result_id is None, field
        assert "No single candidate dominates" in blocked.judgment


def _scripted(monkeypatch, base, by_ticker):
    """Real comparisons, with the three compared metrics replaced by scripted
    loss-direction values (lower is better) so the preference rule itself is
    exercised against a hand-written oracle."""
    real = service.copilot_compare.compare_change
    order = []

    def scripted(ctx, change, data, sources, **kw):
        comparison = real(ctx, change, data, sources, **kw)
        order.append(change.ticker)
        metrics = by_ticker[len(order) - 1]
        for side, values in ((comparison.baseline, base), (comparison.candidate, metrics)):
            for field, value in zip(
                ("annual_volatility", "largest_position_weight", "cvar_1d_95_usd"), values
            ):
                setattr(side, field, value)
        return comparison

    monkeypatch.setattr(service.copilot_compare, "compare_change", scripted)
    return order


@pytest.mark.parametrize(
    "first,second,winner",
    [
        # Both beat no-action; the second also beats the first -> second only.
        ((0.10, 0.40, 90.0), (0.05, 0.30, 80.0), 1),
        # Both beat no-action but trade off against EACH OTHER -> no preference.
        ((0.10, 0.40, 90.0), (0.15, 0.30, 95.0), None),
        # Equal to no-action in every dimension is not an improvement, even if
        # the peer is strictly worse -> no preference.
        ((0.20, 0.50, 100.0), (0.30, 0.60, 110.0), None),
        # Smaller tail-loss dollars are better: a larger CVaR loss blocks it.
        ((0.10, 0.40, 101.0), (0.30, 0.60, 110.0), None),
    ],
    ids=["dominates-peer", "peers-trade-off", "ties-no-action", "larger-tail-loss"],
)
def test_preference_requires_no_worse_everywhere_and_strictly_better_vs_all(
    context, prices, monkeypatch, first, second, winner
):
    frame = _dominant_frame(prices)
    last = frame.iloc[-1]
    book = replace(
        context,
        holdings={
            "SPY": {"shares": 10},
            "QQQ": {"shares": round(3 * 10 * last["SPY"] / last["QQQ"])},
        },
        margin_loan=0,
        cash_balance=1000,
    )
    order = _scripted(monkeypatch, (0.20, 0.50, 100.0), [first, second])
    result = service.evaluate(book, task(), frame, {}, now=NOW)
    assert len(result.candidates) == 2 and len(order) == 2
    expected = None if winner is None else result.candidates[winner].result_id
    assert result.preferred_result_id == expected
