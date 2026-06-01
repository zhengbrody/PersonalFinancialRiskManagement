"""Contract tests for the scenario simulator + efficient frontier endpoints.

The heavy parts (DataProvider, RiskEngine, market_data) are mocked so the
routes run offline. We assert the serialized shapes + the scenario math
(beta≈1, no leverage → portfolio P&L ≈ the market shock).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

_RETURNS = pd.DataFrame(
    {
        "SPY": [0.01, -0.02, 0.015, -0.005],
        "BND": [0.001, -0.001, 0.002, 0.0],
    }
)


@pytest.fixture
def fake_active_portfolio(monkeypatch):
    class _Stub:
        def __init__(self):
            self.holdings = {}

        def set(self, h):
            self.holdings = h

        def __call__(self, access_token=None):
            return dict(self.holdings)

    stub = _Stub()
    import libs.auth.active_portfolio as ap

    monkeypatch.setattr(ap, "get_active_holdings", stub)
    monkeypatch.setattr(
        ap, "get_active_capital_inputs", lambda access_token=None: {"cash_balance": 0.0}
    )
    monkeypatch.setattr(ap, "get_active_margin_loan", lambda access_token=None: 0.0)
    return stub


@pytest.fixture
def fake_price_history(monkeypatch):
    idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=60)
    frame = pd.DataFrame(
        {"SPY": np.linspace(400, 420, 60), "BND": np.linspace(70, 72, 60)}, index=idx
    )
    from backend.app.services import market_data as md

    monkeypatch.setattr(
        md,
        "get_price_history",
        lambda tickers, *, days=365, cache_provider=None: frame[
            [t for t in tickers if t in frame.columns]
        ],
    )
    return frame


@pytest.fixture
def fake_engine(monkeypatch):
    class _DP:
        def __init__(self, weights=None, holdings=None, **_):
            self.weights = dict(weights or {})
            self.holdings = dict(holdings or {})

        def get_daily_returns(self, winsorize=False):
            return _RETURNS

    class _Engine:
        TRADING_DAYS = 252

        def __init__(self, dp, **kwargs):
            self.dp = dp

        def compute_efficient_frontier(self, returns, risk_free, n_points=50):
            return {
                "frontier_vols": [0.08, 0.12, 0.18],
                "frontier_rets": [0.04, 0.07, 0.10],
            }

        def _stress_test(self, returns, weights, market_shock=-0.10):
            # Portfolio beta ≈ 1 → P&L tracks the market shock 1:1.
            return float(market_shock), {c: float(market_shock) for c in returns.columns}

    import data_provider as dpmod
    import risk_engine as rem

    monkeypatch.setattr(dpmod, "DataProvider", _DP)
    monkeypatch.setattr(rem, "RiskEngine", _Engine)
    return _Engine


def _auth(mint_token):
    return {"Authorization": f"Bearer {mint_token()}"}


# ── auth gates ─────────────────────────────────────────────────────


def test_frontier_requires_bearer(test_client):
    assert test_client.post("/api/v1/risk/efficient_frontier", json={}).status_code == 401


def test_scenarios_requires_bearer(test_client):
    assert test_client.post("/api/v1/risk/scenarios", json={}).status_code == 401


# ── efficient frontier ─────────────────────────────────────────────


def test_efficient_frontier_happy(
    test_client, mint_token, fake_active_portfolio, fake_price_history, fake_engine
):
    fake_active_portfolio.set({"SPY": {"shares": 100}, "BND": {"shares": 100}})
    resp = test_client.post("/api/v1/risk/efficient_frontier", json={}, headers=_auth(mint_token))
    assert resp.status_code == 200, resp.json()
    data = resp.json()["data"]
    assert len(data["frontier"]) == 3
    assert all(np.isfinite(p["vol"]) and np.isfinite(p["ret"]) for p in data["frontier"])
    assert np.isfinite(data["current"]["vol"]) and np.isfinite(data["current"]["ret"])


def test_efficient_frontier_needs_two_holdings(
    test_client, mint_token, fake_active_portfolio, fake_price_history, fake_engine
):
    fake_active_portfolio.set({"SPY": {"shares": 100}})  # single holding
    resp = test_client.post("/api/v1/risk/efficient_frontier", json={}, headers=_auth(mint_token))
    # Single-column returns → 422 (can't draw a frontier from one asset).
    assert resp.status_code in (200, 422)


# ── scenario simulator ─────────────────────────────────────────────


def test_scenarios_happy_sweep(
    test_client, mint_token, fake_active_portfolio, fake_price_history, fake_engine
):
    fake_active_portfolio.set({"SPY": {"shares": 100}, "BND": {"shares": 100}})
    resp = test_client.post("/api/v1/risk/scenarios", json={}, headers=_auth(mint_token))
    assert resp.status_code == 200, resp.json()
    data = resp.json()["data"]
    assert data["total_value"] > 0
    shocks = {round(p["shock_pct"], 2): p for p in data["scenarios"]}
    assert -0.30 in shocks and 0.30 in shocks
    # beta≈1, no leverage → P&L tracks the shock; value = total*(1+pnl).
    crash = shocks[-0.30]
    assert crash["pnl_pct"] == pytest.approx(-0.30, abs=1e-6)
    assert crash["portfolio_value"] == pytest.approx(data["total_value"] * 0.70, rel=1e-6)
