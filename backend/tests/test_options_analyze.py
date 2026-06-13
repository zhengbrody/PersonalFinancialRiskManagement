"""Tests for option analytics (``services.options_analytics``) + the
``POST /api/v1/options/analyze`` route.

The service's market fetchers are injected so the Black-Scholes math is tested
deterministically without yfinance; the route test stubs the service to verify
wiring + envelope + auth-gating.
"""

from __future__ import annotations

from types import SimpleNamespace

from backend.app.services import options_analytics as oa

# A comfortably-future expiry so time_to_expiry_years() stays > 0 as the clock
# advances during the test session.
_FUTURE = "2027-06-18"
_PAST = "2020-01-01"


def _spec(**kw):
    base = dict(
        underlying="AAPL",
        option_type="call",
        strike=100.0,
        expiry=_FUTURE,
        quantity=1.0,
        avg_premium=None,
        contract_multiplier=100.0,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _spot(_underlying):
    return 100.0


def _chain(_u, _e, _t, _k):
    return {
        "contract_symbol": "AAPL270618C00100000",
        "strike": 100.0,
        "bid": 9.8,
        "ask": 10.2,
        "last_price": 10.0,
        "implied_volatility": 0.25,
        "open_interest": 1234.0,
        "volume": 56.0,
    }


# ── happy path ────────────────────────────────────────────────────────────────


def test_analyze_contract_full_greeks_and_payoff():
    r = oa.analyze_contract(_spec(avg_premium=8.0), spot_fn=_spot, chain_fn=_chain)
    assert r["spot"] == 100.0
    assert r["mark"] == 10.0  # mid of 9.8/10.2
    assert r["iv"] == 0.25
    assert r["moneyness"] == "ATM"
    assert r["contract_symbol"] == "AAPL270618C00100000"

    g = r["greeks"]
    assert g is not None
    assert 0.5 < g["delta"] < 0.8  # slightly-ITM-by-rate ATM call
    assert g["gamma"] > 0 and g["vega"] > 0 and g["theta"] < 0
    assert r["delta_notional"] == round(g["delta"] * 1 * 100 * 100.0, 2)

    # MV/cost/P&L (mark 10 vs premium 8) × 1 contract × 100.
    assert r["market_value"] == 1000.0
    assert r["cost_basis"] == 800.0
    assert r["unrealized_pnl"] == 200.0

    assert len(r["payoff"]) == oa._PAYOFF_POINTS
    assert r["break_even"] == 108.0  # strike 100 + premium 8 (call)
    assert r["warnings"] == []


def test_put_break_even_and_delta_sign():
    r = oa.analyze_contract(
        _spec(option_type="put", avg_premium=5.0), spot_fn=_spot, chain_fn=_chain
    )
    assert r["greeks"]["delta"] < 0  # long put → negative delta
    assert r["break_even"] == 95.0  # strike 100 − premium 5 (put)


# ── fail-soft ─────────────────────────────────────────────────────────────────


def test_chain_unavailable_is_soft():
    r = oa.analyze_contract(_spec(), spot_fn=_spot, chain_fn=lambda *a: None)
    assert r["greeks"] is None and r["mark"] is None
    assert any("chain unavailable" in w for w in r["warnings"])
    assert r["spot"] == 100.0  # spot still resolved


def test_missing_spot_is_soft():
    r = oa.analyze_contract(_spec(), spot_fn=lambda _u: None, chain_fn=_chain)
    assert r["spot"] is None and r["greeks"] is None
    assert any("underlying spot" in w for w in r["warnings"])


def test_expired_contract_flagged():
    r = oa.analyze_contract(_spec(expiry=_PAST), spot_fn=_spot, chain_fn=_chain)
    assert any("expired" in w for w in r["warnings"])
    assert r["greeks"] is None  # T <= 0 → no Greeks


def test_unknown_option_type_soft():
    r = oa.analyze_contract(_spec(option_type="straddle"), spot_fn=_spot, chain_fn=_chain)
    assert r["greeks"] is None
    assert any("unknown option_type" in w for w in r["warnings"])


def test_iv_solved_from_mark_when_chain_iv_absent():
    def chain_no_iv(*a):
        row = _chain(*a)
        row["implied_volatility"] = None
        return row

    r = oa.analyze_contract(_spec(), spot_fn=_spot, chain_fn=chain_no_iv)
    # IV solved from the $10 mark → a finite positive number, Greeks present.
    assert r["iv"] is not None and r["iv"] > 0
    assert r["greeks"] is not None


# ── batch roll-up ─────────────────────────────────────────────────────────────


def test_batch_totals_roll_up():
    out = oa.analyze_contracts(
        [_spec(quantity=2.0), _spec(option_type="put", quantity=1.0)],
        spot_fn=_spot,
        chain_fn=_chain,
    )
    assert len(out["results"]) == 2
    t = out["totals"]
    assert t["contracts"] == 2
    # net delta = 2·call_delta·100 + 1·put_delta·100 (put delta negative).
    assert t["net_delta"] != 0.0
    assert t["market_value"] > 0
    assert "as_of" in out


# ── route ─────────────────────────────────────────────────────────────────────


def test_analyze_route_requires_auth(test_client):
    resp = test_client.post(
        "/api/v1/options/analyze",
        json={
            "contracts": [
                {"underlying": "AAPL", "option_type": "call", "strike": 100, "expiry": _FUTURE}
            ]
        },
    )
    assert resp.status_code == 401


def test_analyze_route_happy(test_client, mint_token, monkeypatch):
    canned = {
        "results": [
            {
                "underlying": "AAPL",
                "option_type": "call",
                "strike": 100.0,
                "expiry": _FUTURE,
                "quantity": 1.0,
                "contract_multiplier": 100.0,
                "days_to_expiry": 365,
                "spot": 100.0,
                "mark": 10.0,
                "iv": 0.25,
                "greeks": {"delta": 0.6, "gamma": 0.01, "theta": -0.02, "vega": 0.1, "rho": 0.05},
                "delta_notional": 6000.0,
                "market_value": 1000.0,
                "payoff": [{"price": 90.0, "pnl": -1000.0}],
                "warnings": [],
            }
        ],
        "totals": {
            "net_delta": 60.0,
            "net_gamma": 1.0,
            "net_theta": -2.0,
            "net_vega": 10.0,
            "delta_notional": 6000.0,
            "market_value": 1000.0,
            "unrealized_pnl": None,
            "contracts": 1,
        },
        "as_of": "2026-06-13",
        "warnings": [],
    }
    monkeypatch.setattr(
        "backend.app.api.v1.options.options_analytics.analyze_contracts",
        lambda *a, **k: canned,
    )
    resp = test_client.post(
        "/api/v1/options/analyze",
        json={
            "contracts": [
                {"underlying": "AAPL", "option_type": "call", "strike": 100, "expiry": _FUTURE}
            ]
        },
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["error"] is None
    data = body["data"]
    assert data["results"][0]["greeks"]["delta"] == 0.6
    assert data["totals"]["contracts"] == 1
