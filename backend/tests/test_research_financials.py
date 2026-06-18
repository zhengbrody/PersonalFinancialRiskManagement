"""Institutional Research FactPack (Phase 1) — deterministic trend engine.

All trend/TTM/margin/flag/confidence tests are PURE (hand-built fixtures, no
network). Missing-data + endpoint tests monkeypatch the FMP provider offline.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.main import create_app
from backend.app.services import research_financials as rfin
from backend.app.services.providers import fmp_provider as fp


def _q(
    period,
    *,
    revenue=None,
    gross_profit=None,
    operating_income=None,
    net_income=None,
    eps=None,
    fcf=None,
    ebitda=None,
):
    return rfin.quarter_from_row(
        {
            "period": period,
            "fiscal_date": f"{period}-01",
            "revenue": revenue,
            "gross_profit": gross_profit,
            "operating_income": operating_income,
            "net_income": net_income,
            "eps": eps,
            "free_cash_flow": fcf,
            "ebitda": ebitda,
        }
    )


def _series(revenues):
    """Quarters newest-first from a newest-first revenue list (other fields scaled)."""
    return [
        _q(f"P{i}", revenue=r, net_income=r * 0.1, eps=r * 0.01, fcf=r * 0.08, ebitda=r * 0.2)
        for i, r in enumerate(revenues)
    ]


# ── margins ─────────────────────────────────────────────────────────


def test_margins_computed_deterministically():
    q = _q(
        "2024-Q1",
        revenue=100.0,
        gross_profit=40.0,
        operating_income=20.0,
        net_income=10.0,
        fcf=15.0,
    )
    assert q.gross_margin == 0.40
    assert q.operating_margin == 0.20
    assert q.net_margin == 0.10
    assert q.fcf_margin == 0.15


def test_margin_is_none_when_revenue_missing_or_nonpositive():
    assert _q("x", gross_profit=40.0).gross_margin is None  # no revenue
    assert _q("x", revenue=0.0, gross_profit=40.0).gross_margin is None  # zero base
    assert _q("x", revenue=-5.0, net_income=2.0).net_margin is None  # negative base


# ── YoY / QoQ growth ────────────────────────────────────────────────


def test_yoy_growth_is_q0_vs_same_quarter_prior_year():
    qs = _series([120, 115, 112, 110, 100, 95, 90, 88])  # 8 quarters, newest first
    t = rfin.build_trend_summary(qs, [])
    assert round(t.revenue_yoy, 4) == round(120 / 100 - 1, 4)  # Q0 vs Q4
    assert round(t.eps_yoy, 4) == round((120 * 0.01) / (100 * 0.01) - 1, 4)


def test_qoq_growth_is_q0_vs_previous_quarter():
    qs = _series([120, 110, 100, 100, 100, 100, 100, 100])
    t = rfin.build_trend_summary(qs, [])
    assert round(t.revenue_qoq, 4) == round(120 / 110 - 1, 4)


def test_growth_declines_on_nonpositive_base():
    # EPS turns positive after a loss year: base ≤ 0 → growth is None (not a wrong sign).
    qs = [_q(f"P{i}", revenue=100, eps=(2.0 if i == 0 else -1.0)) for i in range(5)]
    t = rfin.build_trend_summary(qs, [])
    assert t.eps_yoy is None


def test_growth_needs_enough_quarters():
    t = rfin.build_trend_summary(_series([120, 110]), [])  # only 2 quarters
    assert t.revenue_yoy is None  # needs ≥5
    assert t.revenue_qoq is not None  # QoQ needs ≥2


# ── TTM aggregation ─────────────────────────────────────────────────


def test_ttm_sums_latest_four_quarters():
    qs = _series([120, 115, 112, 110, 100, 95, 90, 88])
    t = rfin.build_trend_summary(qs, [])
    assert t.ttm_revenue == 120 + 115 + 112 + 110


def test_ttm_none_with_fewer_than_four_quarters():
    assert rfin.build_trend_summary(_series([120, 115, 112]), []).ttm_revenue is None


def test_ttm_none_when_a_field_missing_in_window():
    qs = _series([120, 115, 112, 110])
    qs[2].ebitda = None  # one of the 4 lacks EBITDA → no partial TTM
    t = rfin.build_trend_summary(qs, [])
    assert t.ttm_revenue is not None
    assert t.ttm_ebitda is None


# ── acceleration / deceleration flags ───────────────────────────────


def test_revenue_acceleration_flag():
    # Q0/Q4 = 0.20 ; Q1/Q5 = 0.10 → accelerating
    qs = _series([120, 110, 105, 102, 100, 100, 100, 100])
    t = rfin.build_trend_summary(qs, [])
    assert t.revenue_yoy and t.prior_revenue_yoy is not None
    assert t.revenue_trend == "accelerating"
    assert any("accelerating" in f.lower() for f in t.flags)


def test_revenue_deceleration_flag():
    # Q0/Q4 = 0.05 ; Q1/Q5 = 0.20 → decelerating
    qs = _series([105, 120, 105, 102, 100, 100, 100, 100])
    t = rfin.build_trend_summary(qs, [])
    assert t.revenue_trend == "decelerating"
    assert any("decelerating" in f.lower() for f in t.flags)


def test_net_margin_expansion_flag_and_delta():
    qs = _series([120, 115, 112, 110, 100, 95, 90, 88])
    qs[0].net_margin = 0.15  # latest
    qs[4].net_margin = 0.10  # same quarter prior year
    t = rfin.build_trend_summary(qs, [])
    assert round(t.net_margin_delta_yoy, 4) == 0.05
    assert any("margin expanding" in f.lower() for f in t.flags)


# ── data confidence ─────────────────────────────────────────────────


def test_data_confidence_high_when_complete():
    qs = _series([100] * 8)
    annuals = [
        rfin.annual_from_row({"fiscal_year": str(2024 - i), "revenue": 400}) for i in range(5)
    ]
    score, label = rfin.compute_data_confidence(
        quarters=qs, annuals=annuals, snapshot_ok=True, fresh=True, missing_count=0
    )
    assert score >= 0.75 and label == "high"


def test_data_confidence_low_when_sparse():
    score, label = rfin.compute_data_confidence(
        quarters=[], annuals=[], snapshot_ok=False, fresh=False, missing_count=3
    )
    assert score == 0.0 and label == "low"


def test_data_confidence_partial_is_medium_range():
    qs = _series([100] * 4)
    score, label = rfin.compute_data_confidence(
        quarters=qs, annuals=[], snapshot_ok=True, fresh=True, missing_count=1
    )
    assert 0.45 <= score < 0.75 and label == "medium"


# ── missing-data fallback (offline provider) ────────────────────────


def test_build_factpack_partial_when_providers_fail(monkeypatch):
    monkeypatch.setattr(
        fp, "get_profile", lambda t: fp.ProviderResult(data=None, warnings=["fmp_key_missing"])
    )
    monkeypatch.setattr(
        fp,
        "get_financial_statements",
        lambda t, *, period, limit: fp.ProviderResult(data=None, warnings=["no_income_statement"]),
    )
    pack = rfin.build_research_fact_pack("aapl")  # must NOT raise
    assert pack.ticker == "AAPL"
    assert pack.quarters == [] and pack.annuals == []
    datasets = {m.dataset for m in pack.missing_data}
    assert {"profile", "income_quarterly", "income_annual"} <= datasets
    assert any(m.reason == "no_key" for m in pack.missing_data)
    assert pack.data_confidence == 0.0 and pack.confidence_label == "low"


def test_build_factpack_happy_path_with_mocked_provider(monkeypatch):
    monkeypatch.setattr(
        fp,
        "get_profile",
        lambda t: fp.ProviderResult(
            data=fp.CompanyProfile(ticker=t, name="Apple Inc.", sector="Technology", price=200.0),
            as_of="2024-12-28",
            coverage=1.0,
        ),
    )

    def _rows(n):
        return [
            {
                "period": f"2024-Q{4 - (i % 4)}",
                "fiscal_date": f"2024-{12 - i:02d}-28" if i < 12 else "2022-12-28",
                "revenue": 120 - i,
                "gross_profit": (120 - i) * 0.45,
                "operating_income": (120 - i) * 0.30,
                "net_income": (120 - i) * 0.25,
                "eps": (120 - i) * 0.02,
                "free_cash_flow": (120 - i) * 0.22,
                "ebitda": (120 - i) * 0.33,
                "shares_outstanding": 15_500,
            }
            for i in range(8)
        ]

    monkeypatch.setattr(
        fp,
        "get_financial_statements",
        lambda t, *, period, limit: fp.ProviderResult(
            data=_rows(limit), source="fmp", as_of="2024-12-28", coverage=1.0
        ),
    )

    pack = rfin.build_research_fact_pack("AAPL")
    assert pack.snapshot.name == "Apple Inc."
    assert len(pack.quarters) == 8 and len(pack.annuals) == 5
    assert pack.quarters[0].gross_margin == 0.45  # deterministic margin
    assert pack.trend.ttm_revenue is not None
    assert pack.trend.revenue_yoy is not None
    assert {p.dataset for p in pack.provenance} >= {"profile", "income_quarterly", "income_annual"}
    assert pack.data_confidence > 0.0
    assert "not investment advice" in pack.disclaimer.lower()


# ── provider: tier-adaptive limit fallback ──────────────────────────


def test_get_financial_statements_falls_back_to_tier_limit(monkeypatch):
    """Some FMP tiers cap quarterly depth (e.g. 5); asking for 8 → None. The
    provider must fall back to a smaller limit instead of returning nothing."""
    fp.reset_cache()
    monkeypatch.setattr(fp, "_key", lambda: "test-key")
    tried: list[int] = []

    def fake_get(path, params):
        n = params["limit"]
        if path == "/income-statement":
            tried.append(n)
            if n > 5:  # tier cap: deeper history is premium → error → None
                return None
            return [
                {
                    "date": f"2024-{12 - i:02d}-28",
                    "calendarYear": "2024",
                    "period": f"Q{4 - (i % 4)}",
                    "revenue": 100 - i,
                    "netIncome": 25 - i,
                    "eps": 2.0 - i * 0.1,
                    "ebitda": 30 - i,
                    "freeCashFlow": 22 - i,
                }
                for i in range(n)
            ]
        return [
            {"date": f"2024-{12 - i:02d}-28", "totalDebt": 1000, "cashAndCashEquivalents": 500}
            for i in range(n)
        ]

    monkeypatch.setattr(fp, "_get", fake_get)
    res = fp.get_financial_statements("AAPL", period="quarter", limit=8)
    assert res.data is not None and len(res.data) == 5  # fell back 8 → 5
    assert tried[0] == 8 and 5 in tried  # tried the requested depth first
    assert any("history_capped_at_5" in w for w in res.warnings)


# ── endpoint ────────────────────────────────────────────────────────


def test_research_factpack_endpoint_requires_auth():
    client = TestClient(create_app())
    assert client.get("/api/v1/research/AAPL/fact-pack").status_code == 401


def test_legacy_fact_pack_endpoint_still_present():
    # Backward-compat: the original compact FactPack route is untouched.
    client = TestClient(create_app())
    assert client.get("/api/v1/research/fact_pack/AAPL").status_code == 401
