"""Exportable HTML reports — renderers + endpoints.

The reports are a pure presentation layer (no recompute, no LLM); tests assert
required sections render, unsafe input is escaped, the document is self-contained
with print CSS, and the routes are auth-gated.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.main import create_app
from backend.app.schemas.options import (
    OptionAnalyzeResponse,
    OptionExposureOut,
    OptionStrategyOut,
    OptionTotalsOut,
    PayoffPointOut,
)
from backend.app.schemas.research import (
    DimensionScore,
    FactPack,
    ResearchVerdict,
    ValuationBlock,
)
from backend.app.schemas.risk import ComponentVarRow, ConcentrationOut, RiskReportOut
from backend.app.schemas.risk_explain import RiskExplainOutput
from backend.app.services import report_html


def test_portfolio_report_has_summary_appendix_and_print_css():
    report = RiskReportOut(
        annual_volatility=0.24,
        sharpe_ratio=0.9,
        max_drawdown=-0.31,
        var_95=0.025,
        net_equity=120000.0,
        component_var_pct=[
            ComponentVarRow(ticker="NVDA", pct=0.41),
            ComponentVarRow(ticker="AAPL", pct=0.2),
        ],
        concentration=ConcentrationOut(
            num_holdings=8, top_holding_ticker="NVDA", top_holding_weight=0.3
        ),
        stress_loss=0.22,
        stress_market_shock=-0.2,
        data_quality_notes=["short history for 2 names"],
    )
    diagnosis = RiskExplainOutput(
        severity="elevated",
        headline="Concentrated, high-beta book",
        summary_bullets=["NVDA drives most of your VaR."],
        primary_driver="concentration",
        ai_generated=True,
    )
    html = report_html.render_portfolio_report(report, diagnosis)
    # Self-contained document with print rules.
    assert html.startswith("<!doctype html>")
    assert "@media print" in html and "@page" in html
    # Visual summary (AI exec + KPIs) + appendix sections.
    assert "Executive summary" in html and "AI-generated" in html
    assert "Key metrics" in html and "Top risk drivers" in html
    assert "Factor exposure" in html and "Stress test" in html and "Data quality" in html
    # Real numbers rendered.
    assert "NVDA" in html and "41.0%" in html
    # Education disclaimer present.
    assert "not investment advice" in html


def test_report_escapes_unsafe_text():
    fp = FactPack(ticker="AAPL", name="<script>alert(1)</script>")
    html = report_html.render_ticker_report(fp, None)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html  # escaped


def test_ticker_report_renders_verdict_and_valuation():
    fp = FactPack(
        ticker="AAPL",
        name="Apple Inc.",
        price=200.0,
        valuation=ValuationBlock(pe=30.0, band="rich"),
    )
    verdict = ResearchVerdict(
        rating="Hold",
        conviction="medium",
        summary="Fairly valued.",
        dimensions=[DimensionScore(name="valuation", score=55)],
        data_only=False,
    )
    html = report_html.render_ticker_report(fp, verdict)
    assert "Apple Inc." in html and "AAPL" in html
    assert "AI analyst view" in html and "Hold" in html
    assert "Valuation" in html and "30.00" in html
    assert "rich" in html


def test_options_report_renders_strategy_payoff_svg():
    analysis = OptionAnalyzeResponse(
        results=[],
        totals=OptionTotalsOut(),
        exposure=OptionExposureOut(
            net_delta=55.0,
            gross_delta=55.0,
            net_gamma=2.0,
            net_theta=-10.0,
            net_vega=20.0,
            option_notional=12000.0,
            short_collateral_estimate=0.0,
            contracts=2,
            short_contracts=1,
        ),
        scenarios={
            "grid": [],
            "top_positions": [],
            "stress_cell": {},
            "underlying_shocks": [],
            "iv_shocks": [],
            "horizons": [],
            "repriced": 0,
            "skipped": [],
        },
        strategies=[
            OptionStrategyOut(
                underlying="AAPL",
                expiry="2026-01-16",
                name="Bull call spread",
                leg_count=2,
                net_debit=600.0,
                max_loss=600.0,
                max_gain=1400.0,
                break_evens=[146.0],
                net_greeks={"delta": 0.5, "gamma": 0.02, "theta": -0.03, "vega": 0.1},
                payoff=[PayoffPointOut(price=120, pnl=-600), PayoffPointOut(price=170, pnl=1400)],
            )
        ],
        as_of="2026-06-16",
        warnings=[],
    )
    html = report_html.render_options_report(analysis)
    assert "Bull call spread" in html
    assert "<svg" in html and "polyline" in html  # server-generated payoff, no JS
    assert "Max loss" in html and "$600" in html
    assert "Portfolio option exposure" in html


def test_report_endpoints_are_auth_gated():
    c = TestClient(create_app())
    for path in ("/portfolio/html", "/ticker/html", "/options/html"):
        r = c.post(f"/api/v1/reports{path}", json={})
        assert r.status_code == 401, path
