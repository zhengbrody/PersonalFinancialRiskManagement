"""Deterministic risk-alert builder + endpoint. No LLM, no network."""

from __future__ import annotations

from backend.app.schemas.risk_alerts import (
    AlertComponentVar,
    AlertConcentration,
    AlertStressLoss,
    RiskAlertsInput,
)
from backend.app.services.risk_alerts import build_risk_alerts


def test_concentration_alert_fires_high_and_cites_the_name():
    inp = RiskAlertsInput(
        component_var_pct=[
            AlertComponentVar(ticker="NVDA", pct=0.55),
            AlertComponentVar(ticker="AAPL", pct=0.2),
        ],
    )
    alerts = build_risk_alerts(inp)
    conc = next(a for a in alerts if a.type == "concentration")
    assert conc.severity == "high"
    assert "NVDA" in conc.headline and "55%" in conc.headline
    assert "NVDA" in conc.ask_copilot  # the follow-up question cites the name


def test_margin_alert_uses_leverage_and_cost():
    inp = RiskAlertsInput(leverage=2.5, margin_cost_annual=0.06)
    alerts = build_risk_alerts(inp)
    margin = next(a for a in alerts if a.type == "margin")
    assert margin.severity == "high"
    assert "2.5×" in margin.headline
    assert "6.0%/yr" in margin.detail


def test_stress_alert_names_worst_holding():
    inp = RiskAlertsInput(
        stress_loss=0.31,
        stress_market_shock=-0.2,
        stress_asset_losses=[
            AlertStressLoss(ticker="TSLA", loss_pct=-0.42),
            AlertStressLoss(ticker="SPY", loss_pct=-0.2),
        ],
    )
    alerts = build_risk_alerts(inp)
    stress = next(a for a in alerts if a.type == "stress")
    assert stress.severity == "high"
    assert "20%" in stress.headline and "31%" in stress.headline
    assert "TSLA" in stress.detail


def test_sector_and_options_and_vol_alerts():
    inp = RiskAlertsInput(
        annual_volatility=0.33,
        option_flags=["short_gamma"],
        concentration=AlertConcentration(top_sector="Technology", top_sector_weight=0.62),
    )
    alerts = build_risk_alerts(inp)
    types = {a.type for a in alerts}
    assert {"sector", "options", "volatility"} <= types
    sector = next(a for a in alerts if a.type == "sector")
    assert "Technology" in sector.headline and sector.severity == "high"
    opt = next(a for a in alerts if a.type == "options")
    assert "short gamma" in opt.headline


def test_below_threshold_is_quiet_and_ranking_caps():
    # A calm book: nothing breaches a threshold → no noise.
    calm = RiskAlertsInput(annual_volatility=0.10, max_drawdown=-0.12, leverage=1.0)
    assert build_risk_alerts(calm) == []

    # Ranking: high-severity alerts come first, capped at `limit`.
    busy = RiskAlertsInput(
        component_var_pct=[AlertComponentVar(ticker="X", pct=0.5)],  # high
        annual_volatility=0.24,  # moderate
        leverage=1.6,  # elevated
    )
    ranked = build_risk_alerts(busy, limit=2)
    assert len(ranked) == 2
    assert ranked[0].severity == "high"  # concentration ranked first


def test_alert_key_encodes_subject_for_lifecycle():
    # The lifecycle key must carry the SUBJECT so resolving one name/flag never
    # hides a different one of the same type/severity (the masking bug).
    conc = build_risk_alerts(
        RiskAlertsInput(component_var_pct=[AlertComponentVar(ticker="NVDA", pct=0.55)])
    )[0]
    assert conc.key == "concentration:NVDA:high"

    # Two DIFFERENT option flags → DIFFERENT keys (both are options:elevated
    # by type/severity, which is exactly the collision the subject fixes).
    k1 = build_risk_alerts(RiskAlertsInput(option_flags=["clustered_expiry"]))[0].key
    k2 = build_risk_alerts(RiskAlertsInput(option_flags=["uncovered_short_call"]))[0].key
    assert k1 != k2
    assert k1 == "options:clustered_expiry:elevated"

    # A different concentration subject is a different episode.
    aapl = build_risk_alerts(
        RiskAlertsInput(component_var_pct=[AlertComponentVar(ticker="AAPL", pct=0.6)])
    )[0]
    assert aapl.key != conc.key

    # Singleton (whole-book) alerts carry no subject.
    margin = next(a for a in build_risk_alerts(RiskAlertsInput(leverage=2.5)) if a.type == "margin")
    assert margin.key == "margin:high"


def test_endpoint_is_auth_gated_and_credit_free(client_factory=None):
    from fastapi.testclient import TestClient

    from backend.app.main import create_app

    c = TestClient(create_app())
    # No auth → 401 (route exists, gated).
    r = c.post("/api/v1/risk/alerts", json={})
    assert r.status_code == 401
