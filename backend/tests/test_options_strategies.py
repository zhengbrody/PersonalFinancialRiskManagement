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
    assert s["premium_basis"] == "entry"
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


def test_realistic_googl_vertical_nets_short_leg_instead_of_adding_it():
    # Broker shape from the incident: long 380 / short 400, one contract each.
    # Entry premiums are illustrative; the invariant is exact spread economics.
    legs = [
        _leg("call", 380, 1, 12.95, underlying="GOOGL", expiry="2027-01-15", spot=398),
        _leg("call", 400, -1, 6.95, underlying="GOOGL", expiry="2027-01-15", spot=398),
    ]
    s = build_strategies(legs)[0]
    assert s["name"] == "Bull call spread"
    assert s["net_debit"] == 600.0
    assert s["max_loss"] == 600.0
    assert s["max_gain"] == 1400.0
    assert s["break_evens"] == [386.0]
    # Exact strikes are always present in the chart, independent of sampling.
    assert {380.0, 400.0}.issubset({point["price"] for point in s["payoff"]})


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


def test_narrow_butterfly_uses_exact_strike_extrema_not_chart_sampling():
    # Long 100/101/102 call butterfly for a $0.20 debit. Its $80 peak is only
    # one dollar wide and was easy for a coarse grid to miss.
    legs = [
        _leg("call", 100, 1, 2.0, spot=101),
        _leg("call", 101, -2, 1.1, spot=101),
        _leg("call", 102, 1, 0.4, spot=101),
    ]
    s = build_strategies(legs)[0]
    assert s["name"] == "Long call butterfly"
    assert s["net_debit"] == 20.0
    assert s["max_loss"] == 20.0
    assert s["max_gain"] == 80.0
    assert s["break_evens"] == [100.2, 101.8]


def test_unequal_call_ratio_detects_unbounded_tail_loss():
    # Buy one lower call, sell two upper calls. Beyond the upper strike the
    # net slope is -100 dollars per $1 move, so loss is truly unbounded.
    legs = [_leg("call", 140, 1, 8.0), _leg("call", 160, -2, 2.0)]
    s = build_strategies(legs)[0]
    assert s["name"] == "Call ratio spread"
    assert s["max_loss"] is None
    assert s["max_gain"] is not None


def test_missing_entry_basis_uses_signed_current_marks_and_labels_it():
    legs = [_leg("call", 380, 1, 12.88), _leg("call", 400, -1, 8.60)]
    for leg in legs:
        leg["cost_basis"] = None
    s = build_strategies(legs)[0]
    assert s["net_debit"] == 428.0
    assert s["premium_basis"] == "current_mark"
    assert s["max_loss"] == 428.0
    assert s["max_gain"] == 1572.0
    assert s["break_evens"] == [384.28]


def test_missing_both_entry_and_mark_reports_basis_unavailable():
    leg = _leg("call", 100, 1, 2.0)
    leg["cost_basis"] = None
    leg["mark"] = None
    s = build_strategies([leg])[0]
    assert s["net_debit"] is None
    assert s["premium_basis"] == "unavailable"
    assert s["payoff"] == []


def test_iron_butterfly_and_reverse_iron_butterfly_are_named_by_center_legs():
    normal = [
        _leg("put", 90, 1, 1.0),
        _leg("put", 100, -1, 4.0),
        _leg("call", 100, -1, 4.0),
        _leg("call", 110, 1, 1.0),
    ]
    reverse = [
        _leg("put", 90, -1, 1.0),
        _leg("put", 100, 1, 4.0),
        _leg("call", 100, 1, 4.0),
        _leg("call", 110, -1, 1.0),
    ]
    assert build_strategies(normal)[0]["name"] == "Iron butterfly"
    assert build_strategies(reverse)[0]["name"] == "Reverse iron butterfly"


def test_missing_data_is_fail_soft():
    # No strike / premium → no payoff, but still grouped + named without raising.
    legs = [
        {"underlying": "AAPL", "expiry": "2026-01-16", "option_type": "call", "quantity": 1},
    ]
    s = build_strategies(legs)[0]
    assert s["payoff"] == []
    assert s["max_loss"] is None and s["max_gain"] is None
