"""Deterministic DCF engine — pure math, guardrails, scenarios, sensitivity,
assumption source_type, and fail-soft builder (offline provider)."""

from __future__ import annotations

import pytest

from backend.app.schemas.valuation import DCFOverrides
from backend.app.services import research_dcf as dcf
from backend.app.services.providers import fmp_provider as fp


@pytest.fixture(autouse=True)
def _offline_risk_free(monkeypatch):
    """Pin the risk-free rate so the DCF tests are offline + deterministic (the
    real _risk_free_rate hits the Treasury yield-curve API). Individual tests can
    re-monkeypatch it (e.g. to None to exercise the all-default WACC path)."""
    monkeypatch.setattr(dcf, "_risk_free_rate", lambda: 0.04)


# ── pure projection math ────────────────────────────────────────────


def test_project_matches_hand_computation():
    # base 100, +10%/yr, 20% op margin, 25% tax, no D&A/capex/NWC, WACC 10%, g 2%.
    r = dcf.project(
        base_revenue=100.0,
        growths=[0.10, 0.10],
        margins=[0.20, 0.20],
        tax=0.25,
        da_pct=0.0,
        capex_pct=0.0,
        nwc_pct=0.0,
        wacc=0.10,
        terminal_growth=0.02,
        net_debt=0.0,
        shares=10.0,
    )
    # Y1 FCF 16.5 → PV 15.0 ; Y2 FCF 18.15 → PV 15.0 ; ΣPV = 30
    # TV = 18.15*1.02/0.08 = 231.4125 ; PV(TV) = 231.4125/1.21 = 191.25
    # EV = 221.25 ; equity = 221.25 ; /10 = 22.125
    assert r["projections"][0]["fcf"] == pytest.approx(16.5)
    assert r["projections"][1]["fcf"] == pytest.approx(18.15)
    assert r["terminal_value"] == pytest.approx(231.4125)
    assert r["pv_terminal_value"] == pytest.approx(191.25)
    assert r["enterprise_value"] == pytest.approx(221.25)
    assert r["implied_value_per_share"] == pytest.approx(22.125)


def test_net_debt_reduces_equity_value():
    kw = dict(
        base_revenue=100.0,
        growths=[0.05],
        margins=[0.2],
        tax=0.21,
        da_pct=0.0,
        capex_pct=0.0,
        nwc_pct=0.0,
        wacc=0.10,
        terminal_growth=0.02,
        shares=10.0,
    )
    no_debt = dcf.project(net_debt=0.0, **kw)["equity_value"]
    with_debt = dcf.project(net_debt=50.0, **kw)["equity_value"]
    assert with_debt == pytest.approx(no_debt - 50.0)


# ── terminal-value guardrails ───────────────────────────────────────


def test_terminal_growth_at_or_above_wacc_is_rejected():
    base = dict(
        base_revenue=100.0,
        growths=[0.05],
        margins=[0.2],
        tax=0.2,
        da_pct=0.0,
        capex_pct=0.0,
        nwc_pct=0.0,
        net_debt=0.0,
        shares=10.0,
    )
    with pytest.raises(dcf.InvalidDCF):
        dcf.project(wacc=0.05, terminal_growth=0.06, **base)  # g > WACC
    with pytest.raises(dcf.InvalidDCF):
        dcf.project(wacc=0.05, terminal_growth=0.05, **base)  # g == WACC


def test_zero_or_missing_shares_rejected():
    base = dict(
        base_revenue=100.0,
        growths=[0.05],
        margins=[0.2],
        tax=0.2,
        da_pct=0.0,
        capex_pct=0.0,
        nwc_pct=0.0,
        net_debt=0.0,
        wacc=0.10,
        terminal_growth=0.02,
    )
    with pytest.raises(dcf.InvalidDCF):
        dcf.project(shares=0.0, **base)


# ── builder: assumption source_type + overrides + fail-soft ─────────


