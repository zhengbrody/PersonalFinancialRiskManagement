"""Contract tests for ``POST /api/v1/risk/score_from_active``.

Asserts:
  * Auth required (401 without bearer).
  * Empty active portfolio → 422 ``no_active_portfolio``.
  * Market data fully missing → 422 ``no_market_data``.
  * Happy path: real prices + engine math → ScoreResponse envelope
    with overall_score and three dimensions.

Mocks the Supabase resolver and the market-data service so the test
suite stays hermetic + fast."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


@pytest.fixture
def fake_active_portfolio(monkeypatch):
    """Patch ``libs.auth.active_portfolio.get_active_holdings`` so
    score_from_active doesn't hit Supabase."""

    class _Stub:
        def __init__(self) -> None:
            self.holdings: dict[str, dict] = {}
            self.calls: list[str | None] = []

        def set(self, holdings: dict[str, dict]) -> None:
            self.holdings = holdings

        def __call__(self, access_token=None):
            self.calls.append(access_token)
            return dict(self.holdings)

    stub = _Stub()
    import libs.auth.active_portfolio as ap

    monkeypatch.setattr(ap, "get_active_holdings", stub)
    return stub


@pytest.fixture
def fake_capital(monkeypatch):
    """Patch the token-scoped cash + margin getters so we can drive the
    leverage/cash math without a real Supabase row. Defaults to a
    no-margin, no-cash account (scale = 1.0)."""

    state = {"cash_balance": 0.0, "margin_loan": 0.0}
    import libs.auth.active_portfolio as ap

    monkeypatch.setattr(
        ap,
        "get_active_capital_inputs",
        lambda access_token=None: {
            "cash_balance": state["cash_balance"],
            "contributed_capital": 0.0,
        },
    )
    monkeypatch.setattr(
        ap, "get_active_margin_loan", lambda access_token=None: state["margin_loan"]
    )
    return state


@pytest.fixture
def fake_price_history(monkeypatch):
    """Patch ``services.market_data.get_price_history``."""

    class _Stub:
        def __init__(self) -> None:
            self.frame: pd.DataFrame = pd.DataFrame()
            self.calls: list[list[str]] = []
            self.raise_on_call: Exception | None = None

        def set(self, frame: pd.DataFrame) -> None:
            self.frame = frame

        def raise_with(self, exc: Exception) -> None:
            self.raise_on_call = exc

        def __call__(self, tickers, *, days=365, cache_provider=None):
            self.calls.append(list(tickers))
            if self.raise_on_call is not None:
                raise self.raise_on_call
            cols = [t for t in tickers if t in self.frame.columns]
            return self.frame[cols] if cols else pd.DataFrame()

    stub = _Stub()
    from backend.app.services import market_data as md

    monkeypatch.setattr(md, "get_price_history", stub)
    return stub


def _make_history(tickers: list[str], days: int = 260) -> pd.DataFrame:
    """Deterministic price history — slight upward drift + per-ticker
    idiosyncratic noise so the scorer has something to work with."""
    rng = np.random.default_rng(7)
    idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=days)
    data: dict[str, np.ndarray] = {}
    for tk in tickers:
        # Random walk around 100.
        returns = rng.normal(0.0003, 0.01, days)
        levels = 100.0 * np.exp(np.cumsum(returns))
        data[tk] = levels
    return pd.DataFrame(data, index=idx)


# ── auth gate ──────────────────────────────────────────────────────


def test_requires_bearer_token(test_client):
    resp = test_client.post("/api/v1/risk/score_from_active", json={})
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "unauthorized"


# ── empty / missing data paths ─────────────────────────────────────


