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


def _quarter(**kw):
    base = dict(
        fiscal_date="2026-06-30",
        revenue=1000.0,
        net_income=100.0,
        eps=1.0,
        cash=500.0,
        debt=200.0,
        free_cash_flow=80.0,
        capex=-20.0,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _financials(with_balance_cashflow=True, source="fmp+yfinance"):
    """REAL shape: the provider merges income+balance+cashflow into ONE dataset
    per period — provenance carries ONLY income_quarterly/income_annual; the
    per-statement signal lives in the quarter-row FIELDS."""
    if with_balance_cashflow:
        quarters = [_quarter(), _quarter(fiscal_date="2026-03-31")]
    else:
        quarters = [
            _quarter(cash=None, debt=None, free_cash_flow=None, capex=None),
            _quarter(
                fiscal_date="2026-03-31", cash=None, debt=None, free_cash_flow=None, capex=None
            ),
        ]
    return SimpleNamespace(
        quarters=quarters,
        provenance=[
            SimpleNamespace(
                dataset="income_quarterly",
                source=source,
                as_of="2026-06-30",
                fetched_at="2026-07-14T00:00:00Z",
                coverage=0.8,
            ),
        ],
        missing_data=[SimpleNamespace(dataset="income_quarterly", reason="requires_paid_plan")],
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
    # statements derived from the quarter-row FIELDS (the provider has no
    # per-statement datasets — the old lookup by invented names always missed)
    assert by_field["income_statement_quarterly"].as_of == "2026-06-30"
    assert by_field["income_statement_quarterly"].group == "Financial statements"
    assert by_field["balance_sheet_quarterly"].source == "fmp+yfinance"
    assert by_field["cashflow_statement_quarterly"].coverage == 1.0
    # freshness stamps survive
    assert by_field["price"].as_of == "2026-07-14"
    # groups everywhere
    assert all(r.group for r in (*out.fields, *out.missing))


def test_missing_fields_carry_typed_reasons_never_fake_values(monkeypatch):
    # income-only tier: balance/cashflow FIELDS all None in every quarter
    _wire(monkeypatch)
    monkeypatch.setattr(rc, "_financials", lambda tk: _financials(with_balance_cashflow=False))
    out = rc.build_coverage("AAPL")
    by_missing = {r.field: r for r in out.missing}
    assert by_missing["balance_sheet_quarterly"].missing_reason == "unsupported"
    assert by_missing["balance_sheet_quarterly"].critical is True
    assert by_missing["cashflow_statement_quarterly"].missing_reason == "unsupported"
    # income itself still present from the same rows
    assert any(f.field == "income_statement_quarterly" for f in out.fields)
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
    assert {r.field for r in out.missing} >= {
        "price",
        "profit_margins",
        "income_statement_quarterly",
    }
    assert all(r.missing_reason for r in out.missing)


def test_rich_coverage_supports_conviction(monkeypatch):
    _wire(monkeypatch)
    out = rc.build_coverage("AAPL")
    dc = out.data_confidence
    # all critical datasets present → full critical coverage, directional
    assert dc.directional_allowed is True
    assert dc.critical_coverage == 1.0
    assert dc.conviction_cap in ("medium", "high")


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


def test_thin_factpack_gets_short_cache_ttl(monkeypatch):
    """A freshly-built pack with coverage under the no-directional floor is
    cached for minutes, not the full TTL — a provider throttle window must not
    pin low-coverage answers for half an hour."""
    from backend.app.schemas import research as R
    from backend.app.services import research_factpack as rf
    from backend.app.services.cache import get_cache
    from backend.app.services.cache_keys import make_key

    rf.reset_enrich_cache()
    thin = R.FactPack(ticker="THIN", price=1.0, data_quality=R.DataQuality(coverage=0.1))
    monkeypatch.setattr(rf, "build_fact_pack", lambda tk, yf_enricher=None: thin)
    rf.build_fact_pack_cached("THIN")
    env = get_cache().get(make_key("research:factpack", rf.FACTPACK_VERSION, "THIN"))
    window = float(env["expires_at"]) - float(env["fetched_at"])
    assert window <= rf._THIN_PACK_TTL + 1

    rf.reset_enrich_cache()
    rich = R.FactPack(ticker="RICH", price=1.0, data_quality=R.DataQuality(coverage=0.9))
    monkeypatch.setattr(rf, "build_fact_pack", lambda tk, yf_enricher=None: rich)
    rf.build_fact_pack_cached("RICH")
    env2 = get_cache().get(make_key("research:factpack", rf.FACTPACK_VERSION, "RICH"))
    window2 = float(env2["expires_at"]) - float(env2["fetched_at"])
    assert window2 >= rf._FACTPACK_TTL - 1