def _annual_rows():
    # newest first; 4 fiscal years
    out = []
    for i in range(4):
        rev = 400.0 - i * 40
        out.append(
            {
                "fiscal_date": f"{2024 - i}-12-31",
                "fiscal_year": str(2024 - i),
                "period": str(2024 - i),
                "revenue": rev,
                "operating_income": rev * 0.30,
                "income_tax": rev * 0.30 * 0.18,
                "pretax_income": rev * 0.30,
                "d_and_a": rev * 0.05,
                "capex": -rev * 0.06,
                "change_in_nwc": -rev * 0.01,
                "debt": 100.0,
                "cash": 60.0,
                "diluted_shares": 1000.0,
            }
        )
    return out


@pytest.fixture
def mock_fmp(monkeypatch):
    monkeypatch.setattr(
        fp,
        "get_financial_statements",
        lambda t, *, period, limit: fp.ProviderResult(
            data=_annual_rows(), source="fmp", as_of="2024-12-31", coverage=1.0
        ),
    )
    monkeypatch.setattr(
        fp,
        "get_profile",
        lambda t: fp.ProviderResult(
            data=fp.CompanyProfile(ticker=t, name="Acme", beta=1.2, price=50.0)
        ),
    )


def test_build_input_labels_source_types(mock_fmp):
    inp = dcf.build_dcf_input("ACME")
    assert inp.base_revenue.source_type == "reported" and inp.base_revenue.value == 400.0
    assert inp.tax_rate.source_type == "derived"  # income_tax/pretax = 0.18
    assert inp.tax_rate.value == pytest.approx(0.18, abs=1e-3)
    assert inp.wacc.source_type == "derived"  # CAPM from beta
    assert inp.net_debt.source_type == "reported" and inp.net_debt.value == pytest.approx(40.0)
    assert inp.diluted_shares.source_type == "reported" and inp.diluted_shares.value == 1000.0
    assert len(inp.revenue_growth) == inp.projection_years
    assert all(g.source_type in ("derived", "default") for g in inp.revenue_growth)


def test_user_overrides_relabel_and_recalculate(mock_fmp):
    base = dcf.build_dcf("ACME")
    ov = DCFOverrides(wacc=0.12, terminal_growth=0.02, tax_rate=0.30)
    edited = dcf.build_dcf("ACME", ov)
    assert edited.inputs.wacc.source_type == "user_override" and edited.inputs.wacc.value == 0.12
    assert edited.inputs.tax_rate.source_type == "user_override"
    # a higher WACC + higher tax must lower the implied value
    assert base.implied_value_per_share is not None
    assert edited.implied_value_per_share is not None
    assert edited.implied_value_per_share < base.implied_value_per_share


def test_build_input_unavailable_when_no_data(monkeypatch):
    monkeypatch.setattr(
        fp,
        "get_financial_statements",
        lambda t, *, period, limit: fp.ProviderResult(data=None, warnings=["no_income_statement"]),
    )
    monkeypatch.setattr(fp, "get_profile", lambda t: fp.ProviderResult(data=None))
    monkeypatch.setattr(dcf, "_risk_free_rate", lambda: None)  # no macro either
    inp = dcf.build_dcf_input("ZZZ")
    assert inp.base_revenue.source_type == "unavailable"
    assert inp.diluted_shares.source_type == "unavailable"
    # No beta, no equity value, no sourced risk-free rate → wholly default WACC.
    assert inp.wacc.source_type == "default"
    assert {m.dataset for m in inp.missing_data} >= {
        "income_annual",
        "base_revenue",
        "diluted_shares",
    }


def test_build_input_defaults_operating_margin_when_revenue_exists(monkeypatch):
    rows = [_full_row(), _full_row()]
    for r in rows:
        r["operating_income"] = None
    monkeypatch.setattr(
        fp,
        "get_financial_statements",
        lambda t, *, period, limit: fp.ProviderResult(
            data=rows, source="fmp", as_of="2024-12-31", coverage=0.8
        ),
    )
    monkeypatch.setattr(
        fp,
        "get_profile",
        lambda t: fp.ProviderResult(
            data=fp.CompanyProfile(ticker=t, name="Acme", beta=1.0, price=10.0, market_cap=5000.0)
        ),
    )
    inp = dcf.build_dcf_input("ACME")
    assert inp.base_revenue.value == 1000.0
    assert inp.operating_margin
    assert inp.operating_margin[0].source_type == "default"
    assert ("operating_margin", "default_used") in [(m.dataset, m.reason) for m in inp.missing_data]


