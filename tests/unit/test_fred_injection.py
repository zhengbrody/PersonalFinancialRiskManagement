"""Tests for FRED macroeconomic release injection.

Covers:
1. fetch_macro_releases returns rows when FRED is reachable
2. fetch_macro_releases returns [] (no exception) when FRED errors
3. build_ai_risk_briefing renders a "Macroeconomic Releases" section
   when macro_releases is provided
4. build_ai_risk_briefing OMITS the section when macro_releases is None
5. The floating chat's _build_portfolio_context() includes the macro
   block when the helper returns rows
6. The floating chat silently skips the macro block when the helper
   raises (chat must not fail because FRED is down)
"""

from __future__ import annotations

import importlib
import sys
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

import market_intelligence as mi
from risk_engine import RiskReport

# Sample CSV body matching the FRED graph CSV endpoint shape.
_SAMPLE_CPI_CSV = (
    "observation_date,CPIAUCSL\n"
    "2024-01-01,300.0\n"
    "2024-02-01,301.0\n"
    "2024-03-01,302.0\n"
    "2024-04-01,303.0\n"
    "2024-05-01,304.0\n"
    "2024-06-01,305.0\n"
    "2024-07-01,306.0\n"
    "2024-08-01,307.0\n"
    "2024-09-01,308.0\n"
    "2024-10-01,309.0\n"
    "2024-11-01,310.0\n"
    "2024-12-01,311.0\n"
    "2025-01-01,309.6\n"  # +3.2% YoY vs 300.0
)


def _reset_memo():
    """Clear module-level memo so tests don't leak through each other.

    Also clears the st.cache_data wrapper if streamlit decided to wrap
    fetch_macro_releases earlier in the test session.
    """
    mi._FRED_MEMO.clear()
    try:
        import streamlit as _st  # noqa: F401

        _st.cache_data.clear()
    except Exception:
        pass


def _make_mock_response(text: str, status: int = 200):
    resp = MagicMock()
    resp.text = text
    resp.status_code = status
    resp.raise_for_status = MagicMock()
    return resp


# ──────────────────────────────────────────────────────────────
# 1. Success path
# ──────────────────────────────────────────────────────────────
def test_fetch_macro_releases_returns_rows_on_success(monkeypatch):
    _reset_memo()

    def _fake_get(url, timeout=5, **kw):
        # Every series returns the same CSV body but renamed to that series id.
        # Extract the requested id from the URL.
        sid = url.split("id=")[-1]
        body = _SAMPLE_CPI_CSV.replace("CPIAUCSL", sid)
        return _make_mock_response(body)

    monkeypatch.setattr(mi._http_session, "get", _fake_get)

    rows = mi.fetch_macro_releases()

    assert isinstance(rows, list)
    assert len(rows) >= 1
    # Every row must carry the spec-mandated keys
    for row in rows:
        assert "Series" in row
        assert "Latest" in row
        assert "Date" in row
        assert "Source" in row
        assert "fred_id" in row
        assert row["Source"] == "FRED"

    # The CPI row should show its YoY in the Latest field
    cpi = [r for r in rows if r["fred_id"] == "CPIAUCSL"]
    assert cpi, "CPI series should be present in the result"
    assert "%" in cpi[0]["Latest"]
    assert cpi[0]["Series"] == "CPI YoY"


# ──────────────────────────────────────────────────────────────
# 2. Failure path
# ──────────────────────────────────────────────────────────────
def test_fetch_macro_releases_returns_empty_on_failure(monkeypatch):
    _reset_memo()

    def _boom(*a, **kw):
        raise ConnectionError("FRED is down")

    monkeypatch.setattr(mi._http_session, "get", _boom)

    rows = mi.fetch_macro_releases()

    assert rows == [], (
        "fetch_macro_releases must swallow network errors -- got " f"{len(rows)} rows instead of []"
    )


