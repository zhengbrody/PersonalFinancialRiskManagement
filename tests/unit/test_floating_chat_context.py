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

    # Truncation lives on the deep context path (15-holding cap). The
    # short path caps at 3, so request deep explicitly here to exercise
    # the original behavior.
    context = module._build_portfolio_context(depth="deep")

    assert "... 5 smaller positions omitted from chat context for speed." in context


# ---------------------------------------------------------------------------
# Tiered-depth context tests (P1: AI prompt structure + context-size tiering)
# ---------------------------------------------------------------------------


class _FakeReport:
    """Minimal stand-in for risk_engine.RiskReport for context tests."""

    annual_return = 0.18
    annual_volatility = 0.22
    sharpe_ratio = 0.95
    var_95 = -0.034
    cvar_95 = -0.051
    max_drawdown = -0.18
    stress_loss = -0.12
    betas = {"AAPL": 1.25, "MSFT": 1.05, "NVDA": 1.85}
    component_var_pct = {"NVDA": 0.4, "AAPL": 0.35, "MSFT": 0.25}


def _seed_portfolio(monkeypatch, fake_st, *, with_report: bool = True) -> None:
    """Populate session_state + active_portfolio shims with a minimal portfolio."""
    fake_st.session_state.update(
        {
            "weights": {"AAPL": 0.4, "MSFT": 0.3, "NVDA": 0.2, "GOOG": 0.05, "META": 0.05},
            "prices": pd.DataFrame(
                [{"AAPL": 200.0, "MSFT": 300.0, "NVDA": 450.0, "GOOG": 150.0, "META": 350.0}]
            ),
            "_portfolio_meta": {
                "portfolio_name": "Main",
                "portfolio_source": "user",
                "net_equity": 50000,
                "total_long": 60000,
                "margin_loan": 10000,
                "leverage": 1.2,
            },
        }
    )
    if with_report:
        fake_st.session_state["report"] = _FakeReport()

    monkeypatch.setattr(
        "libs.auth.active_portfolio.get_active_holdings",
        lambda: {
            "AAPL": {"shares": 10, "avg_cost": 150, "account": "b", "asset_type": "equity"},
            "MSFT": {"shares": 5, "avg_cost": 250, "account": "b", "asset_type": "equity"},
            "NVDA": {"shares": 3, "avg_cost": 300, "account": "b", "asset_type": "equity"},
            "GOOG": {"shares": 2, "avg_cost": 120, "account": "b", "asset_type": "equity"},
            "META": {"shares": 1, "avg_cost": 280, "account": "b", "asset_type": "equity"},
        },
    )
    monkeypatch.setattr("libs.auth.active_portfolio.get_active_margin_loan", lambda: 10000)
    monkeypatch.setattr(
        "libs.auth.active_portfolio.get_active_portfolio_meta",
        lambda: {"name": "Main", "source": "user"},
    )


def test_short_depth_returns_compact_context(monkeypatch, floating_chat_module):
    module, fake_st = floating_chat_module
    _seed_portfolio(monkeypatch, fake_st)

    context = module._build_portfolio_context(depth="short")

    # Compact: under 800 chars vs ~1500+ for deep.
    assert len(context) < 800, f"short context too large: {len(context)} chars"
    # Short omits the heavy risk-report block entirely.
    assert "VaR95" not in context
    assert "Top betas" not in context
    # ...but still cites the top holdings so the LLM can answer
    # "what's my biggest position".
    assert "AAPL" in context


def test_deep_depth_includes_factor_betas_and_var(monkeypatch, floating_chat_module):
    module, fake_st = floating_chat_module
    _seed_portfolio(monkeypatch, fake_st)

    context = module._build_portfolio_context(depth="deep")

    assert "VaR" in context
    assert "Top betas" in context
    # The numeric beta value should be printed for at least one holding.
    assert "NVDA=1.85" in context


def test_auto_picks_short_for_casual_message(monkeypatch, floating_chat_module):
    module, fake_st = floating_chat_module
    _seed_portfolio(monkeypatch, fake_st)

    context = module._build_portfolio_context(depth="auto", user_message="hi")

    # Auto-classified short for casual "hi" → no risk report.
    assert "VaR95" not in context
    assert "Top betas" not in context


def test_auto_picks_deep_for_risk_keyword(monkeypatch, floating_chat_module):
    module, fake_st = floating_chat_module
    _seed_portfolio(monkeypatch, fake_st)

    context = module._build_portfolio_context(depth="auto", user_message="what's my VaR exposure?")

    # "var" keyword pushes auto-classification to deep.
    assert "VaR95" in context
    assert "Top betas" in context


def test_auto_picks_deep_for_long_message(monkeypatch, floating_chat_module):
    module, fake_st = floating_chat_module
    _seed_portfolio(monkeypatch, fake_st)

    long_message = (
        "I am wondering about my overall portfolio positioning and how it might react "
        "to various market conditions over the next several months."
    )
    assert len(long_message) > 80
    context = module._build_portfolio_context(depth="auto", user_message=long_message)

    # Long messages get the full context even without risk keywords.
    assert "VaR95" in context


def test_no_portfolio_state_returns_clean_empty_string(floating_chat_module):
    """Empty session_state should produce a graceful no-portfolio message,
    not a stack trace or a half-populated context."""
    module, _fake_st = floating_chat_module

    for depth in ("short", "deep", "auto"):
        context = module._build_portfolio_context(depth=depth)
        assert "No portfolio data is loaded yet" in context
        # Sanity: no half-rendered numeric formatting from missing data.
        assert "$0" not in context.split("No portfolio data")[0]


def test_classify_context_depth_keywords_and_length(floating_chat_module):
    """Direct unit test on the classifier so the heuristic doesn't drift."""
    module, _fake_st = floating_chat_module

    assert module._classify_context_depth("hi") == "short"
    assert module._classify_context_depth("what's NVDA today") == "short"
    assert module._classify_context_depth("show my VaR") == "deep"
    assert module._classify_context_depth("rebalance ideas?") == "deep"
    assert module._classify_context_depth("a" * 81) == "deep"
    assert module._classify_context_depth("") == "short"


def test_response_budget_respects_explicit_depth(floating_chat_module):
    module, _fake_st = floating_chat_module

    assert module._response_budget("anything", depth="short") == 350
    assert module._response_budget("anything", depth="deep") == 800
    # Auto path preserves the legacy behavior tested above.
    assert module._response_budget("plain question", depth="auto") == 500
