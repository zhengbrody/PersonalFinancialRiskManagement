"""Tests for POST /api/v1/risk/var_backtest.

Active holdings + price history monkeypatched with a synthetic series so the
VaR + breach-count + histogram math runs offline.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


def _auth(mint_token):
    return {"Authorization": f"Bearer {mint_token()}"}


@pytest.fixture
def fake_vb(monkeypatch):
    from backend.app.services import var_backtest as vb

    monkeypatch.setattr(vb, "_resolve_active_holdings", lambda user: {"AAPL": {"shares": 10}})

    # ~300 trading days of a price path with known-ish daily vol.
    idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=300)
    rng = np.random.default_rng(7)
    daily = rng.normal(0.0005, 0.012, len(idx))
    price = 100 * np.cumprod(1 + daily)
    frame = pd.DataFrame({"AAPL": price}, index=idx)
    from backend.app.services import market_data as md

    monkeypatch.setattr(md, "get_price_history", lambda tickers, *, days=550, **k: frame)
    return frame


def test_var_backtest_requires_bearer(test_client):
    assert test_client.post("/api/v1/risk/var_backtest").status_code == 401


def test_var_backtest_happy(test_client, mint_token, fake_vb):
    resp = test_client.post("/api/v1/risk/var_backtest", headers=_auth(mint_token))
    assert resp.status_code == 200, resp.json()
    d = resp.json()["data"]
    assert d["n_days"] >= 250
    assert d["var_95"] is not None and d["var_95"] > 0
    assert d["var_99"] >= d["var_95"]  # 99% VaR is deeper than 95%
    # ~5% of days breach the 95% VaR (Gaussian on near-normal data → close).
    assert 0 <= d["breaches_95"] <= d["n_days"]
    assert abs(d["expected_95"] - 0.05 * d["n_days"]) < 1e-6
    assert len(d["histogram"]) == 25
    assert sum(b["count"] for b in d["histogram"]) == d["n_days"]
    # Coverage verdicts (Kupiec + Christoffersen) ride along per level.
    for key, alpha in (("coverage_95", 0.05), ("coverage_99", 0.01)):
        cov = d[key]
        assert cov["n"] == d["n_days"]
        assert cov["alpha"] == alpha
        assert 0.0 <= cov["p_cc"] <= 1.0
        assert cov["lr_cc"] >= max(cov["lr_uc"], cov["lr_ind"]) - 1e-9
        # The verdict must be exactly the p_cc >= 0.05 rule, whatever it is.
        assert cov["passed"] == (cov["p_cc"] >= 0.05)
    # Seeded near-Gaussian returns → the 95% level should genuinely pass.
    assert d["coverage_95"]["passed"] is True


def test_var_backtest_too_short(test_client, mint_token, monkeypatch):
    from backend.app.services import var_backtest as vb

    monkeypatch.setattr(vb, "_resolve_active_holdings", lambda user: {"AAPL": {"shares": 1}})
    idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=20)
    frame = pd.DataFrame({"AAPL": np.linspace(100, 110, 20)}, index=idx)
    from backend.app.services import market_data as md

    monkeypatch.setattr(md, "get_price_history", lambda *a, **k: frame)
    resp = test_client.post("/api/v1/risk/var_backtest", headers=_auth(mint_token))
    assert resp.status_code == 422
