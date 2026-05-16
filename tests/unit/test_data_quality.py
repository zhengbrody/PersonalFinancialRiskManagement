"""Tests for libs/data_quality.py — pure dataclass logic + Streamlit-mocked render."""

from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from libs.data_quality import (
    DataQualityReport,
    DataSource,
    overview_report,
    quant_lab_report,
    render_data_quality_panel,
    risk_report,
    trading_floor_report,
)

# ── Fixtures ────────────────────────────────────────────────


@pytest.fixture
def fake_streamlit(monkeypatch):
    """Provide a fake ``streamlit`` module with a dict-style session_state.

    Mirrors the pattern in tests/unit/test_auth_session.py.
    """
    fake_st = MagicMock()
    fake_st.session_state = {}
    fake_st.secrets.get.return_value = ""
    # The expander returned by st.expander() must support `with ...:` usage.
    fake_expander = MagicMock()
    fake_expander.__enter__ = MagicMock(return_value=fake_expander)
    fake_expander.__exit__ = MagicMock(return_value=False)
    fake_st.expander.return_value = fake_expander
    monkeypatch.setitem(sys.modules, "streamlit", fake_st)
    return fake_st


# ── DataQualityReport label / coverage ──────────────────────


def test_label_high_when_all_sources_ok():
    rpt = DataQualityReport(
        sources=(
            DataSource("a", "ok"),
            DataSource("b", "ok"),
            DataSource("c", "ok"),
        )
    )
    assert rpt.label == "High"
    assert rpt.coverage_str == "3/3 sources"


def test_label_medium_when_half_partial():
    # 2 ok + 2 partial of 4 = (2 + 1.0) / 4 = 0.75 → Medium
    rpt = DataQualityReport(
        sources=(
            DataSource("a", "ok"),
            DataSource("b", "ok"),
            DataSource("c", "partial"),
            DataSource("d", "partial"),
        )
    )
    assert rpt.label == "Medium"


def test_label_low_when_majority_missing():
    rpt = DataQualityReport(
        sources=(
            DataSource("a", "ok"),
            DataSource("b", "missing"),
            DataSource("c", "missing"),
            DataSource("d", "missing"),
        )
    )
    assert rpt.label == "Low"


def test_label_low_when_empty():
    assert DataQualityReport(sources=()).label == "Low"


def test_coverage_str_format():
    rpt = DataQualityReport(
        sources=(
            DataSource("a", "ok"),
            DataSource("b", "partial"),
            DataSource("c", "missing"),
        )
    )
    assert rpt.coverage_str == "1/3 sources"


# ── overview_report ─────────────────────────────────────────


def test_overview_report_partial_when_some_prices_missing():
    weights = {f"T{i}": 0.1 for i in range(10)}
    # Only 7 of 10 tickers have price columns
    prices_df = pd.DataFrame({f"T{i}": np.arange(5.0) for i in range(7)})
    rpt = overview_report(
        weights=weights,
        prices_df=prices_df,
        meta={"net_equity": 100000.0},
    )
    price_source = next(s for s in rpt.sources if "Price history" in s.name)
    assert price_source.status == "partial"
    assert "7/10" in (price_source.note or "")


def test_overview_report_missing_when_no_weights():
    rpt = overview_report(weights={}, prices_df=None, meta=None)
    holdings = next(s for s in rpt.sources if s.name == "Portfolio holdings")
    assert holdings.status == "missing"
    # With no holdings, no usable sources → label is Low
    assert rpt.label == "Low"


def test_overview_report_ok_when_all_present():
    weights = {"NVDA": 0.5, "MSFT": 0.5}
    prices_df = pd.DataFrame({"NVDA": [1.0, 2.0], "MSFT": [3.0, 4.0]})
    rpt = overview_report(
        weights=weights,
        prices_df=prices_df,
        meta={"net_equity": 50000.0},
    )
    price_source = next(s for s in rpt.sources if "Price history" in s.name)
    assert price_source.status == "ok"


# ── risk_report ─────────────────────────────────────────────


