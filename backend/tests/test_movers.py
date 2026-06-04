"""Contract tests for ``GET /api/v1/macro/movers``.

Hermetic: the legacy ``volatility_scanner`` functions are monkeypatched so CI
never touches yfinance. Public endpoint, fail-soft (a dead upstream → empty
list, never 500).
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _reset_cache():
    from backend.app.services import market_movers as mm

    mm.reset_cache()
    yield
    mm.reset_cache()


@pytest.fixture
def fake_scanner(monkeypatch):
    import volatility_scanner as vs

    monkeypatch.setattr(
        vs,
        "get_sector_performance",
        lambda: [
            {"sector": "Technology", "ticker": "XLK", "change_pct": 1.2, "ytd_return": 0.18},
            {"sector": "Energy", "ticker": "XLE", "change_pct": -0.8, "ytd_return": 0.05},
        ],
    )
    monkeypatch.setattr(
        vs,
        "scan_sp500_movers",
        lambda top_n=20: {
            "top_gainers": [
                {
                    "ticker": "NVDA",
                    "name": "NVIDIA",
                    "change_pct": 4.1,
                    "close": 120.0,
                    "avg_volume_ratio": 1.3,
                }
            ],
            "top_losers": [
                {
                    "ticker": "INTC",
                    "name": "Intel",
                    "change_pct": -3.2,
                    "close": 30.0,
                    "avg_volume_ratio": 1.1,
                }
            ],
            "highest_volume": [
                {
                    "ticker": "TSLA",
                    "name": "Tesla",
                    "change_pct": 2.0,
                    "close": 250.0,
                    "avg_volume_ratio": 3.4,
                }
            ],
            "scan_date": "2026-06-04",
        },
    )
    return vs


def test_movers_is_public(test_client, fake_scanner):
    # No bearer required.
    resp = test_client.get("/api/v1/macro/movers")
    assert resp.status_code == 200, resp.json()
    data = resp.json()["data"]
    assert data["scan_date"] == "2026-06-04"
    assert data["sectors"][0]["sector"] == "Technology"
    assert data["top_gainers"][0]["ticker"] == "NVDA"
    assert data["top_losers"][0]["ticker"] == "INTC"
    # legacy "highest_volume" surfaced as "unusual_volume"
    assert data["unusual_volume"][0]["ticker"] == "TSLA"


def test_movers_fail_soft(test_client, monkeypatch):
    import volatility_scanner as vs

    def boom(*a, **k):
        raise RuntimeError("yfinance down")

    monkeypatch.setattr(vs, "get_sector_performance", boom)
    monkeypatch.setattr(vs, "scan_sp500_movers", boom)
    resp = test_client.get("/api/v1/macro/movers")
    assert resp.status_code == 200  # never 500
    data = resp.json()["data"]
    assert data["sectors"] == []
    assert data["top_gainers"] == []