def test_no_active_portfolio_returns_422_with_specific_code(
    test_client, mint_token, fake_active_portfolio
):
    fake_active_portfolio.set({})  # signed-in but no holdings
    resp = test_client.post(
        "/api/v1/risk/score_from_active",
        json={},
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "no_active_portfolio"


def test_no_market_data_returns_422_with_specific_code(
    test_client, mint_token, fake_active_portfolio, fake_price_history
):
    fake_active_portfolio.set({"SPY": {"shares": 100}})
    fake_price_history.set(pd.DataFrame())  # empty → no prices
    resp = test_client.post(
        "/api/v1/risk/score_from_active",
        json={},
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    assert resp.status_code == 422
    body = resp.json()
    assert body["error"]["code"] == "no_market_data"
    assert body["error"]["details"]["tickers"] == ["SPY"]


def test_market_data_exception_is_server_error(
    test_client, mint_token, fake_active_portfolio, fake_price_history
):
    fake_active_portfolio.set({"SPY": {"shares": 100}})
    fake_price_history.raise_with(RuntimeError("yfinance refused"))
    resp = test_client.post(
        "/api/v1/risk/score_from_active",
        json={},
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    assert resp.status_code == 500
    assert resp.json()["error"]["code"] == "server_error"


# ── happy path ─────────────────────────────────────────────────────


def test_happy_path_returns_complete_score_envelope(
    test_client, mint_token, fake_active_portfolio, fake_price_history
):
    fake_active_portfolio.set(
        {
            "SPY": {"shares": 100, "avg_cost": 400.0},
            "BND": {"shares": 50, "avg_cost": 70.0},
        }
    )
    fake_price_history.set(_make_history(["BND", "SPY"]))

    token = mint_token(sub="user-real-data")
    resp = test_client.post(
        "/api/v1/risk/score_from_active",
        json={"risk_preference": 3, "risk_free_rate": 0.045},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.json()
    data = resp.json()["data"]
    assert isinstance(data["overall_score"], int)
    assert 0 <= data["overall_score"] <= 1000
    assert set(data["dimensions"].keys()) == {
        "risk_match",
        "risk_adjusted_return",
        "downside_protection",
    }
    # Real prices were used — no synthetic-data warning in the notes.
    notes = data["metrics"]["data_quality_notes"]
    assert not any("synthesised" in n for n in notes)

    # The caller's JWT was forwarded to the active-portfolio resolver
    # so Supabase RLS applied. Same security contract as /portfolios/me.
    assert fake_active_portfolio.calls == [token]


def _run_score(test_client, token, fake_active_portfolio, fake_price_history, holdings):
    fake_active_portfolio.set(holdings)
    fake_price_history.set(_make_history(sorted(holdings.keys())))
    resp = test_client.post(
        "/api/v1/risk/score_from_active",
        json={"risk_preference": 3, "risk_free_rate": 0.045},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.json()
    return resp.json()["data"]


def test_margin_amplifies_risk_in_score(
    test_client, mint_token, fake_active_portfolio, fake_price_history, fake_capital
):
    """A margin loan levers the book. The same holdings with a loan must
    report higher daily VaR than the unlevered version, and flag the
    leverage in the data-quality notes."""
    holdings = {"SPY": {"shares": 100, "avg_cost": 400.0}}
    token = mint_token(sub="user-lev")

    fake_capital["cash_balance"] = 0.0
    fake_capital["margin_loan"] = 0.0
    base = _run_score(test_client, token, fake_active_portfolio, fake_price_history, holdings)

    # ~50% loan against the equity → leverage ≈ 2× (gross/net).
    fake_capital["margin_loan"] = 0.5 * 100 * 100.0  # shares×~price (history ~100)
    levered = _run_score(
        test_client, token, fake_active_portfolio, fake_price_history, holdings
    )

    base_var = base["metrics"]["var_95_daily"]
    lev_var = levered["metrics"]["var_95_daily"]
    assert base_var is not None and lev_var is not None
    assert lev_var > base_var * 1.5  # leverage clearly amplified VaR
    assert any("everage" in n for n in levered["metrics"]["data_quality_notes"])


def test_cash_drag_lowers_risk_in_score(
    test_client, mint_token, fake_active_portfolio, fake_price_history, fake_capital
):
    """Idle cash dilutes a pure-equity book: same holdings + a cash
    balance must report lower daily VaR (cash is ~risk-free)."""
    holdings = {"SPY": {"shares": 100, "avg_cost": 400.0}}
    token = mint_token(sub="user-cash")

    fake_capital["cash_balance"] = 0.0
    fake_capital["margin_loan"] = 0.0
    base = _run_score(test_client, token, fake_active_portfolio, fake_price_history, holdings)

    # Add cash roughly equal to the equity → ~half the book is risk-free.
    fake_capital["cash_balance"] = 100 * 100.0
    with_cash = _run_score(
        test_client, token, fake_active_portfolio, fake_price_history, holdings
    )

    assert with_cash["metrics"]["var_95_daily"] < base["metrics"]["var_95_daily"]
    # cash_weight should now be a meaningful fraction of the book.
    assert with_cash["metrics"]["cash_weight"] > 0.3


def test_drops_zero_share_holdings_silently(
    test_client, mint_token, fake_active_portfolio, fake_price_history
):
    """A user can keep a 0-share row as a watchlist marker. The
    scorer shouldn't crash — it just skips the row. If every row is
    0-share we surface the specific 422."""
    fake_active_portfolio.set(
        {
            "SPY": {"shares": 0},
            "BND": {"shares": 0},
        }
    )
    fake_price_history.set(_make_history(["BND", "SPY"]))
    resp = test_client.post(
        "/api/v1/risk/score_from_active",
        json={},
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "no_priced_holdings"