# ──────────────────────────────────────────────────────────────
# 3. Briefing renders the section
# ──────────────────────────────────────────────────────────────
def test_build_ai_risk_briefing_includes_macro_releases_section():
    report = RiskReport()
    weights = {"AAPL": 0.5, "MSFT": 0.5}

    prompt = mi.build_ai_risk_briefing(
        report=report,
        weights=weights,
        vix_info={"current": 18.0, "level": "Normal", "change": 0.01},
        yield_analysis={},
        fundamentals_df=pd.DataFrame(),
        macro_news=[],
        sentiment_data=None,
        macro_releases=[
            {
                "Series": "CPI YoY",
                "Latest": "3.20%",
                "Date": "2026-04-01",
                "fred_id": "CPIAUCSL",
                "Source": "FRED",
            }
        ],
        lang="en",
    )

    assert "Macroeconomic Releases" in prompt
    assert "CPI YoY" in prompt
    assert "3.20%" in prompt
    assert "2026-04-01" in prompt
    assert "CPIAUCSL" in prompt


# ──────────────────────────────────────────────────────────────
# 4. Briefing omits the section when not provided
# ──────────────────────────────────────────────────────────────
def test_build_ai_risk_briefing_omits_section_when_none():
    report = RiskReport()
    weights = {"AAPL": 1.0}

    prompt = mi.build_ai_risk_briefing(
        report=report,
        weights=weights,
        vix_info={"current": 18.0, "level": "Normal", "change": None},
        yield_analysis={},
        fundamentals_df=pd.DataFrame(),
        macro_news=[],
        sentiment_data=None,
        macro_releases=None,
        lang="en",
    )

    assert "Macroeconomic Releases" not in prompt


# ──────────────────────────────────────────────────────────────
# 5/6. Floating chat context — install fake streamlit
# ──────────────────────────────────────────────────────────────
@pytest.fixture
def floating_chat_module(monkeypatch):
    fake_st = MagicMock()
    fake_st.session_state = {}
    monkeypatch.setitem(sys.modules, "streamlit", fake_st)
    sys.modules.pop("ui.floating_chat", None)
    module = importlib.import_module("ui.floating_chat")
    return module, fake_st


def test_chat_context_includes_macro_when_available(monkeypatch, floating_chat_module):
    module, fake_st = floating_chat_module
    fake_st.session_state.update({"weights": {"AAPL": 1.0}})

    # Avoid touching the real active-portfolio loader.
    monkeypatch.setattr("libs.auth.active_portfolio.get_active_holdings", lambda: {}, raising=False)
    monkeypatch.setattr(
        "libs.auth.active_portfolio.get_active_margin_loan", lambda: 0, raising=False
    )
    monkeypatch.setattr(
        "libs.auth.active_portfolio.get_active_portfolio_meta", lambda: {}, raising=False
    )

    fake_rows = [
        {
            "Series": "CPI YoY",
            "Latest": "3.20%",
            "Date": "2026-04-01",
            "fred_id": "CPIAUCSL",
            "Source": "FRED",
        },
        {
            "Series": "Unemployment Rate",
            "Latest": "4.10%",
            "Date": "2026-04-01",
            "fred_id": "UNRATE",
            "Source": "FRED",
        },
    ]
    with patch("market_intelligence.fetch_macro_releases", return_value=fake_rows):
        context = module._build_portfolio_context()

    assert "CPI YoY" in context
    assert "Unemployment Rate" in context
    assert "3.20%" in context
    assert "4.10%" in context
    assert "Recent macro releases" in context


def test_chat_context_silently_skips_macro_when_fred_down(monkeypatch, floating_chat_module):
    module, fake_st = floating_chat_module
    fake_st.session_state.update({"weights": {"AAPL": 1.0}})

    monkeypatch.setattr("libs.auth.active_portfolio.get_active_holdings", lambda: {}, raising=False)
    monkeypatch.setattr(
        "libs.auth.active_portfolio.get_active_margin_loan", lambda: 0, raising=False
    )
    monkeypatch.setattr(
        "libs.auth.active_portfolio.get_active_portfolio_meta", lambda: {}, raising=False
    )

    def _boom():
        raise RuntimeError("FRED really is down")

    with patch("market_intelligence.fetch_macro_releases", side_effect=_boom):
        # Must NOT raise -- the chat keeps working even with FRED down.
        context = module._build_portfolio_context()

    assert "Recent macro releases" not in context
    # Weights block should still be present so the rest of the function ran.
    assert "Current portfolio weights" in context
