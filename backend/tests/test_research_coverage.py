"""Phase 5 — research data-coverage matrix.

Core grading, typed missing reasons, honest source tiers (fallback stays
fallback, derived stays derived), fail-soft legs, the shared conviction gate,
and the authed endpoint.
"""

from __future__ import annotations

from types import SimpleNamespace

from backend.app.schemas import research as R
from backend.app.services import research_coverage as rc


def _rich_pack() -> R.FactPack:
    return R.FactPack(
        ticker="AAPL",
        name="Apple Inc.",
        sector="Technology",
        as_of="2026-07-14",
        price=291.4,
        valuation=R.ValuationBlock(pe=32.1, forward_pe=30.0),
        quality=R.QualityBlock(net_margin=0.26, roe=1.52),
        growth=R.GrowthBlock(revenue_cagr=0.083),
        analyst=R.AnalystBlock(target_consensus=310.0, implied_upside_pct=0.06),
        momentum=R.MomentumBlock(rsi_14=55.0),
        ownership=R.OwnershipBlock(institutional_pct=0.61),
        insider=R.InsiderBlock(buys_90d=3, sells_90d=5, signal="net selling"),
        news=[R.NewsHeadline(title="AAPL ships things")],
        data_quality=R.DataQuality(
            coverage=0.9,
            sources=[
                R.SourceRef(field="price", source="fmp", as_of="2026-07-14", coverage=1.0),
                R.SourceRef(field="ratios", source="fmp", as_of="2026-07-13", coverage=1.0),
                R.SourceRef(field="analyst", source="yfinance", coverage=1.0),
            ],
        ),
    )


def _financials(coverage=1.0, source="fmp"):
    return SimpleNamespace(
        provenance=[
            SimpleNamespace(
                dataset="income_quarterly",
                source=source,
                as_of="2026-06-30",
                fetched_at="2026-07-14T00:00:00Z",
                coverage=coverage,
            ),
            SimpleNamespace(
                dataset="balance_quarterly",
                source=source,
                as_of="2026-06-30",
                fetched_at=None,
                coverage=coverage,
            ),
            SimpleNamespace(
                dataset="cashflow_quarterly",
                source="none",
                as_of=None,
                fetched_at=None,
                coverage=0.0,
            ),
        ],
        missing_data=[SimpleNamespace(dataset="cashflow_quarterly", reason="requires_paid_plan")],
    )


def _earnings(with_estimates=True):
    period = SimpleNamespace(eps_estimate=2.5 if with_estimates else None, revenue_estimate=None)
    return SimpleNamespace(
        as_of="2026-06-30",
        periods=[period],
        transcript=SimpleNamespace(available=False),
        provenance=[
            SimpleNamespace(
                dataset="earnings",
                source="yfinance",
                as_of="2026-06-30",
                fetched_at=None,
                coverage=1.0,
            )
        ],
        missing_data=[SimpleNamespace(dataset="transcript", reason="requires_paid_plan")],
    )


def _dcf():
    a = lambda st: SimpleNamespace(source_type=st)  # noqa: E731
    return SimpleNamespace(
        base_revenue=a("reported"),
        tax_rate=a("reported"),
        wacc=a("derived"),
        terminal_growth=a("default"),
        net_debt=a("reported"),
        diluted_shares=a("reported"),
        revenue_growth=[a("derived")],
        operating_margin=[a("derived")],
    )


def _wire(monkeypatch, fp="rich", fin="ok", earn="ok", dcf="ok"):
    monkeypatch.setattr(
        rc,
        "_factpack",
        lambda tk: (
            _rich_pack()
            if fp == "rich"
            else (_ for _ in ()).throw(RuntimeError("down")) if fp == "boom" else None
        ),
    )
    monkeypatch.setattr(rc, "_financials", lambda tk: _financials() if fin == "ok" else None)
    monkeypatch.setattr(rc, "_earnings", lambda tk: _earnings() if earn == "ok" else None)
    monkeypatch.setattr(rc, "_dcf_input", lambda tk: _dcf() if dcf == "ok" else None)


