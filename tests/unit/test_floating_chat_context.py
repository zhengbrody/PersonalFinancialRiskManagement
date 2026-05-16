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


def test_response_budget_defaults_fast_and_expands_for_deep_dive(floating_chat_module):
    module, _fake_st = floating_chat_module

    assert module._response_budget("what is my VaR?") == 500
    assert module._response_budget("give me a detailed hedge scenario") == 800


def test_chat_call_llm_stream_returns_generator(monkeypatch, floating_chat_module):
    """Perf fix: Claude streaming should return a generator so that
    st.write_stream can render tokens as they arrive. Regression guard:
    if someone collapses _chat_call_llm back to a single-shot
    .messages.create call, this test fails."""
    module, fake_st = floating_chat_module

    # Admin mode → skip quota gate.
    monkeypatch.setenv("MINDMARKET_ADMIN_MODE", "true")
    fake_st.session_state.update(
        {
            "_model_provider": "Anthropic Claude",
            "_api_key_input": "sk-ant-fake",
        }
    )

    # Stub anthropic client so we never make a real API call.
    class _FakeStream:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        @property
        def text_stream(self):
            yield "Hello "
            yield "world"

    class _FakeMessages:
        def stream(self, **kwargs):
            return _FakeStream()

    class _FakeAnthropic:
        def __init__(self, api_key):
            self.messages = _FakeMessages()

    fake_anthropic = MagicMock()
    fake_anthropic.Anthropic = _FakeAnthropic
    monkeypatch.setitem(sys.modules, "anthropic", fake_anthropic)

    result = module._chat_call_llm(
        prompt="test",
        system="sys",
        max_tokens=300,
        stream=True,
    )

    # Must be an iterator/generator, not a string.
    assert hasattr(result, "__iter__")
    assert not isinstance(result, str)
    chunks = list(result)
    assert "".join(chunks) == "Hello world"


def test_build_portfolio_context_truncates_smaller_positions(monkeypatch, floating_chat_module):
    module, fake_st = floating_chat_module
    tickers = [f"T{i:02d}" for i in range(20)]
    fake_st.session_state.update(
        {
            "weights": {ticker: 1 / len(tickers) for ticker in tickers},
            "prices": pd.DataFrame([{ticker: float(100 - i) for i, ticker in enumerate(tickers)}]),
            "_portfolio_meta": {"portfolio_name": "Many", "portfolio_source": "user"},
        }
    )

    monkeypatch.setattr(
        "libs.auth.active_portfolio.get_active_holdings",
        lambda: {ticker: {"shares": i + 1, "avg_cost": 10} for i, ticker in enumerate(tickers)},
    )
    monkeypatch.setattr("libs.auth.active_portfolio.get_active_margin_loan", lambda: 0)
    monkeypatch.setattr(
        "libs.auth.active_portfolio.get_active_portfolio_meta",
        lambda: {"name": "Many", "source": "user"},
    )

    context = module._build_portfolio_context()

    assert "... 5 smaller positions omitted from chat context for speed." in context
