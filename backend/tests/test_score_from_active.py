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

from types import SimpleNamespace

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

    state = {"cash_balance": 0.0, "margin_loan": 0.0, "contributed_capital": 0.0}
    import libs.auth.active_portfolio as ap

    monkeypatch.setattr(
        ap,
        "get_active_capital_inputs",
        lambda access_token=None: {
            "cash_balance": state["cash_balance"],
            "contributed_capital": state["contributed_capital"],
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
            self.current_prices: dict[str, float] = {}
            self.calls: list[list[str]] = []
            self.raise_on_call: Exception | None = None

        def set(self, frame: pd.DataFrame) -> None:
            self.frame = frame

        def set_current_prices(self, prices: dict[str, float]) -> None:
            self.current_prices = prices

        def raise_with(self, exc: Exception) -> None:
            self.raise_on_call = exc

        def __call__(self, tickers, *, days=365, cache_provider=None, provenance=None):
            self.calls.append(list(tickers))
            if self.raise_on_call is not None:
                raise self.raise_on_call
            cols = [t for t in tickers if t in self.frame.columns]
            if provenance is not None:
                provenance["by_ticker"] = {c: "yfinance" for c in cols}
                provenance["missing"] = [t for t in tickers if t not in cols]
            return self.frame[cols] if cols else pd.DataFrame()

        def latest(self, tickers, *, cache_provider=None, provenance=None):
            rows = []
            for t in tickers:
                if t not in self.frame.columns:
                    continue
                series = self.frame[t].dropna()
                if series.empty:
                    continue
                rows.append(
                    SimpleNamespace(
                        ticker=t,
                        price=float(self.current_prices.get(t, series.iloc[-1])),
                        as_of=pd.Timestamp(series.index[-1]).strftime("%Y-%m-%d"),
                    )
                )
            return rows

    stub = _Stub()
    from backend.app.services import market_data as md

    monkeypatch.setattr(md, "get_price_history", stub)
    monkeypatch.setattr(md, "get_latest_prices", stub.latest)
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


def test_legacy_asset_type_does_not_500(
    test_client, mint_token, fake_active_portfolio, fake_price_history
):
    """A holding stored with a legacy/unknown asset_type (e.g. 'equity', not in
    the domain's allowed set) must be normalised to public_security, not 500."""
    fake_active_portfolio.set(
        {
            "SPY": {"shares": 100, "avg_cost": 400.0, "asset_type": "equity"},
            "AAPL": {"shares": 10, "avg_cost": 150.0, "asset_type": "stock"},
        }
    )
    fake_price_history.set(_make_history(["AAPL", "SPY"]))
    resp = test_client.post(
        "/api/v1/risk/score_from_active",
        json={},
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    assert resp.status_code == 200, resp.json()
    assert isinstance(resp.json()["data"]["overall_score"], int)


def test_happy_path_returns_complete_score_envelope(
    test_client, mint_token, fake_active_portfolio, fake_price_history, fake_capital
):
    fake_capital["cash_balance"] = 1000.0
    fake_capital["margin_loan"] = 250.0
    fake_capital["contributed_capital"] = 40000.0
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

    latest_equity = 100 * float(fake_price_history.frame["SPY"].dropna().iloc[-1]) + 50 * float(
        fake_price_history.frame["BND"].dropna().iloc[-1]
    )
    previous_equity = 100 * float(fake_price_history.frame["SPY"].dropna().iloc[-2]) + 50 * float(
        fake_price_history.frame["BND"].dropna().iloc[-2]
    )
    expected_net = latest_equity + 1000.0 - 250.0
    expected_daily_pnl = latest_equity - previous_equity
    expected_daily_return = expected_daily_pnl / (previous_equity + 1000.0 - 250.0)
    assert data["metrics"]["total_value"] == pytest.approx(latest_equity + 1000.0, abs=0.01)
    assert data["metrics"]["net_equity"] == pytest.approx(expected_net, abs=0.01)
    assert data["metrics"]["daily_pnl"] == pytest.approx(expected_daily_pnl, abs=0.01)
    assert data["metrics"]["daily_return"] == pytest.approx(expected_daily_return)
    assert data["metrics"]["total_pnl"] == pytest.approx(expected_net - 40000.0, abs=0.01)
    assert data["metrics"]["total_return"] == pytest.approx((expected_net - 40000.0) / 40000.0)

    # The caller's JWT was forwarded to the active-portfolio resolver
    # so Supabase RLS applied. Same security contract as /portfolios/me.
    assert fake_active_portfolio.calls == [token]


def test_account_value_metrics_use_current_prices_for_today_pnl():
    """Daily P&L must use the current/last price vs previous close, not the
    stale daily close that backs the risk engine."""
    from backend.app.api.v1.risk import _account_value_metrics

    idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=2)
    price_frame = pd.DataFrame({"SPY": [100.0, 110.0]}, index=idx)
    metrics = _account_value_metrics(
        holdings={"SPY": {"shares": 10}},
        price_frame=price_frame,
        cash_balance=0.0,
        margin_loan=0.0,
        contributed_capital=1000.0,
        current_prices={"SPY": 95.0},
    )

    assert metrics["total_value"] == pytest.approx(950.0)
    assert metrics["daily_pnl"] == pytest.approx(-50.0)
    assert metrics["daily_return"] == pytest.approx(-50.0 / 1000.0)


def test_account_value_metrics_do_not_turn_new_positions_into_daily_pnl():
    """Positions without a prior close should contribute to current value, but
    not become artificial day-over-day gains."""
    from backend.app.api.v1.risk import _account_value_metrics

    idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=2)
    price_frame = pd.DataFrame(
        {
            "SPY": [100.0, 110.0],
            "NEW": [None, 50.0],
        },
        index=idx,
    )
    metrics = _account_value_metrics(
        holdings={"SPY": {"shares": 10}, "NEW": {"shares": 10}},
        price_frame=price_frame,
        cash_balance=0.0,
        margin_loan=0.0,
        contributed_capital=1000.0,
    )

    assert metrics["total_value"] == pytest.approx(1600.0)
    assert metrics["daily_pnl"] == pytest.approx(100.0)
    assert metrics["daily_return"] == pytest.approx(100.0 / 1500.0)
    assert metrics["total_pnl"] == pytest.approx(600.0)


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
    levered = _run_score(test_client, token, fake_active_portfolio, fake_price_history, holdings)

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
    with_cash = _run_score(test_client, token, fake_active_portfolio, fake_price_history, holdings)

    assert with_cash["metrics"]["var_95_daily"] < base["metrics"]["var_95_daily"]
    # cash_weight should now be a meaningful fraction of the book.
    assert with_cash["metrics"]["cash_weight"] > 0.3


def test_missing_avg_cost_scores_without_fabricating_pnl(
    test_client, mint_token, fake_active_portfolio, fake_price_history
):
    """A holding with no avg_cost must still score cleanly — the missing
    cost basis becomes UNKNOWN (None) at the boundary, not a fake 0 that
    would imply 100% profit. The score itself doesn't depend on cost
    basis, so this just proves the None path doesn't crash."""
    fake_active_portfolio.set({"SPY": {"shares": 100}})  # no avg_cost
    fake_price_history.set(_make_history(["SPY"]))
    resp = test_client.post(
        "/api/v1/risk/score_from_active",
        json={},
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    assert resp.status_code == 200, resp.json()
    assert 0 <= resp.json()["data"]["overall_score"] <= 1000


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


def test_option_holding_penalizes_score_and_surfaces_impact(
    test_client, mint_token, fake_active_portfolio, fake_price_history, fake_capital, monkeypatch
):
    """An uncovered short call deterministically deducts from the score and the
    `options` impact block is surfaced (base − penalty + breakdown)."""
    import backend.app.services.options_analytics as oa

    monkeypatch.setattr(
        oa,
        "analyze_contracts",
        lambda specs, **k: {
            "results": [
                {
                    "underlying": "AAPL",
                    "option_type": "call",
                    "strike": 100.0,
                    "expiry": "2027-06-18",
                    "quantity": -1.0,  # short call
                    "contract_multiplier": 100.0,
                    "days_to_expiry": 300,
                    "spot": 100.0,
                    "mark": 10.0,
                    "iv": 0.3,
                    "greeks": {
                        "delta": 0.6,
                        "gamma": 0.02,
                        "theta": -0.05,
                        "vega": 0.15,
                        "rho": 0.1,
                    },
                    "delta_notional": -6000.0,
                    "market_value": -1000.0,
                    "moneyness": "ATM",
                    "warnings": [],
                }
            ]
        },
    )
    fake_active_portfolio.set(
        {
            "SPY": {"shares": 100, "avg_cost": 400.0},
            "AAPL270618C00100000": {
                "shares": 1,
                "asset_type": "option",
                "option_type": "call",
                "option_side": "short",
                "underlying": "AAPL",
                "strike": 100,
                "expiry": "2027-06-18",
            },
        }
    )
    fake_price_history.set(_make_history(["SPY", "AAPL"]))

    resp = test_client.post(
        "/api/v1/risk/score_from_active",
        json={},
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    opt = data["options"]
    assert opt is not None
    assert opt["contracts"] == 1
    assert opt["penalty"] > 0  # short gamma + uncovered short call
    assert any(f["code"] == "uncovered_short_call" for f in opt["flags"])
    # overall_score = base_score − penalty (transparent, capped).
    assert data["overall_score"] == max(0, opt["base_score"] - opt["penalty"])


def test_no_options_no_impact_block(
    test_client, mint_token, fake_active_portfolio, fake_price_history, fake_capital
):
    fake_active_portfolio.set({"SPY": {"shares": 100, "avg_cost": 400.0}})
    fake_price_history.set(_make_history(["SPY"]))
    resp = test_client.post(
        "/api/v1/risk/score_from_active",
        json={},
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["options"] is None  # equity-only → no options block
