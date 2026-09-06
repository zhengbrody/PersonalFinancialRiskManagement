"""Financial meaning, missing-data gates and deterministic projection."""

import math

import pytest

from backend.app.schemas.confidence import DataConfidence
from backend.app.schemas.risk import (
    ComponentVarRow,
    FactorBetaRow,
    LossBreakdown,
    LossFigure,
    RiskDimension,
    RiskReportOut,
)
from backend.app.services.risk_check import build_risk_check


def check(report=None, **kwargs):
    return build_risk_check(
        report or RiskReportOut(),
        portfolio_id="p1",
        computed_at="2026-09-05T12:00:00Z",
        price_history_as_of="2026-09-04",
        has_options=kwargs.get("has_options", False),
    )


def values(result):
    return {m.key: m for m in result.metrics}


def confidence(**kwargs):
    return DataConfidence(
        label="high", confidence=1, overall_coverage=1, critical_coverage=1, **kwargs
    )


def test_one_day_loss_is_not_21_day_or_cvar():
    report = RiskReportOut(
        var_95=0.3,
        cvar_95=0.4,
        losses=LossBreakdown(
            basis_value=10000,
            var_1d_95=LossFigure(horizon="1d", usd=120),
            cvar_1d_95=LossFigure(horizon="1d", usd=240),
            var_21d_95=LossFigure(horizon="21d", usd=3000),
        ),
    )
    metrics = values(check(report))
    assert metrics["var_1d_95"].value == 120
    assert metrics["cvar_1d_95"].value == 240
    assert metrics["var_1d_95"].horizon == "1 trading day"
    assert "not a maximum" in metrics["var_1d_95"].explanation


@pytest.mark.parametrize("basis", [None, 0, -100, math.inf, math.nan])
def test_nonpositive_or_missing_equity_does_not_make_dollar_claims(basis):
    result = check(
        RiskReportOut(
            losses=LossBreakdown(basis_value=basis, var_1d_95=LossFigure(horizon="1d", usd=500))
        )
    )
    assert values(result)["var_1d_95"].value is None
    assert result.status == "limited"


def test_wrong_horizon_is_unavailable():
    result = check(
        RiskReportOut(
            losses=LossBreakdown(basis_value=1000, var_1d_95=LossFigure(horizon="21d", usd=500))
        )
    )
    assert values(result)["var_1d_95"].value is None


@pytest.mark.parametrize("bad", [None, math.nan, math.inf, -math.inf])
def test_missing_nonfinite_not_zero(bad):
    result = check(RiskReportOut(annual_volatility=bad))
    assert values(result)["volatility"].value is None
    assert result.status == "limited"
    assert result.findings[0].key == "coverage"
    result.model_dump_json()


def test_real_zero_remains_zero():
    assert values(check(RiskReportOut(annual_volatility=0)))["volatility"].value == 0


def test_beta_is_portfolio_regression_not_spy_holdings_beta():
    report = RiskReportOut(
        betas={"SPY": 1.0, "XYZ": 2.1},
        factor_betas=[FactorBetaRow(factor="SPY", beta=1.6)],
    )
    metric = values(check(report))["beta"]
    assert metric.value == 1.6
    assert metric.source_field == "factor_betas[SPY].beta"
    assert "before account-level leverage" in metric.basis
    report.factor_betas = []
    assert values(check(report))["beta"].value is None


def test_options_limit_is_always_visible():
    result = check(has_options=True)
    assert result.status == "limited"
    assert any("not strategy-level expiry maximum losses" in s for s in result.limitations)


@pytest.mark.parametrize(
    "conf", [None, confidence(directional_allowed=False), confidence(stale=True)]
)
def test_no_ranked_verdict_with_unverified_inputs(conf):
    result = check(
        RiskReportOut(
            data_confidence=conf,
            dimensions=[
                RiskDimension(
                    key="concentration",
                    name="Concentration",
                    status="high",
                    explanation="High concentration.",
                )
            ],
        )
    )
    assert [f.key for f in result.findings] == ["coverage"]


