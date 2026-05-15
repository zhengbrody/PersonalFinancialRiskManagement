"""Regression tests for floating AI chat portfolio context."""

from __future__ import annotations

import importlib
import sys
from unittest.mock import MagicMock

import pandas as pd
import pytest


@pytest.fixture
def floating_chat_module(monkeypatch):
    fake_st = MagicMock()
    fake_st.session_state = {}
    monkeypatch.setitem(sys.modules, "streamlit", fake_st)
    sys.modules.pop("ui.floating_chat", None)
    module = importlib.import_module("ui.floating_chat")
    return module, fake_st


def test_build_portfolio_context_includes_active_holdings(monkeypatch, floating_chat_module):
    module, fake_st = floating_chat_module
    fake_st.session_state.update(
        {
            "weights": {"AAPL": 0.6, "MSFT": 0.4},
            "prices": pd.DataFrame([{"AAPL": 200.0, "MSFT": 300.0}]),
            "_portfolio_meta": {
                "portfolio_name": "Taxable",
                "portfolio_source": "user",
                "net_equity": 5000,
                "total_long": 6000,
                "margin_loan": 1000,
                "leverage": 1.2,
            },
        }
    )

    monkeypatch.setattr(
        "libs.auth.active_portfolio.get_active_holdings",
        lambda: {
            "AAPL": {
                "shares": 10,
                "avg_cost": 150,
                "account": "brokerage",
                "asset_type": "equity",
                "sector": "Technology",
            }
        },
    )
    monkeypatch.setattr("libs.auth.active_portfolio.get_active_margin_loan", lambda: 1000)
    monkeypatch.setattr(
        "libs.auth.active_portfolio.get_active_portfolio_meta",
        lambda: {"name": "Taxable", "source": "user"},
    )

    context = module._build_portfolio_context()

    assert "Current portfolio weights" in context
    assert "Active user portfolio holdings (Taxable, source=user)" in context
    assert "AAPL: shares=10" in context
    assert "weight=60.00%" in context
    assert "last_price=$200.00" in context
    assert "market_value=$2,000" in context
    assert "margin_loan=$1,000" in context
    assert "Name=Taxable" in context


def test_build_portfolio_context_asks_for_analysis_when_empty(floating_chat_module):
    module, _fake_st = floating_chat_module

    context = module._build_portfolio_context()

    assert "No portfolio data is loaded yet" in context
    assert "Refresh & Run Analysis" in context
