"""Regression tests for the deterministic Action-Card generator
(services/risk_actions.py) — the proposals + book transforms behind the upgraded
cards. Pure, no engine, no network. The endpoint integration (expected deltas
re-scored on real returns) lives in test_score_from_active.py."""

from __future__ import annotations

from backend.app.services import risk_actions as ra

_CONCENTRATED = [
    {"ticker": "NVDA", "market_value": 60000.0, "asset_type": "public_security"},
    {"ticker": "AAPL", "market_value": 25000.0, "asset_type": "public_security"},
    {"ticker": "MSFT", "market_value": 15000.0, "asset_type": "public_security"},
]
_WEIGHTS = {"NVDA": 0.60, "AAPL": 0.25, "MSFT": 0.15}


def test_concentrated_levered_book_gets_all_three_levers():
    specs = ra.propose_specs(
        equity_weights=_WEIGHTS,
        top_ticker="NVDA",
        top_weight=0.60,
        leverage=1.4,
        cash_weight=0.0,
        annual_volatility=0.30,
        beta=1.3,
    )
    assert [s.key for s in specs] == [
        "reduce_concentration",
        "add_cash_buffer",
        "reduce_leverage",
    ]
    for s in specs:
        assert s.trade_offs and s.assumptions  # every card carries both
        assert "Simulate" in s.proposed_change


def test_clean_book_gets_no_levers():
    specs = ra.propose_specs(
        equity_weights={"A": 0.2, "B": 0.2, "C": 0.2, "D": 0.2},
        top_ticker="A",
        top_weight=0.20,
        leverage=1.0,
        cash_weight=0.20,
        annual_volatility=0.10,
        beta=0.7,
    )
    assert specs == []


def test_concentration_lever_only_when_over_cap():
    below = ra.propose_specs(
        equity_weights={"A": 0.24, "B": 0.76},
        top_ticker="B",
        top_weight=0.24,
        leverage=1.0,
        cash_weight=0.0,
        annual_volatility=0.10,
        beta=0.8,
    )
    assert not any(s.key == "reduce_concentration" for s in below)


def test_cap_top_holding_trims_to_25pct_and_moves_to_cash():
    spec = next(
        s
        for s in ra.propose_specs(
            equity_weights=_WEIGHTS,
            top_ticker="NVDA",
            top_weight=0.60,
            leverage=1.0,
            cash_weight=0.0,
            annual_volatility=0.10,
            beta=0.8,
        )
        if s.key == "reduce_concentration"
    )
    legs, cash, lev = ra.apply_spec(_CONCENTRATED, 0.0, 1.0, spec)
    nvda = next(x["market_value"] for x in legs if x["ticker"] == "NVDA")
    assert nvda == 25000.0  # 25% of 100k equity
    assert cash == 35000.0  # the freed amount
    # total value conserved, no new ticker introduced
    assert sum(x["market_value"] for x in legs) + cash == 100000.0
    assert {x["ticker"] for x in legs} == {"NVDA", "AAPL", "MSFT"}


def test_add_cash_buffer_trims_all_holdings_proportionally():
    spec = ra.ProposalSpec(
        kind="add_cash_buffer",
        key="add_cash_buffer",
        title="",
        rationale="",
        proposed_change="",
        params={"fraction": 0.10},
    )
    legs, cash, lev = ra.apply_spec(_CONCENTRATED, 0.0, 1.0, spec)
    assert cash == 10000.0  # 10% of 100k
    # weights unchanged (every leg trimmed by the same fraction)
    assert next(x["market_value"] for x in legs if x["ticker"] == "NVDA") == 54000.0
    assert sum(x["market_value"] for x in legs) + cash == 100000.0


def test_deleverage_sets_leverage_to_one_without_touching_positions():
    spec = ra.ProposalSpec(
        kind="deleverage",
        key="reduce_leverage",
        title="",
        rationale="",
        proposed_change="",
        params={"target": 1.0},
    )
    legs, cash, lev = ra.apply_spec(_CONCENTRATED, 5000.0, 1.8, spec)
    assert lev == 1.0
    assert legs == _CONCENTRATED and cash == 5000.0


def test_levers_never_introduce_a_new_security():
    """Compliance boundary: a lever only trims the user's OWN positions or adds
    cash — it must never create a position in a ticker that wasn't held."""
    specs = ra.propose_specs(
        equity_weights=_WEIGHTS,
        top_ticker="NVDA",
        top_weight=0.60,
        leverage=1.5,
        cash_weight=0.0,
        annual_volatility=0.30,
        beta=1.3,
    )
    original = {x["ticker"] for x in _CONCENTRATED}
    for s in specs:
        legs, _cash, _lev = ra.apply_spec(_CONCENTRATED, 0.0, 1.5, s)
        assert {x["ticker"] for x in legs} <= original  # subset — nothing new
        assert "buy" not in s.proposed_change.lower()
