"""Local unit tests for options-pricer handler. No AWS calls."""
from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from handler import lambda_handler  # noqa: E402


def _ok_event(**overrides) -> dict:
    body = {
        "spot": 100.0,
        "strike": 100.0,
        "time_to_expiry_years": 1.0,
        "risk_free_rate": 0.05,
        "volatility": 0.20,
        "option_type": "call",
    }
    body.update(overrides)
    return {"body": json.dumps(body)}


def test_atm_1y_call_textbook():
    resp = lambda_handler(_ok_event(), context=None)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["price"] == pytest.approx(10.4506, abs=1e-3)
    assert 0.5 < body["delta"] < 0.7


def test_put_returns_negative_delta():
    resp = lambda_handler(_ok_event(option_type="put"), context=None)
    body = json.loads(resp["body"])
    assert body["delta"] < 0


def test_iv_solved_when_only_market_price_given():
    """Pass market_price WITHOUT volatility — handler should solve IV."""
    body = {
        "spot": 100.0, "strike": 100.0, "time_to_expiry_years": 1.0,
        "risk_free_rate": 0.05, "option_type": "call",
        "market_price": 10.4506,
    }
    resp = lambda_handler({"body": json.dumps(body)}, context=None)
    assert resp["statusCode"] == 200
    out = json.loads(resp["body"])
    assert "implied_volatility" in out
    assert out["implied_volatility"] == pytest.approx(0.20, abs=1e-4)


def test_iv_unsolvable_returns_400():
    body = {
        "spot": 100.0, "strike": 100.0, "time_to_expiry_years": 1.0,
        "risk_free_rate": 0.05, "option_type": "call",
        "market_price": 200.0,  # impossible: above S
    }
    resp = lambda_handler({"body": json.dumps(body)}, context=None)
    assert resp["statusCode"] == 400


def test_neither_volatility_nor_market_price_400():
    body = {
        "spot": 100.0, "strike": 100.0, "time_to_expiry_years": 1.0,
        "risk_free_rate": 0.05, "option_type": "call",
    }
    resp = lambda_handler({"body": json.dumps(body)}, context=None)
    assert resp["statusCode"] == 400


def test_invalid_option_type_400():
    resp = lambda_handler(_ok_event(option_type="garbage"), context=None)
    assert resp["statusCode"] == 400


def test_expiry_iso_resolves_to_T():
    """Use future date string instead of T."""
    body = {
        "spot": 100.0, "strike": 100.0,
        "expiry_iso": "2099-01-01",
        "risk_free_rate": 0.05, "volatility": 0.2, "option_type": "call",
    }
    resp = lambda_handler({"body": json.dumps(body)}, context=None)
    assert resp["statusCode"] == 200
