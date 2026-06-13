"""Unit tests for the option-aware holding helpers in ``api/v1/risk.py``.

PR1 of the options feature adds ``"option"`` as a recognized asset type and
excludes option contracts (keyed by synthetic OCC symbols) from the equity
price-fetch paths so they neither 500 nor get mispriced as equities.
"""

from __future__ import annotations

from backend.app.api.v1.risk import (
    _is_option_holding,
    _normalize_asset_type,
    _priceable_tickers,
)


def test_normalize_recognizes_option():
    assert _normalize_asset_type("option") == "option"
    assert _normalize_asset_type("Option") == "option"
    assert _normalize_asset_type("call") == "option"
    assert _normalize_asset_type("put") == "option"


def test_normalize_unchanged_for_existing_types():
    assert _normalize_asset_type("public_security") == "public_security"
    assert _normalize_asset_type("cash") == "cash"
    assert _normalize_asset_type("equity") == "public_security"  # legacy fallback
    assert _normalize_asset_type(None) == "public_security"


def test_is_option_holding():
    assert _is_option_holding({"asset_type": "option", "shares": 1}) is True
    assert _is_option_holding({"asset_type": "public_security"}) is False
    assert _is_option_holding({}) is False
    assert _is_option_holding(None) is False


def test_priceable_tickers_excludes_options():
    holdings = {
        "AAPL": {"shares": 10, "asset_type": "public_security"},
        "SPY": {"shares": 5},  # no asset_type → equity by default
        "AAPL260116C00150000": {
            "shares": 2,
            "asset_type": "option",
            "underlying": "AAPL",
            "strike": 150,
            "expiry": "2026-01-16",
            "option_type": "call",
        },
    }
    assert _priceable_tickers(holdings) == ["AAPL", "SPY"]


# ── PR3: option delta-equivalent overlay ──────────────────────────────────────

import pandas as pd  # noqa: E402

from backend.app.api.v1.risk import (  # noqa: E402
    _apply_option_overlay,
    _augment_holdings_with_deltas,
    _compute_weights,
    _option_delta_equiv_shares,
    _option_specs_from_holdings,
    _option_underlyings,
)

_OPT = {
    "shares": 2,
    "avg_cost": 5.0,
    "asset_type": "option",
    "option_type": "call",
    "underlying": "AAPL",
    "strike": 150,
    "expiry": "2027-01-15",
    "contract_multiplier": 100,
}


def test_option_specs_and_underlyings():
    holdings = {"AAPL": {"shares": 10}, "AAPL270115C00150000": dict(_OPT)}
    specs = _option_specs_from_holdings(holdings)
    assert len(specs) == 1
    assert specs[0].underlying == "AAPL" and specs[0].quantity == 2
    assert _option_underlyings(holdings) == ["AAPL"]


def test_option_specs_skip_incomplete():
    holdings = {
        "BAD": {"shares": 1, "asset_type": "option", "option_type": "put"}
    }  # no strike/expiry
    assert _option_specs_from_holdings(holdings) == []


def test_delta_equiv_shares_uses_analytics(monkeypatch):
    def fake_analyze(specs, **kw):
        return {
            "results": [
                {
                    "underlying": "AAPL",
                    "quantity": 2,
                    "contract_multiplier": 100,
                    "greeks": {"delta": 0.6, "gamma": 0, "theta": 0, "vega": 0, "rho": 0},
                }
            ]
        }

    import backend.app.services.options_analytics as oa

    monkeypatch.setattr(oa, "analyze_contracts", fake_analyze)
    out = _option_delta_equiv_shares(_option_specs_from_holdings({"X": dict(_OPT)}))
    assert out == {"AAPL": 0.6 * 2 * 100}  # 120 equity-equivalent shares


def test_delta_equiv_shares_failsoft(monkeypatch):
    import backend.app.services.options_analytics as oa

    monkeypatch.setattr(
        oa, "analyze_contracts", lambda *a, **k: (_ for _ in ()).throw(RuntimeError)
    )
    assert _option_delta_equiv_shares(_option_specs_from_holdings({"X": dict(_OPT)})) == {}


def test_augment_clamps_net_short():
    holdings = {"AAPL": {"shares": 10}}
    aug, clamped = _augment_holdings_with_deltas(holdings, ["AAPL"], {"AAPL": -12000.0})
    assert aug["AAPL"]["shares"] == 0.0  # 10 − 12000 clamped to 0
    assert clamped == ["AAPL"]


def test_augment_adds_long_exposure():
    aug, clamped = _augment_holdings_with_deltas(
        {"AAPL": {"shares": 10}}, ["AAPL"], {"AAPL": 120.0}
    )
    assert aug["AAPL"]["shares"] == 130.0
    assert clamped == []


def _frame(**cols):
    idx = pd.bdate_range(end="2027-01-01", periods=5)
    return pd.DataFrame({k: v for k, v in cols.items()}, index=idx)


def test_apply_overlay_augments_weights_and_concentration(monkeypatch):
    def fake_analyze(specs, **kw):
        return {
            "results": [
                {
                    "underlying": "AAPL",
                    "quantity": 2,
                    "contract_multiplier": 100,
                    "greeks": {"delta": 0.6, "gamma": 0, "theta": 0, "vega": 0, "rho": 0},
                }
            ]
        }

    import backend.app.services.options_analytics as oa

    monkeypatch.setattr(oa, "analyze_contracts", fake_analyze)
    holdings = {"AAPL": {"shares": 10}, "MSFT": {"shares": 5}, "AAPL270115C00150000": dict(_OPT)}
    price_frame = _frame(AAPL=[100, 100, 100, 100, 100], MSFT=[200, 200, 200, 200, 200])
    base_w, base_mv = _compute_weights(holdings, price_frame, tickers=["AAPL", "MSFT"])
    w, h_eng, conc, note = _apply_option_overlay(
        holdings, price_frame, ["AAPL", "MSFT"], base_w, base_mv
    )

    # AAPL exposure should rise (10 + 120 delta-equiv shares × $100 = $13,000).
    assert conc["AAPL"] == 13000.0
    assert w["AAPL"] > base_w["AAPL"]  # option lifted AAPL's weight
    assert h_eng["AAPL"]["shares"] == 130.0
    assert note and "delta-equivalent" in note


def test_apply_overlay_noop_without_options():
    holdings = {"AAPL": {"shares": 10}}
    price_frame = _frame(AAPL=[100, 100, 100, 100, 100])
    base_w, base_mv = _compute_weights(holdings, price_frame, tickers=["AAPL"])
    w, h_eng, conc, note = _apply_option_overlay(holdings, price_frame, ["AAPL"], base_w, base_mv)
    assert w == base_w and conc == base_mv and note is None and h_eng is holdings


def test_option_specs_short_leg_negates_quantity():
    holdings = {
        "AAPL270115C00150000": {**_OPT, "option_side": "long", "shares": 1},
        "AAPL270115C00170000": {**_OPT, "option_side": "short", "shares": 2, "strike": 170},
    }
    specs = {s.strike: s for s in _option_specs_from_holdings(holdings)}
    assert specs[150.0].quantity == 1.0  # long
    assert specs[170.0].quantity == -2.0  # short → negative


def test_option_specs_default_long_when_no_side():
    spec = _option_specs_from_holdings({"K": dict(_OPT)})[0]  # no option_side
    assert spec.quantity == 2.0  # defaults to long (positive)
