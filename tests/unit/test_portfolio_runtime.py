"""Tests for shared live-portfolio payload construction."""

from __future__ import annotations

import pytest

from libs.auth.portfolio_runtime import PortfolioPayloadError, build_live_portfolio_payload


def test_live_payload_uses_supabase_holdings_and_complete_meta():
    holdings = {
        "AAPL": {"shares": 2, "avg_cost": 100, "account": "taxable", "asset_type": "equity"},
        "MSFT": {"shares": 1, "account": "ira", "asset_type": "equity"},
    }

    payload = build_live_portfolio_payload(
        holdings=holdings,
        margin_loan=50,
        active_meta={"name": "User Portfolio", "source": "supabase", "id": "pf-1"},
        price_fetcher=lambda tickers: {"AAPL": 150.0, "MSFT": 300.0},
    )

    assert payload.weights == {"AAPL": 0.5, "MSFT": 0.5}
    assert payload.meta["portfolio_source"] == "supabase"
    assert payload.meta["total_long"] == pytest.approx(600.0)
    assert payload.meta["net_equity"] == pytest.approx(550.0)
    assert payload.meta["leverage"] == pytest.approx(600.0 / 550.0)
    assert payload.meta["contributed_capital"] == 0

    cost_info = payload.meta["position_cost_info"]
    assert cost_info["coverage_by_mv_pct"] == pytest.approx(0.5)
    assert cost_info["coverage_by_count_pct"] == pytest.approx(0.5)
    assert cost_info["tickers_missing_cost"] == ["MSFT"]
    assert payload.meta["position_pnl_dollar"] == pytest.approx(100.0)

    taxable = payload.meta["account_breakdown"]["taxable"]
    assert taxable["net_equity"] == pytest.approx(250.0)
    assert taxable["leverage"] == pytest.approx(300.0 / 250.0)
    assert "ira" in payload.meta["account_breakdown"]


def test_empty_active_portfolio_fails_closed():
    with pytest.raises(PortfolioPayloadError):
        build_live_portfolio_payload(
            holdings={},
            margin_loan=0,
            active_meta={"name": "No portfolio yet", "source": "empty", "id": None},
            price_fetcher=lambda tickers: {},
        )


def test_owner_default_gets_owner_capital_metadata():
    holdings = {"AAPL": {"shares": 1, "avg_cost": 100, "account": "margin", "asset_type": "equity"}}

    payload = build_live_portfolio_payload(
        holdings=holdings,
        margin_loan=0,
        active_meta={"name": "Owner default portfolio", "source": "owner_default", "id": None},
        price_fetcher=lambda tickers: {"AAPL": 200.0},
    )

    assert payload.meta["contributed_capital"] > 0
    assert payload.meta["return_on_capital_dollar"] is not None


def test_payload_normalizes_lowercase_tickers():
    payload = build_live_portfolio_payload(
        holdings={"aapl": {"shares": 1, "avg_cost": 100, "account": "taxable"}},
        margin_loan=0,
        active_meta={"name": "User Portfolio", "source": "supabase", "id": "pf-1"},
        price_fetcher=lambda tickers: {"AAPL": 150.0},
    )

    assert payload.weights == {"AAPL": 1.0}
    assert payload.meta["account_breakdown"]["taxable"]["tickers"] == ["AAPL"]
