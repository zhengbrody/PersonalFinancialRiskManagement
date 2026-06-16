"""options_strategies — multi-leg netting into recognized strategies with
BOUNDED economics (the fix for a spread's short leg showing an unreal
unbounded loss)."""

from __future__ import annotations

from backend.app.services.options_strategies import build_strategies


def _leg(option_type, strike, qty, premium, *, underlying="AAPL", expiry="2026-01-16", spot=150.0):
    mult = 100.0
    greeks = {"delta": 0.5, "gamma": 0.02, "theta": -0.03, "vega": 0.1}
    return {
        "underlying": underlying,
        "expiry": expiry,
        "option_type": option_type,
        "strike": strike,
        "quantity": qty,
        "contract_multiplier": mult,
        "spot": spot,
        "mark": premium,
        "cost_basis": round(premium * qty * mult, 2),
        "unrealized_pnl": 0.0,
        "greeks": greeks,
    }


def test_bull_call_spread_is_named_and_bounded():
    # Long 140 call @ $8, short 160 call @ $2 → net debit $6/share = $600.
    legs = [_leg("call", 140, 1, 8.0), _leg("call", 160, -1, 2.0)]
    strategies = build_strategies(legs)
    assert len(strategies) == 1
    s = strategies[0]
    assert s["name"] == "Bull call spread"
    assert s["leg_count"] == 2
    # net debit = 800 (paid) - 200 (received) = 600.
    assert s["net_debit"] == 600.0
    # BOTH sides bounded (no unbounded loss/gain) — the whole point.
    assert s["max_loss"] is not None and s["max_gain"] is not None
    # Max loss = net debit = $600; max gain = width(20)*100 - 600 = $1400.
    assert abs(s["max_loss"] - 600.0) <= 1.0
    assert abs(s["max_gain"] - 1400.0) <= 1.0
    # One break-even between the strikes (≈ 146).
    assert len(s["break_evens"]) == 1
    assert 140 < s["break_evens"][0] < 160
    # Net greeks summed (long+short delta cancels somewhat).
    assert "delta" in s["net_greeks"]


def test_short_call_alone_is_unbounded_loss_but_long_call_is_unbounded_gain():
    short = build_strategies([_leg("call", 160, -1, 2.0)])[0]
    assert short["name"] == "Short call"
    assert short["max_loss"] is None  # naked short call: unbounded loss
    assert short["max_gain"] is not None  # capped at premium

    long = build_strategies([_leg("call", 140, 1, 8.0)])[0]
    assert long["name"] == "Long call"
    assert long["max_gain"] is None  # unbounded upside
    assert long["max_loss"] is not None  # capped at premium


def test_groups_are_split_by_underlying_and_expiry():
    legs = [
        _leg("call", 140, 1, 8.0, underlying="AAPL", expiry="2026-01-16"),
        _leg("call", 160, -1, 2.0, underlying="AAPL", expiry="2026-01-16"),
        _leg("put", 100, 1, 3.0, underlying="MSFT", expiry="2026-02-20", spot=110.0),
    ]
    strategies = build_strategies(legs)
    assert len(strategies) == 2
    names = {(s["underlying"], s["name"]) for s in strategies}
    assert ("AAPL", "Bull call spread") in names
    assert ("MSFT", "Long put") in names


def test_long_straddle_detected():
    legs = [_leg("call", 150, 1, 5.0), _leg("put", 150, 1, 5.0)]
    s = build_strategies(legs)[0]
    assert s["name"] == "Long straddle"
    # Straddle: net long calls → upside unbounded; downside bounded (S→0).
    assert s["max_gain"] is None
    assert s["max_loss"] is not None


def test_missing_data_is_fail_soft():
    # No strike / premium → no payoff, but still grouped + named without raising.
    legs = [
        {"underlying": "AAPL", "expiry": "2026-01-16", "option_type": "call", "quantity": 1},
    ]
    s = build_strategies(legs)[0]
    assert s["payoff"] == []
    assert s["max_loss"] is None and s["max_gain"] is None
