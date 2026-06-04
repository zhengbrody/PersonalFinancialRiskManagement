"""Contract tests for /api/v1/institutions/* (SEC 13F smart money).

The legacy ``institutional_tracker`` (SEC EDGAR) is monkeypatched so the suite
runs offline. Asserts auth gates, envelope shapes, and fail-soft behaviour
(EDGAR hiccup → empty, never 500).
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _clear_cache():
    from backend.app.services import institutions as svc

    svc.reset_cache()
    yield
    svc.reset_cache()


@pytest.fixture
def fake_active(monkeypatch):
    state = {"holdings": {"NVDA": {"shares": 10}, "MSFT": {"shares": 5}}}
    import libs.auth.active_portfolio as ap

    monkeypatch.setattr(
        ap, "get_active_holdings", lambda access_token=None: dict(state["holdings"])
    )
    return state


@pytest.fixture
def fake_tracker(monkeypatch):
    import institutional_tracker as it

    monkeypatch.setattr(
        it,
        "get_smart_money_signals",
        lambda tickers: [
            {
                "ticker": "NVDA",
                "num_institutions": 18,
                "crowding_score": 0.9,
                "top_holders": ["Berkshire", "Bridgewater"],
                "signal": "HIGH_CONVICTION",
            }
        ],
    )
    monkeypatch.setattr(
        it, "get_top_institutions", lambda: [{"name": "Berkshire Hathaway", "cik": "0001067983"}]
    )
    monkeypatch.setattr(it, "get_institution_name", lambda cik: "Berkshire Hathaway")
    monkeypatch.setattr(
        it,
        "summarize_top_holdings",
        lambda cik, top_n=20: [
            {
                "ticker": "AAPL",
                "name": "Apple",
                "shares": 1000,
                "value": 2.0e8,
                "pct_of_portfolio": 40.0,
            }
        ],
    )
    monkeypatch.setattr(
        it,
        "get_institutional_changes",
        lambda cik: {
            "latest_filing_date": "2026-03-31",
            "previous_filing_date": "2025-12-31",
            "new_positions": [
                {"ticker": "GOOG", "name": "Alphabet", "shares": 500, "value": 1.0e7}
            ],
            "increased": [],
            "decreased": [],
            "exited": [],
            "summary": {"total_new": 1},
        },
    )
    return it


def _auth(mint_token):
    return {"Authorization": f"Bearer {mint_token()}"}


def test_smart_money_requires_bearer(test_client):
    assert test_client.get("/api/v1/institutions/smart_money").status_code == 401


def test_smart_money_happy(test_client, mint_token, fake_active, fake_tracker):
    resp = test_client.get("/api/v1/institutions/smart_money", headers=_auth(mint_token))
    assert resp.status_code == 200, resp.json()
    sigs = resp.json()["data"]["signals"]
    assert sigs and sigs[0]["ticker"] == "NVDA"
    assert sigs[0]["signal"] == "HIGH_CONVICTION"
    assert sigs[0]["top_holders"] == ["Berkshire", "Bridgewater"]


def test_smart_money_empty_portfolio_returns_empty(test_client, mint_token, monkeypatch):
    import libs.auth.active_portfolio as ap

    monkeypatch.setattr(ap, "get_active_holdings", lambda access_token=None: {})
    resp = test_client.get("/api/v1/institutions/smart_money", headers=_auth(mint_token))
    assert resp.status_code == 200
    assert resp.json()["data"]["signals"] == []


def test_smart_money_fail_soft_on_edgar_error(test_client, mint_token, fake_active, monkeypatch):
    import institutional_tracker as it

    def boom(tickers):
        raise RuntimeError("SEC 503")

    monkeypatch.setattr(it, "get_smart_money_signals", boom)
    resp = test_client.get("/api/v1/institutions/smart_money", headers=_auth(mint_token))
    assert resp.status_code == 200  # never 500
    assert resp.json()["data"]["signals"] == []


def test_top_institutions(test_client, mint_token, fake_tracker):
    resp = test_client.get("/api/v1/institutions/top", headers=_auth(mint_token))
    assert resp.status_code == 200, resp.json()
    insts = resp.json()["data"]["institutions"]
    assert insts[0]["cik"] == "0001067983"


def test_institution_detail(test_client, mint_token, fake_tracker):
    resp = test_client.get("/api/v1/institutions/0001067983", headers=_auth(mint_token))
    assert resp.status_code == 200, resp.json()
    data = resp.json()["data"]
    assert data["name"] == "Berkshire Hathaway"
    assert data["holdings"][0]["ticker"] == "AAPL"
    assert data["changes"]["new_positions"][0]["ticker"] == "GOOG"
