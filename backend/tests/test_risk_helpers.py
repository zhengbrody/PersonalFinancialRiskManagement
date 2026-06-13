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