def test_rich_ticker_matrix_grades_and_sources(monkeypatch):
    _wire(monkeypatch)
    out = rc.build_coverage("aapl")
    assert out.ticker == "AAPL"
    by_field = {r.field: r for r in out.fields}
    # core fields present + graded critical
    for f in ("company_profile", "price", "profit_margins", "return_on_equity", "valuation_pe"):
        assert by_field[f].critical is True
    # honest source tiers: fmp=primary, yfinance=secondary(fallback), derived=derived
    assert by_field["price"].source == "fmp" and by_field["price"].source_type == "primary"
    assert by_field["analyst_estimates"].source == "yfinance"
    assert by_field["analyst_estimates"].source_type == "secondary"
    assert by_field["analyst_estimates"].fallback_used is True
    assert by_field["revenue_growth"].source_type == "derived"
    # statements ride the financials provenance
    assert by_field["income_quarterly"].as_of == "2026-06-30"
    assert by_field["income_quarterly"].group == "Financial statements"
    # freshness stamps survive
    assert by_field["price"].as_of == "2026-07-14"
    # groups everywhere
    assert all(r.group for r in (*out.fields, *out.missing))


def test_missing_fields_carry_typed_reasons_never_fake_values(monkeypatch):
    _wire(monkeypatch)
    out = rc.build_coverage("AAPL")
    by_missing = {r.field: r for r in out.missing}
    # premium-gated cashflow → typed "unsupported" (from requires_paid_plan)
    assert by_missing["cashflow_quarterly"].missing_reason == "unsupported"
    assert by_missing["cashflow_quarterly"].critical is True
    # transcripts absent → typed reason, coverage 0 (no fake placeholders)
    assert by_missing["transcripts"].missing_reason == "unsupported"
    assert all((r.coverage or 0) == 0.0 for r in out.missing)


def test_conviction_gate_reacts_to_thin_critical_coverage(monkeypatch):
    _wire(monkeypatch, fp="none", fin="none")  # everything core missing
    out = rc.build_coverage("ZZZZ")
    dc = out.data_confidence
    assert dc.critical_coverage == 0.0
    assert dc.directional_allowed is False
    assert dc.conviction_cap == "none"
    # every absent core dataset is an explicit missing row with a typed reason
    assert {r.field for r in out.missing} >= {"price", "profit_margins", "income_quarterly"}
    assert all(r.missing_reason for r in out.missing)


def test_rich_coverage_supports_conviction(monkeypatch):
    _wire(monkeypatch)
    out = rc.build_coverage("AAPL")
    dc = out.data_confidence
    # one critical statement (cashflow) missing → reduced, but directional
    assert dc.directional_allowed is True
    assert dc.conviction_cap in ("low", "medium", "high")
    assert 0.5 < dc.critical_coverage < 1.0


def test_fail_soft_legs_become_missing_rows(monkeypatch):
    _wire(monkeypatch, fp="boom", fin="none", earn="none", dcf="none")
    out = rc.build_coverage("AAPL")  # nothing raises
    assert out.fields == []
    assert {r.missing_reason for r in out.missing} == {"provider_error"}


def test_dcf_assumptions_aggregate_coverage(monkeypatch):
    _wire(monkeypatch)
    out = rc.build_coverage("AAPL")
    row = next(r for r in out.fields if r.field == "dcf_assumptions")
    assert row.source_type == "derived"
    assert 0 < (row.coverage or 0) <= 1.0


def test_coverage_endpoint_auth_and_happy(test_client, mint_token, monkeypatch):
    assert test_client.get("/api/v1/research/AAPL/coverage").status_code == 401
    from backend.app.services import research_coverage as svc

    _wire(monkeypatch, fp="rich")
    monkeypatch.setattr(svc, "_factpack", lambda tk: _rich_pack())
    resp = test_client.get(
        "/api/v1/research/AAPL/coverage",
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["ticker"] == "AAPL"
    assert data["data_confidence"]["conviction_cap"] in ("none", "low", "medium", "high")
    assert any(f["field"] == "price" for f in data["fields"])