def test_risk_report_uses_report_object_fields():
    weights = {"NVDA": 1.0}
    prices_df = pd.DataFrame({"NVDA": [1.0, 2.0, 3.0]})
    mock_report = SimpleNamespace(
        mc_portfolio_returns=np.array([0.01, -0.02, 0.03]),
        factor_betas=pd.DataFrame(),  # empty → missing
        component_var_pct=pd.Series([0.1, 0.2]),
        margin_call_info={"has_margin": True},
    )
    rpt = risk_report(weights=weights, prices_df=prices_df, report_obj=mock_report)

    by_name = {s.name: s for s in rpt.sources}
    assert by_name["Factor exposures"].status == "missing"
    assert by_name["Monte Carlo simulation"].status == "ok"
    assert by_name["Component VaR"].status == "ok"
    assert by_name["Margin call check"].status == "ok"


def test_risk_report_all_missing_when_report_blank():
    mock_report = SimpleNamespace(
        mc_portfolio_returns=None,
        factor_betas=None,
        component_var_pct=None,
        margin_call_info=None,
    )
    rpt = risk_report(weights={}, prices_df=None, report_obj=mock_report)
    assert rpt.label == "Low"
    statuses = {s.status for s in rpt.sources}
    assert statuses == {"missing"}


# ── trading_floor_report ────────────────────────────────────


def test_trading_floor_report_status_per_input():
    rpt = trading_floor_report(
        regime_data={"label": "Risk-On"},
        sector_data=None,
        movers_data=[{"ticker": "NVDA"}],
        market_regime_data={"vix": 14.0},
    )
    by_name = {s.name: s.status for s in rpt.sources}
    assert by_name["Regime detector"] == "ok"
    assert by_name["Sector scan"] == "missing"
    assert by_name["S&P 500 movers"] == "ok"
    assert by_name["Market regime (VIX / yield / F&G)"] == "ok"


# ── quant_lab_report ────────────────────────────────────────


def test_quant_lab_report_extends_risk_report(fake_streamlit):
    mock_report = SimpleNamespace(
        mc_portfolio_returns=np.array([0.0]),
        factor_betas=pd.DataFrame({"mkt": [0.5]}),
        component_var_pct=pd.Series([0.1]),
        margin_call_info={"has_margin": False},
    )
    fake_streamlit.session_state["backtest_result"] = {"sharpe": 1.2}
    rpt = quant_lab_report(
        weights={"NVDA": 1.0},
        prices_df=pd.DataFrame({"NVDA": [1.0]}),
        report_obj=mock_report,
    )
    by_name = {s.name: s.status for s in rpt.sources}
    assert "Backtest result (cached)" in by_name
    assert by_name["Backtest result (cached)"] == "ok"


def test_quant_lab_report_backtest_missing_when_absent(fake_streamlit):
    mock_report = SimpleNamespace(
        mc_portfolio_returns=None,
        factor_betas=None,
        component_var_pct=None,
        margin_call_info=None,
    )
    rpt = quant_lab_report(weights={}, prices_df=None, report_obj=mock_report)
    bt = next(s for s in rpt.sources if s.name == "Backtest result (cached)")
    assert bt.status == "missing"


# ── render_data_quality_panel ───────────────────────────────


def test_render_panel_uses_expander(fake_streamlit):
    rpt = DataQualityReport(
        sources=(
            DataSource("a", "ok"),
            DataSource("b", "ok"),
            DataSource("c", "partial", note="some note"),
        )
    )
    render_data_quality_panel(rpt)
    # st.expander must have been called once.
    assert fake_streamlit.expander.called
    header = fake_streamlit.expander.call_args[0][0]
    assert any(level in header for level in ("High", "Medium", "Low"))
    assert "2/3 sources" in header
    # The per-source rows go through markdown inside the with-block.
    assert fake_streamlit.markdown.called


def test_render_panel_handles_empty_sources(fake_streamlit):
    rpt = DataQualityReport(sources=())
    render_data_quality_panel(rpt)
    # Should still call expander but no per-source markdown rows.
    assert fake_streamlit.expander.called
    # Caption used instead of markdown rows.
    assert fake_streamlit.caption.called
