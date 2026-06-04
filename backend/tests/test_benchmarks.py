"""Tests for GET /api/v1/risk/benchmarks (public reference context).

The price fetch is monkeypatched so CI stays offline. Public + fail-soft.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


@pytest.fixture(autouse=True)
def _reset_cache():
    from backend.app.services import benchmarks as bm

    bm.reset_cache()
    yield
    bm.reset_cache()


@pytest.fixture
def fake_prices(monkeypatch):
    idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=120)
    # SPY drifts up with more vol; AGG is calmer — enough points for stats.
    rng = np.linspace(0, 1, 120)
    frame = pd.DataFrame({"SPY": 400 * (1 + 0.15 * rng), "AGG": 100 * (1 + 0.03 * rng)}, index=idx)
    from backend.app.services import market_data as md

    monkeypatch.setattr(md, "get_price_history", lambda tickers, *, days=365, **k: frame)
    return frame


def test_benchmarks_public_and_shaped(test_client, fake_prices):
    resp = test_client.get("/api/v1/risk/benchmarks")
    assert resp.status_code == 200, resp.json()
    data = resp.json()["data"]
    names = {b["name"] for b in data["benchmarks"]}
    assert "S&P 500 (SPY)" in names
    assert "Balanced 60/40" in names
    spy = next(b for b in data["benchmarks"] if b["name"] == "S&P 500 (SPY)")
    assert spy["annual_volatility"] is not None
    assert data["as_of"]


def test_benchmarks_fail_soft(test_client, monkeypatch):
    from backend.app.services import market_data as md

    def boom(*a, **k):
        raise RuntimeError("yfinance down")

    monkeypatch.setattr(md, "get_price_history", boom)
    resp = test_client.get("/api/v1/risk/benchmarks")
    assert resp.status_code == 200  # never 500
    assert resp.json()["data"]["benchmarks"] == []
