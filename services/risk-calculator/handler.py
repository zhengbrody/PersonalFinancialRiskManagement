"""
services/risk-calculator/handler.py

POST /var
    Body:
        {
          "weights":   {"AAPL": 0.4, "MSFT": 0.3, "GOOGL": 0.3},
          "returns":   [[0.001, 0.002, -0.001], ...],   # T x N matrix, ROW PER DAY
          "tickers":   ["AAPL", "MSFT", "GOOGL"],       # column order for `returns`
          "n_simulations": 10000,                       # optional
          "horizon_days":  21,                          # optional
          "confidence":    0.95                         # optional, in [0.5, 0.999]
        }
    Returns:
        {"var": 0.0473, "cvar": 0.0581, "n_assets": 3, "n_simulations": 10000}

Why this shape: client (Streamlit on EC2 in Phase 1, browser SPA in Phase 4+)
already has the prices and computed returns. We avoid round-tripping price
data through Lambda — keeps payload under API GW's 10 MB limit and avoids
the price-cache lambda becoming a hot dependency for every VaR call.

Pure compute. No DynamoDB read here. Cold start dominated by scipy import.
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any

import numpy as np
import pandas as pd

# libs/ is bind-mounted (or COPY'd) into /var/task/libs at image build time.
# abspath FIRST — under pytest discovery __file__ can be relative,
# in which case 3x dirname collapses to "" instead of the repo root.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from libs.mindmarket_core import var as mv  # noqa: E402


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
    """API Gateway proxy integration entrypoint."""
    body_str = event.get("body") or "{}"
    try:
        body = json.loads(body_str) if isinstance(body_str, str) else body_str
    except json.JSONDecodeError as e:
        return _bad_request(f"Invalid JSON body: {e}")

    weights_dict = body.get("weights")
    returns_matrix = body.get("returns")
    tickers = body.get("tickers")

    if not isinstance(weights_dict, dict):
        return _bad_request("'weights' must be a dict {ticker: weight}")
    if not isinstance(returns_matrix, list) or not returns_matrix:
        return _bad_request("'returns' must be a non-empty 2D list (T x N)")
    if not isinstance(tickers, list) or not tickers:
        return _bad_request("'tickers' must be a non-empty list of column names")

    # Validate alignment
    if len(tickers) != len(returns_matrix[0]):
        return _bad_request(
            f"tickers length ({len(tickers)}) must equal "
            f"returns columns ({len(returns_matrix[0])})"
        )
    for tk in tickers:
        if tk not in weights_dict:
            return _bad_request(f"weight missing for ticker '{tk}'")

    n_simulations = int(body.get("n_simulations", 10_000))
    horizon_days = int(body.get("horizon_days", 21))
    confidence = float(body.get("confidence", 0.95))

    if not (0.5 <= confidence <= 0.999):
        return _bad_request(f"confidence must be in [0.5, 0.999], got {confidence}")
    if not (100 <= n_simulations <= 50_000):
        return _bad_request(f"n_simulations must be in [100, 50000], got {n_simulations}")
    if not (1 <= horizon_days <= 252):
        return _bad_request(f"horizon_days must be in [1, 252], got {horizon_days}")

    # Build numpy artifacts
    try:
        returns_df = pd.DataFrame(returns_matrix, columns=tickers, dtype=float)
        weights_arr = np.array([float(weights_dict[tk]) for tk in tickers])
    except (ValueError, KeyError) as e:
        return _bad_request(f"Failed to parse returns/weights: {e}")

    # Compute
    cov_daily = mv.ewma_covariance(returns_df)
    portfolio_returns = mv.monte_carlo_returns(
        returns_df,
        weights_arr,
        cov_daily,
        n_simulations=n_simulations,
        horizon_days=horizon_days,
    )
    var_value, cvar_value = mv.percentile_var_cvar(portfolio_returns, confidence)

    return _ok({
        "var": var_value,
        "cvar": cvar_value,
        "confidence": confidence,
        "n_assets": len(tickers),
        "n_simulations": n_simulations,
        "horizon_days": horizon_days,
    })
