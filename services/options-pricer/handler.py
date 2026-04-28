"""
services/options-pricer/handler.py

POST /greeks
    Body:
        {
          "spot": 100.0,
          "strike": 105.0,
          "time_to_expiry_years": 0.25,   # OR provide expiry_iso "YYYY-MM-DD"
          "expiry_iso": "2026-08-15",     # mutually exclusive with time_to_expiry_years
          "risk_free_rate": 0.045,
          "volatility": 0.30,             # If null/omitted AND market_price given, solve IV
          "market_price": 4.25,           # optional, used to compute IV if vol omitted
          "option_type": "call"           # or "put"
        }
    Returns:
        {
          "price": 4.27,
          "delta": 0.42, "gamma": 0.025, "theta": -0.014, "vega": 0.18, "rho": 0.07,
          "implied_volatility": 0.305,    # only if computed
          "inputs_echoed": {...}
        }

Stateless, pure compute. Useful for live Greeks ribbons in the UI without
roundtripping yfinance every keystroke.
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from libs.mindmarket_core import black_scholes as bs  # noqa: E402


def _bad_request(msg: str) -> dict:
    return {
        "statusCode": 400,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({"error": msg}),
    }


def _ok(payload: dict) -> dict:
    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(payload),
    }


def lambda_handler(event: dict, context: Any) -> dict:
    body_str = event.get("body") or "{}"
    try:
        body = json.loads(body_str) if isinstance(body_str, str) else body_str
    except json.JSONDecodeError as e:
        return _bad_request(f"Invalid JSON body: {e}")

    # Required scalars
    try:
        S = float(body["spot"])
        K = float(body["strike"])
        r = float(body["risk_free_rate"])
        option_type = str(body.get("option_type", "call")).lower().strip()
    except (KeyError, ValueError, TypeError) as e:
        return _bad_request(f"Missing/invalid required field: {e}")

    if option_type not in ("call", "put"):
        return _bad_request("option_type must be 'call' or 'put'")

    # T resolution
    if "time_to_expiry_years" in body:
        try:
            T = float(body["time_to_expiry_years"])
        except (ValueError, TypeError):
            return _bad_request("time_to_expiry_years must be a number")
    elif "expiry_iso" in body:
        try:
            T = bs.time_to_expiry_years(str(body["expiry_iso"]))
        except ValueError as e:
            return _bad_request(f"Invalid expiry_iso (use YYYY-MM-DD): {e}")
    else:
        return _bad_request("Provide either 'time_to_expiry_years' or 'expiry_iso'")

    if T < 0:
        return _bad_request("Expiry is in the past (T < 0)")

    # Volatility — direct or solve from market_price
    sigma = body.get("volatility")
    market_price = body.get("market_price")
    iv_solved = None

    if sigma is None and market_price is not None:
        try:
            iv_solved = bs.implied_volatility(
                market_price=float(market_price),
                S=S, K=K, T=T, r=r, option_type=option_type,
            )
        except (ValueError, TypeError) as e:
            return _bad_request(f"Failed to compute IV: {e}")
        if iv_solved is None:
            return _bad_request(
                "Could not solve IV — market_price below intrinsic, "
                "above max bound, or solver failed"
            )
        sigma = iv_solved

    if sigma is None:
        return _bad_request("Provide either 'volatility' or 'market_price' to imply it")
    sigma = float(sigma)

    # Compute
    try:
        price = bs.bs_price(S, K, T, r, sigma, option_type)
        greeks = bs.bs_greeks(S, K, T, r, sigma, option_type)
    except ValueError as e:
        return _bad_request(str(e))

    out: dict = {
        "price": price,
        **greeks,
        "inputs_echoed": {
            "spot": S, "strike": K, "time_to_expiry_years": T,
            "risk_free_rate": r, "volatility": sigma, "option_type": option_type,
        },
    }
    if iv_solved is not None:
        out["implied_volatility"] = iv_solved

    return _ok(out)
