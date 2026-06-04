"""Tests for POST /api/v1/risk/historical_scenarios.

Active holdings + price history are monkeypatched with a synthetic multi-year
frame so the replay math runs offline + deterministically.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


def _auth(mint_token):
    return {"Authorization": f"Bearer {mint_token()}"}


@pytest.fixture
def fake_hist(monkeypatch):
    from backend.app.services import historical_scenarios as hs

    monkeypatch.setattr(
        hs, "_resolve_active_holdings", lambda user: {"AAPL": {"shares": 10}, "SPY": {"shares": 5}}
    )

    # Daily index from 2007 → today so every episode window is covered.
    idx = pd.bdate_range(start="2007-01-01", end=pd.Timestamp.today().normalize())
    n = len(idx)
    base = np.linspace(50, 200, n)
    # A −30% decline ACROSS the COVID window (peak at start → trough at end),
    # recovering to 1.0 afterward — so the replay sees a real in-window drop.
    factor = np.ones(n)
    mask = (idx >= "2020-02-19") & (idx <= "2020-03-23")
    if mask.any():
        factor[mask] = np.linspace(1.0, 0.7, int(mask.sum()))
    frame = pd.DataFrame(
        {"AAPL": base * factor, "SPY": base * 1.5 * factor, "MSFT": base}, index=idx
    )
    from backend.app.services import market_data as md

    monkeypatch.setattr(md, "get_price_history", lambda tickers, *, days=6800, **k: frame)
    return frame


def test_historical_requires_bearer(test_client):
    assert test_client.post("/api/v1/risk/historical_scenarios").status_code == 401


def test_historical_happy(test_client, mint_token, fake_hist):
    resp = test_client.post("/api/v1/risk/historical_scenarios", headers=_auth(mint_token))
    assert resp.status_code == 200, resp.json()
    scenarios = resp.json()["data"]["scenarios"]
    labels = {s["label"] for s in scenarios}
    assert "COVID-19 crash" in labels
    covid = next(s for s in scenarios if s["label"] == "COVID-19 crash")
    # The synthetic 2020 dip → a negative portfolio return that quarter.
    assert covid["portfolio_return"] is not None and covid["portfolio_return"] < 0
    assert covid["market_return"] is not None
    assert 0 < covid["coverage"] <= 1.0


def test_historical_no_market_data(test_client, mint_token, monkeypatch):
    from backend.app.services import historical_scenarios as hs

    monkeypatch.setattr(hs, "_resolve_active_holdings", lambda user: {"AAPL": {"shares": 1}})
    from backend.app.services import market_data as md

    monkeypatch.setattr(md, "get_price_history", lambda *a, **k: pd.DataFrame())
    resp = test_client.post("/api/v1/risk/historical_scenarios", headers=_auth(mint_token))
    assert resp.status_code == 422