def test_build_input_derives_shares_from_market_cap_over_price(monkeypatch):
    row = _full_row()
    row["diluted_shares"] = None
    monkeypatch.setattr(
        fp,
        "get_financial_statements",
        lambda t, *, period, limit: fp.ProviderResult(
            data=[row, row], source="fmp", as_of="2024-12-31", coverage=0.9
        ),
    )
    monkeypatch.setattr(
        fp,
        "get_profile",
        lambda t: fp.ProviderResult(
            data=fp.CompanyProfile(ticker=t, name="Acme", beta=1.0, price=25.0, market_cap=2500.0)
        ),
    )
    inp = dcf.build_dcf_input("ACME")
    assert inp.diluted_shares.source_type == "derived"
    assert inp.diluted_shares.source == "derived:market_cap_over_price"
    assert inp.diluted_shares.value == pytest.approx(100.0)


def test_build_dcf_invalid_when_no_data(monkeypatch):
    monkeypatch.setattr(
        fp,
        "get_financial_statements",
        lambda t, *, period, limit: fp.ProviderResult(data=None, warnings=["x"]),
    )
    monkeypatch.setattr(fp, "get_profile", lambda t: fp.ProviderResult(data=None))
    out = dcf.build_dcf("ZZZ")  # must not raise
    assert out.valid is False and out.implied_value_per_share is None


def test_build_dcf_terminal_growth_guardrail_via_overrides(mock_fmp):
    out = dcf.build_dcf("ACME", DCFOverrides(wacc=0.03, terminal_growth=0.05))
    assert out.valid is False
    assert any("terminal growth" in w.lower() for w in out.warnings)


# ── scenarios + sensitivity ─────────────────────────────────────────


def test_scenarios_ordered_bear_base_bull(mock_fmp):
    out = dcf.build_dcf("ACME")
    by = {s.name: s.implied_value_per_share for s in out.scenarios}
    assert set(by) == {"bear", "base", "bull"}
    assert by["bear"] is not None and by["base"] is not None and by["bull"] is not None
    assert by["bear"] < by["base"] < by["bull"]


def test_sensitivity_tables_present_and_guard_invalid_cells(mock_fmp):
    out = dcf.build_dcf("ACME")
    assert len(out.sensitivity) == 2
    wacc_tg = out.sensitivity[0]
    assert wacc_tg.row_label == "WACC" and wacc_tg.col_label == "Terminal growth"
    # grid shape matches axes
    assert len(wacc_tg.values) == len(wacc_tg.rows)
    assert all(len(r) == len(wacc_tg.cols) for r in wacc_tg.values)
    # a cell where terminal growth ≥ WACC must be None (invalid)
    invalid = [
        wacc_tg.values[i][j]
        for i, w in enumerate(wacc_tg.rows)
        for j, g in enumerate(wacc_tg.cols)
        if g >= w
    ]
    assert all(c is None for c in invalid)
    assert out.sensitivity[1].row_label == "Revenue CAGR"


# ── Phase-2 upgrade: workbook-parity WACC + equity bridge + NWC%sales + history ──


def test_wacc_matches_workbook_full_formula():
    """Workbook WACC sheet (AMZN): Debt 47,556 · Equity 1,250,000 · Kd 2% ·
    tax 21% · rf 2.758% · β 1.25 · MRP 4.24% → WACC = 0.07820578."""
    ov = DCFOverrides(
        risk_free_rate=0.02758,
        beta=1.25,
        market_risk_premium=0.0424,
        cost_of_debt=0.02,
        equity_value=1_250_000.0,
        total_debt=47556.0,
    )
    w, bd = dcf._build_wacc(
        ov, beta=None, equity_value=None, total_debt=None, interest_expense=None, tax=0.21
    )
    # The engine rounds for display (WACC 5dp, weights 4dp) → workbook ≈ 0.07821.
    assert w.value == pytest.approx(0.0782, abs=1e-4)
    by = {a.name: a for a in bd}
    assert {"cost_of_equity", "cost_of_debt", "pct_equity", "pct_debt", "wacc"} <= set(by)
    assert by["cost_of_equity"].value == pytest.approx(0.08058, abs=1e-5)  # rf + β·MRP
    assert by["pct_debt"].value == pytest.approx(0.0367, abs=1e-3)


