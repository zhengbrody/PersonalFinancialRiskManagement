"""HTTP contract of /risk/factor_stress (service mocked at the price seam)."""

from datetime import date

import pytest

from backend.app.services import factor_stress as svc
from backend.tests.test_factor_stress_service import HOLDINGS, _market, _prices

URL = "/api/v1/risk/factor_stress"


class _Ctx:
    portfolio_id = "p-1"
    cash_balance = 0.0
    margin_loan = 0.0
    contributed_capital = 0.0

    def __init__(self, holdings):
        self.holdings = holdings


@pytest.fixture
def client(test_client):
    return test_client


@pytest.fixture
def auth_headers(mint_token):
    return {"Authorization": f"Bearer {mint_token()}"}


@pytest.fixture
def wired(monkeypatch):
    from backend.app.api.v1 import risk
    from backend.app.services import context_cache

    # Every test recomputes: the scenario cache would otherwise serve the
    # previous test's portfolio.
    monkeypatch.setattr(
        context_cache, "cached_scenarios", lambda **kw: type("R", (), {"value": kw["producer"]()})()
    )
    monkeypatch.setattr(risk, "_resolve_active_context_or_raise", lambda user: _Ctx(HOLDINGS))
    df = _market()
    real = svc.run_factor_stress

    def run(**kw):
        return real(price_fn=_prices(df), today=date(2026, 11, 6), **kw)

    monkeypatch.setattr(svc, "run_factor_stress", run)
    return risk


def test_requires_auth(client):
    assert client.post(URL, json={}).status_code == 401


def test_happy_path_envelope(client, auth_headers, wired):
    r = client.post(URL, json={}, headers=auth_headers)
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["model_version"] == "factor-stress-v1"
    assert [f["id"] for f in data["factors"]] == [
        "equity",
        "rates",
        "credit",
        "usd",
        "oil",
        "vol",
        "gold",
    ]
    kinds = {s["kind"] for s in data["scenarios"]}
    assert kinds == {"hypothetical", "historical"}
    assert data["coverage"]["unmodelled"][0]["ticker"] == "CCC"


def test_custom_scenario_round_trip(client, auth_headers, wired):
    r = client.post(URL, json={"custom_shocks": {"equity": -0.25}}, headers=auth_headers)
    assert r.status_code == 200
    last = r.json()["data"]["scenarios"][-1]
    assert last["kind"] == "custom" and last["shocks"]["equity"] == -0.25


@pytest.mark.parametrize(
    "body",
    [
        {"custom_shocks": {"equity": -2.0}},
        {"custom_shocks": {"bitcoin": -0.5}},
        {"horizon_weeks": 3},
        {"confidence": 0.5},
    ],
)
def test_bad_input_is_rejected_before_any_work(client, auth_headers, wired, body):
    assert client.post(URL, json=body, headers=auth_headers).status_code == 422


def test_portfolio_switch_is_a_409(client, auth_headers, wired):
    r = client.post(URL, json={"expected_portfolio_id": "other"}, headers=auth_headers)
    assert r.status_code == 409 and r.json()["error"]["code"] == "portfolio_changed"


def test_nothing_to_model_is_a_422_with_a_code(client, auth_headers, wired, monkeypatch):
    monkeypatch.setattr(
        wired,
        "_resolve_active_context_or_raise",
        lambda user: _Ctx({"CCC": {"shares": 5, "asset_type": "stock"}}),
    )
    r = client.post(URL, json={}, headers=auth_headers)
    assert r.status_code == 422 and r.json()["error"]["code"] == "no_modelled_holdings"
