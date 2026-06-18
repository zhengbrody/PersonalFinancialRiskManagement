"""Institutional analyst report — required sections present, deterministic
(exec summary from the no-LLM thesis fallback), fail-soft, endpoint auth."""

from __future__ import annotations

from types import SimpleNamespace as NS

from fastapi.testclient import TestClient

from backend.app.main import create_app
from backend.app.schemas.research import DataProvenanceItem, MissingDataItem
from backend.app.services import (
    research_dcf,
    research_earnings,
    research_factpack,
    research_financials,
    research_peers,
    research_thesis,
)
from backend.app.services import (
    research_report as rr,
)

REQUIRED = {
    "snapshot",
    "exec_summary",
    "financials",
    "dcf",
    "peers",
    "earnings",
    "risks",
    "monitoring",
    "provenance",
}


def _mock_all(monkeypatch, *, empty=False):
    if empty:
        for mod, fn in [
            (research_financials, "build_research_fact_pack"),
            (research_factpack, "build_fact_pack"),
            (research_dcf, "build_dcf"),
            (research_peers, "build_peer_comparison"),
            (research_earnings, "build_earnings_comparison"),
            (research_thesis, "build_thesis"),
        ]:
            monkeypatch.setattr(mod, fn, lambda *a, **k: None)
        return

    monkeypatch.setattr(
        research_financials,
        "build_research_fact_pack",
        lambda t: NS(
            snapshot=NS(
                name="Apple Inc.", sector="Tech", industry="Devices", price=200.0, market_cap=3e12
            ),
            confidence_label="high",
            data_confidence=0.84,
            as_of="2024-12-28",
            quarters=[
                NS(
                    period="2024-Q4",
                    revenue=120e9,
                    gross_margin=0.45,
                    operating_margin=0.30,
                    net_margin=0.25,
                    eps=2.4,
                )
            ],
            trend=NS(ttm_revenue=450e9, revenue_yoy=0.06, revenue_qoq=0.02, eps_yoy=0.1),
            provenance=[DataProvenanceItem(dataset="income_quarterly", source="fmp", coverage=1.0)],
            missing_data=[
                MissingDataItem(dataset="income_quarterly", reason="insufficient_history")
            ],
        ),
    )
    monkeypatch.setattr(
        research_factpack, "build_fact_pack", lambda t, **k: NS(risk_flags=["Rich multiple"])
    )
    monkeypatch.setattr(
        research_dcf,
        "build_dcf",
        lambda t, *a, **k: NS(
            valid=True,
            current_price=200.0,
            upside_pct=-0.5,
            inputs=NS(
                wacc=NS(value=0.096, source_type="derived"),
                terminal_growth=NS(value=0.025, source_type="default"),
                tax_rate=NS(value=0.18, source_type="derived"),
                net_debt=NS(value=4e10, source_type="reported"),
                diluted_shares=NS(value=1.5e10, source_type="reported"),
                provenance=[],
                missing_data=[],
            ),
            scenarios=[
                NS(name="bear", implied_value_per_share=75.0),
                NS(name="base", implied_value_per_share=98.0),
                NS(name="bull", implied_value_per_share=135.0),
            ],
        ),
    )
    monkeypatch.setattr(
        research_peers,
        "build_peer_comparison",
        lambda t, **k: NS(
            peer_source="fmp",
            rows=[
                NS(
                    ticker="AAPL",
                    is_subject=True,
                    market_cap=3e12,
                    revenue_growth=0.06,
                    net_margin=0.25,
                    pe=34.0,
                    ev_ebitda=22.0,
                ),
                NS(
                    ticker="MSFT",
                    is_subject=False,
                    market_cap=3e12,
                    revenue_growth=0.15,
                    net_margin=0.36,
                    pe=33.0,
                    ev_ebitda=24.0,
                ),
            ],
            missing_data=[],
        ),
    )
    monkeypatch.setattr(
        research_earnings,
        "build_earnings_comparison",
        lambda t: NS(
            as_of="2024-12-28",
            periods=[
                NS(
                    period="2024-Q4",
                    revenue=120e9,
                    revenue_yoy=0.06,
                    eps=2.4,
                    eps_yoy=0.1,
                    revenue_beat=True,
                )
            ],
            summary=NS(headline="Revenue +6% YoY"),
            transcript=NS(available=True, fiscal_year=2024, quarter=4, date="2025-02-01"),
            provenance=[],
            missing_data=[],
        ),
    )
    monkeypatch.setattr(
        research_thesis,
        "build_thesis",
        lambda t, llm_callable=None: NS(
            key_debate="Base DCF $98 vs $200 price.",
            bull_case=["Durable franchise"],
            bear_case=["Rich multiple"],
            red_flags=["Slowing growth"],
            monitor_next_quarter=["Next print vs trend"],
            ai_generated=False,
        ),
    )


def test_report_includes_all_required_sections(monkeypatch):
    _mock_all(monkeypatch)
    out = rr.build_analyst_report("AAPL")
    keys = {s.key for s in out.sections}
    assert REQUIRED <= keys
    # deterministic content rendered
    assert "Apple Inc." in out.html and "Executive summary" in out.html
    assert (
        "DCF model" in out.html
        and "Peer comparison" in out.html
        and "Earnings analysis" in out.html
    )
    # always-present disclaimer + timestamps
    assert "not financial advice" in out.html.lower()
    assert out.generated_at and out.as_of == "2024-12-28"
    # provenance appendix carries the deterministic items
    assert any(p.dataset == "income_quarterly" for p in out.provenance.items)


def test_report_failsoft_when_engines_empty(monkeypatch):
    _mock_all(monkeypatch, empty=True)
    out = rr.build_analyst_report("ZZZ")  # must not raise
    keys = {s.key for s in out.sections}
    assert REQUIRED <= keys  # every section still present (with "unavailable" notes)
    assert "not financial advice" in out.html.lower()
    # the unavailable sections are flagged included=False
    assert any(s.included is False for s in out.sections)


def test_report_endpoint_requires_auth():
    client = TestClient(create_app())
    assert client.get("/api/v1/research/AAPL/report").status_code == 401