def test_wacc_capital_structure_weighting():
    ov = DCFOverrides(
        risk_free_rate=0.03,
        beta=1.0,
        market_risk_premium=0.05,
        cost_of_debt=0.05,
        equity_value=800.0,
        total_debt=200.0,
    )
    w, _ = dcf._build_wacc(
        ov, beta=None, equity_value=None, total_debt=None, interest_expense=None, tax=0.20
    )
    # 0.8·(0.03 + 1·0.05) + 0.2·0.05·(1−0.20) = 0.064 + 0.008 = 0.072
    assert w.value == pytest.approx(0.072, abs=1e-6)


def test_wacc_equity_only_without_capital_structure():
    ov = DCFOverrides(risk_free_rate=0.03, beta=1.1, market_risk_premium=0.05)
    w, _ = dcf._build_wacc(
        ov, beta=None, equity_value=None, total_debt=None, interest_expense=None, tax=0.21
    )
    assert w.source_type == "derived"
    assert w.value == pytest.approx(0.03 + 1.1 * 0.05, abs=1e-6)  # equity-only Ke


def test_cost_of_debt_derived_from_interest_over_debt():
    w, bd = dcf._build_wacc(
        DCFOverrides(equity_value=1000.0, total_debt=200.0),
        beta=1.0,
        equity_value=None,
        total_debt=None,
        interest_expense=10.0,
        tax=0.21,
    )
    kd = next(a for a in bd if a.name == "cost_of_debt")
    assert kd.source_type == "derived" and kd.value == pytest.approx(0.05)  # 10/200


def test_nwc_pct_is_average_of_last_three_over_sales():
    rows = [
        {"change_in_nwc": -10.0, "revenue": 1000.0},  # −1.0%
        {"change_in_nwc": -20.0, "revenue": 1000.0},  # −2.0%
        {"change_in_nwc": 0.0, "revenue": 1000.0},  # 0.0%
        {"change_in_nwc": 500.0, "revenue": 1000.0},  # ignored — only last 3
    ]
    a = dcf._nwc_asm(None, rows)
    assert a.source_type == "derived"
    assert a.value == pytest.approx((-0.01 - 0.02 + 0.0) / 3)  # keeps the sign


def test_projected_nwc_is_pct_of_total_sales():
    r = dcf.project(
        base_revenue=100.0,
        growths=[0.10],
        margins=[0.20],
        tax=0.0,
        da_pct=0.0,
        capex_pct=0.0,
        nwc_pct=0.05,
        wacc=0.10,
        terminal_growth=0.02,
        net_debt=0.0,
        shares=10.0,
    )
    p = r["projections"][0]
    assert p["change_nwc"] == pytest.approx(110.0 * 0.05)  # revenue × nwc%sales
    assert p["fcf"] == pytest.approx(110.0 * 0.20 - 5.5)  # EBIAT + 0 − 0 − ΔNWC


def _full_row():
    return {
        "fiscal_date": "2024-12-31",
        "fiscal_year": "2024",
        "revenue": 1000.0,
        "operating_income": 200.0,
        "income_tax": 40.0,
        "pretax_income": 200.0,
        "d_and_a": 50.0,
        "capex": -60.0,
        "change_in_nwc": -5.0,
        "debt": 300.0,
        "cash": 100.0,
        "short_term_investments": 50.0,
        "minority_interest": 20.0,
        "diluted_shares": 1000.0,
    }


