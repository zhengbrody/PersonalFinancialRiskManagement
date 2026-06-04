"""Contract tests for ``POST /api/v1/quant/attribution``.

The active-holdings resolver, MV-weight helper, market data, and the legacy
``get_attribution_summary`` are all monkeypatched so the route runs offline.
"""

from __future__ import annotations

import pandas as pd
import pytest


def _auth(mint_token):
    return {"Authorization": f"Bearer {mint_token()}"}


@pytest.fixture
def fake_attr(monkeypatch):
    from backend.app.services import quant_attribution as qa

    monkeypatch.setattr(
        qa, "_resolve_active_holdings", lambda user: {"AAPL": {"shares": 10}, "MSFT": {"shares": 5}}
    )

    from backend.app.services import market_data as md

    # weights are now derived from this frame's latest row (single fetch).
    frame = pd.DataFrame({"AAPL": [1.0, 1.1, 1.2], "MSFT": [2.0, 2.1, 2.2], "SPY": [3.0, 3.1, 3.2]})
    monkeypatch.setattr(md, "get_price_history", lambda tickers, *, days=730, **k: frame)

    import performance_attribution as pa

    monkeypatch.setattr(
        pa,
        "get_attribution_summary",
        lambda w, returns, benchmark_ticker="SPY": {
            "tracking_error": 0.04,
            "information_ratio": 0.6,
            "hit_ratio": 0.55,
            "active_return_annual": 0.03,
            "brinson": {
                "total_active_return": 0.03,
                "allocation_effect": 0.01,
                "selection_effect": 0.02,
                "interaction_effect": 0.0,
                "sector_detail": pd.DataFrame(
                    [
                        {
                            "sector": "Technology",
                            "weight_diff": 0.2,
                            "allocation_effect": 0.01,
                            "selection_effect": 0.02,
                            "total_effect": 0.03,
                        }
                    ]
                ),
            },
            "factor": {
                "alpha": 0.02,
                "r_squared": 0.88,
                "residual_return": 0.005,
                "factor_betas": {"SPY": 1.05, "QQQ": 0.3},
                "factor_contributions": {"SPY": 0.04, "QQQ": 0.01},
            },
        },
    )
    return qa


def test_attribution_requires_bearer(test_client):
    assert test_client.post("/api/v1/quant/attribution").status_code == 401


def test_attribution_happy(test_client, mint_token, fake_attr):
    resp = test_client.post("/api/v1/quant/attribution", headers=_auth(mint_token))
    assert resp.status_code == 200, resp.json()
    data = resp.json()["data"]
    assert data["information_ratio"] == 0.6
    assert data["brinson"]["allocation_effect"] == 0.01
    assert data["brinson"]["sector_detail"][0]["sector"] == "Technology"
    assert data["factor"]["factor_betas"]["SPY"] == 1.05


def test_attribution_needs_two_holdings(test_client, mint_token, monkeypatch):
    from backend.app.services import quant_attribution as qa

    monkeypatch.setattr(qa, "_resolve_active_holdings", lambda user: {"AAPL": {"shares": 10}})
    resp = test_client.post("/api/v1/quant/attribution", headers=_auth(mint_token))
    assert resp.status_code == 422
