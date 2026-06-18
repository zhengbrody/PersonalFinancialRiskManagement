"""Deterministic DCF engine — pure math, guardrails, scenarios, sensitivity,
assumption source_type, and fail-soft builder (offline provider)."""

from __future__ import annotations

import pytest

from backend.app.schemas.valuation import DCFOverrides
from backend.app.services import research_dcf as dcf
from backend.app.services.providers import fmp_provider as fp

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
    inp = dcf.build_dcf_input("ZZZ")
    assert inp.base_revenue.source_type == "unavailable"
    assert inp.diluted_shares.source_type == "unavailable"
    assert inp.wacc.source_type == "default"  # no beta → labeled default
    assert {m.dataset for m in inp.missing_data} >= {
        "income_annual",
        "base_revenue",
        "diluted_shares",
    }


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
