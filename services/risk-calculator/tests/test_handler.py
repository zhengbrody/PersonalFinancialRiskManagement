"""Local unit tests for risk-calculator handler. No AWS calls."""
from __future__ import annotations

import json
import os
import sys

import numpy as np
import pytest

# Allow `import handler` from this test file when run via pytest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from handler import lambda_handler  # noqa: E402


def _make_returns(days: int = 252, n: int = 3, seed: int = 0) -> list[list[float]]:
    rng = np.random.default_rng(seed)
    return rng.normal(0, 0.012, size=(days, n)).tolist()


def _ok_event() -> dict:
    return {
        "body": json.dumps({
            "tickers": ["AAPL", "MSFT", "GOOGL"],
            "weights": {"AAPL": 0.4, "MSFT": 0.3, "GOOGL": 0.3},
            "returns": _make_returns(),
            "n_simulations": 1000,
            "horizon_days": 21,
            "confidence": 0.95,
        })
    }


def test_happy_path_returns_var_and_cvar():
    resp = lambda_handler(_ok_event(), context=None)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert "var" in body and body["var"] > 0
    assert "cvar" in body and body["cvar"] >= body["var"]
    assert body["n_assets"] == 3
    assert body["n_simulations"] == 1000


def test_invalid_json_body():
    resp = lambda_handler({"body": "not json{"}, context=None)
    assert resp["statusCode"] == 400


def test_missing_weights():
    bad = _ok_event()
    body_dict = json.loads(bad["body"])
    del body_dict["weights"]
    bad["body"] = json.dumps(body_dict)
    resp = lambda_handler(bad, context=None)
    assert resp["statusCode"] == 400


def test_ticker_misalignment_with_returns_columns():
    bad = _ok_event()
    body_dict = json.loads(bad["body"])
    body_dict["tickers"] = ["AAPL", "MSFT"]  # 2 vs 3 columns
    bad["body"] = json.dumps(body_dict)
    resp = lambda_handler(bad, context=None)
    assert resp["statusCode"] == 400
    assert "tickers" in json.loads(resp["body"])["error"]


def test_confidence_out_of_range():
    bad = _ok_event()
    body_dict = json.loads(bad["body"])
    body_dict["confidence"] = 1.5
    bad["body"] = json.dumps(body_dict)
    resp = lambda_handler(bad, context=None)
    assert resp["statusCode"] == 400


def test_n_simulations_out_of_range():
    bad = _ok_event()
    body_dict = json.loads(bad["body"])
    body_dict["n_simulations"] = 999_999
    bad["body"] = json.dumps(body_dict)
    resp = lambda_handler(bad, context=None)
    assert resp["statusCode"] == 400


def test_var_99_greater_than_var_95():
    """Sanity: deeper-tail VaR is bigger."""
    ev = _ok_event()
    body_dict = json.loads(ev["body"])
    body_dict["confidence"] = 0.95
    ev["body"] = json.dumps(body_dict)
    r95 = json.loads(lambda_handler(ev, None)["body"])

    body_dict["confidence"] = 0.99
    ev["body"] = json.dumps(body_dict)
    r99 = json.loads(lambda_handler(ev, None)["body"])

    assert r99["var"] >= r95["var"]