def test_existing_severity_is_preserved_and_capped():
    result = check(
        RiskReportOut(
            data_confidence=confidence(),
            dimensions=[
                RiskDimension(
                    key="beta", name="Beta", status="elevated", explanation="Beta warning."
                ),
                RiskDimension(
                    key="concentration",
                    name="Concentration",
                    status="high",
                    explanation="Concentration warning.",
                ),
                RiskDimension(
                    key="leverage", name="Leverage", status="high", explanation="Leverage warning."
                ),
            ],
        )
    )
    assert len(result.findings) == 3
    assert result.findings[1].key == "concentration"
    assert result.findings[1].explanation == "Concentration warning."


def test_contribution_keeps_hedging_sign_and_does_not_renormalize():
    report = RiskReportOut(
        component_var_pct=[
            ComponentVarRow(ticker="A", pct=1.2),
            ComponentVarRow(ticker="B", pct=-0.2),
        ]
    )
    result = values(check(report))["risk_driver"]
    assert result.value == 1.2
    assert result.label.endswith(": A")
    assert "not a holding weight" in result.basis


def test_no_return_or_principal_as_ytd_metric():
    result = check(
        RiskReportOut(annual_return=-0.175, contributed_capital=50000, total_return=0.06)
    )
    assert not {"ytd", "annual_return", "contributed_capital"} & {m.key for m in result.metrics}
    assert any("Deposits are not investment gains" in s for s in result.limitations)
    assert result.computed_at != result.price_history_as_of


def test_projection_does_not_mutate_report():
    report = RiskReportOut(data_quality_notes=["Missing cost"])
    before = report.model_dump()
    check(report, has_options=True)
    assert report.model_dump() == before


def legs(expiry="2027-01-15"):
    return [
        dict(
            underlying="XYZ",
            expiry=expiry,
            option_type="call",
            quantity=1,
            strike=100,
            contract_multiplier=100,
            cost_basis=1000,
            mark=10,
            spot=105,
        ),
        dict(
            underlying="XYZ",
            expiry=expiry,
            option_type="call",
            quantity=-1,
            strike=120,
            contract_multiplier=100,
            cost_basis=-600,
            mark=6,
            spot=105,
        ),
    ]


def test_strategy_reuses_exact_spread_bounds():
    from backend.app.services.risk_check import strategy_checks

    strategy = strategy_checks(legs(), 2)[0]
    assert strategy.max_loss == 400
    assert strategy.max_gain == 1600
    assert strategy.loss_status == strategy.gain_status == "bounded"
    assert strategy.premium_basis == "entry"


def test_incomplete_group_is_not_naked_risk():
    from backend.app.services.risk_check import strategy_checks

    assert strategy_checks(legs()[:1], 2) == []


def test_missing_basis_not_unbounded():
    from backend.app.services.risk_check import strategy_checks

    rows = legs()
    rows[0].update(cost_basis=None, mark=None)
    strategy = strategy_checks(rows, 2)[0]
    assert strategy.premium_basis == "unavailable"
    assert strategy.loss_status == strategy.gain_status == "unavailable"


def test_mixed_basis_and_cross_expiry_are_not_original_trade_loss():
    from backend.app.services.risk_check import strategy_checks

    rows = legs()
    rows[0]["cost_basis"] = None
    assert strategy_checks(rows, 2)[0].premium_basis == "mixed"
    rows[1]["expiry"] = "2027-02-19"
    assert len(strategy_checks(rows, 2)) == 2


@pytest.mark.parametrize(
    "key,value",
    [
        ("cost_basis", -1000),
        ("quantity", 0),
        ("strike", -1),
        ("mark", math.nan),
        ("mark", -1),
        ("spot", -1),
    ],
)
def test_invalid_strategy_inputs_fail_closed(key, value):
    from backend.app.services.risk_check import strategy_checks

    rows = legs()
    rows[0][key] = value
    assert strategy_checks(rows, 2) == []