def test_equity_bridge_uses_cash_sti_debt_minority(monkeypatch):
    monkeypatch.setattr(
        fp,
        "get_financial_statements",
        lambda t, *, period, limit: fp.ProviderResult(
            data=[_full_row(), _full_row()], source="fmp", as_of="2024-12-31", coverage=1.0
        ),
    )
    monkeypatch.setattr(
        fp,
        "get_profile",
        lambda t: fp.ProviderResult(
            data=fp.CompanyProfile(ticker=t, name="Acme", beta=1.0, price=10.0, market_cap=5000.0)
        ),
    )
    out = dcf.build_dcf("ACME")
    assert out.cash == 100.0 and out.short_term_investments == 50.0
    assert out.total_debt == 300.0 and out.minority_interest == 20.0
    # net_debt = debt + minority − cash − ST inv = 300 + 20 − 100 − 50 = 170
    assert out.inputs.net_debt.value == pytest.approx(170.0)
    if out.valid:
        assert out.equity_value == pytest.approx(out.enterprise_value - 170.0)


def test_historical_rows_surfaced_with_derivations(mock_fmp):
    out = dcf.build_dcf("ACME")
    assert len(out.historical) == 4
    assert out.historical[0].fiscal_year == "2021"  # oldest first
    assert out.historical[-1].fiscal_year == "2024"
    assert out.historical[-1].ebit_margin == pytest.approx(0.30)  # op income / revenue
    assert out.historical[-1].revenue_growth is not None
    assert out.valuation_date == "2024-12-31"


def test_wacc_breakdown_carries_source_types(mock_fmp):
    inp = dcf.build_dcf_input("ACME")
    by = {a.name: a for a in inp.wacc_breakdown}
    assert by["beta"].source_type == "reported"  # profile beta
    assert by["cost_of_equity"].source_type == "derived"
    assert all(
        a.source_type in ("reported", "derived", "default", "user_override", "unavailable")
        for a in inp.wacc_breakdown
    )


# ── TTM fallbacks + exact missing-field warnings (data-pipeline hardening) ──


def test_base_revenue_and_margin_ttm_fallback_when_annual_missing(monkeypatch):
    """Annual statements empty, quarterly present → base revenue = TTM (sum of 4Q)
    and operating margin = TTM op income / TTM revenue, both labeled derived."""

    def _stmts(t, *, period, limit):
        if period == "annual":
            return fp.ProviderResult(data=None, warnings=["no_income_statement"])
        q = [
            {"fiscal_date": f"2024-{m:02d}-30", "revenue": 250.0, "operating_income": 50.0}
            for m in (12, 9, 6, 3)
        ]
        return fp.ProviderResult(data=q, source="fmp", as_of="2024-12-30", coverage=0.8)

    monkeypatch.setattr(fp, "get_financial_statements", _stmts)
    monkeypatch.setattr(
        fp,
        "get_profile",
        lambda t: fp.ProviderResult(
            data=fp.CompanyProfile(ticker=t, name="Acme", beta=1.0, price=10.0, market_cap=5000.0)
        ),
    )
    inp = dcf.build_dcf_input("ACME")
    assert inp.base_revenue.source_type == "derived"
    assert inp.base_revenue.source == "derived:ttm_quarters"
    assert inp.base_revenue.value == pytest.approx(1000.0)  # 4 × 250
    assert inp.operating_margin[0].source == "derived:ttm_operating_margin"
    assert inp.operating_margin[0].value == pytest.approx(0.2)  # 200 / 1000


def test_dcf_warning_lists_exact_missing_fields(monkeypatch):
    monkeypatch.setattr(
        fp,
        "get_financial_statements",
        lambda t, *, period, limit: fp.ProviderResult(data=None, warnings=["x"]),
    )
    monkeypatch.setattr(fp, "get_profile", lambda t: fp.ProviderResult(data=None))
    out = dcf.build_dcf("ZZZ")
    assert out.valid is False
    w = " ".join(out.warnings)
    # Exact missing fields, not a generic "insufficient inputs".
    assert "base_revenue" in w and "operating_margin" in w
    # The missing-data items are surfaced on the input for the UI.
    assert {m.dataset for m in out.inputs.missing_data} >= {"base_revenue", "operating_margin"}
