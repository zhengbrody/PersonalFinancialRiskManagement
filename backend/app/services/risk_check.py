"""Retail-readable risk brief. Pure projection: no provider, LLM or new math.

Values retain their source field, unit, horizon and basis. Severity belongs to
the existing risk-dimensions service. Missing measurements never imply safety.
"""

import math
from uuid import uuid4

from ..schemas.risk import RiskReportOut
from ..schemas.risk_check import CheckFinding, CheckMetric, CheckStrategy, RiskCheck


def build_risk_check(
    report: RiskReportOut,
    *,
    portfolio_id: str,
    computed_at: str,
    price_history_as_of: str | None,
    has_options: bool,
    option_results: list[dict] | None = None,
    expected_option_legs: int = 0,
) -> RiskCheck:
    metrics: list[CheckMetric] = []

    def add(key, label, value, unit, horizon, basis, explanation, source):
        value = value if isinstance(value, (int, float)) and math.isfinite(value) else None
        metrics.append(
            CheckMetric(
                key=key,
                label=label,
                value=value,
                unit=unit,
                horizon=horizon,
                basis=basis,
                explanation=explanation,
                source_field=source,
            )
        )

    losses = report.losses
    for key, label, explanation in (
        (
            "var_1d_95",
            "A bad day: estimated loss threshold",
            "Historical 95% one-day VaR. Losses exceeded this threshold in about 5% of the modeled sample; it is not a maximum loss or a forecast.",
        ),
        (
            "cvar_1d_95",
            "When that bad day gets worse",
            "Expected shortfall (CVaR): average loss in the modeled worst 5% of days. Actual losses can be larger.",
        ),
    ):
        figure = getattr(losses, key, None)
        # Never relabel the 21-day Monte Carlo headline as a one-day figure.
        usable = figure is not None and figure.horizon == "1d"
        positive_basis = (
            losses is not None
            and losses.basis_value is not None
            and math.isfinite(losses.basis_value)
            and losses.basis_value > 0
        )
        add(
            key,
            label,
            figure.usd if usable and positive_basis else None,
            "usd",
            "1 trading day",
            "Report net-equity basis",
            explanation,
            f"losses.{key}.usd",
        )
    add(
        "volatility",
        "How widely returns can swing",
        report.annual_volatility,
        "fraction",
        "Annualized historical model",
        "Report portfolio risk model",
        "Volatility measures dispersion, not a loss limit. It does not describe the order or depth of losses.",
        "annual_volatility",
    )
    concentration = report.concentration
    add(
        "concentration",
        "Largest single-name exposure",
        concentration.top_holding_weight if concentration else None,
        "fraction",
        "Current modeled exposure",
        "Invested exposure; cash excluded; options may use delta equivalents",
        "A large position can dominate exposure. Position weight is not the same as its contribution to total risk.",
        "concentration.top_holding_weight",
    )
    market_factor = next((row for row in report.factor_betas if row.factor == "SPY"), None)
    add(
        "beta",
        "Modeled basket's market sensitivity",
        market_factor.beta if market_factor else None,
        "multiple",
        "Historical regression",
        "Portfolio-factor regression against SPY; before account-level leverage scaling",
        "Beta describes the modeled invested basket's market sensitivity. It is not a single holding's beta, a leverage-adjusted account beta, correlation or a loss limit.",
        "factor_betas[SPY].beta",
    )
    add(
        "diversification",
        "Are different names really diversifying?",
        report.correlation.diversification_ratio if report.correlation else None,
        "multiple",
        "Historical model",
        "Weighted asset volatility divided by portfolio volatility",
        "Higher values indicate greater historical diversification benefit. Correlations can rise during stress.",
        "correlation.diversification_ratio",
    )
    positive_contributors = [
        r for r in report.component_var_pct if math.isfinite(r.pct) and r.pct > 0
    ]
    driver = max(positive_contributors, key=lambda r: r.pct, default=None)
    add(
        "risk_driver",
        f"Largest positive VaR contributor{': ' + driver.ticker if driver else ''}",
        driver.pct if driver else None,
        "fraction",
        "Engine VaR decomposition",
        "Share of total modeled VaR; not a holding weight",
        "Risk contribution is different from money invested. Hedging contributions may be negative, so positive contributions can exceed 100%.",
        "component_var_pct",
    )
    financing = report.financing_resilience
    add(
        "financing",
        "Loan left after estimated liquid offsets",
        financing.residual_margin if financing else None,
        "usd",
        "Current-value estimate",
        "Cash and eligible cash-equivalent liquidation estimate",
        "An offset is not an executed repayment or a broker guarantee. Settlement, slippage and house requirements can change the outcome.",
        "financing_resilience.residual_margin",
    )
    add(
        "stress",
        "Loss in the selected market shock",
        (
            losses.stress.usd
            if losses
            and losses.stress
            and losses.basis_value is not None
            and math.isfinite(losses.basis_value)
            and losses.basis_value > 0
            else None
        ),
        "usd",
        "Hypothetical scenario, not a time forecast",
        "Report net-equity basis",
        "This is a modeled scenario, not a prediction or maximum loss. The market shock is a user/default assumption.",
        "losses.stress.usd",
    )
    add(
        "shock",
        "Assumed market move",
        report.stress_market_shock,
        "fraction",
        "Hypothetical scenario",
        "Broad-market shock input",
        "This assumption is not an observed market return.",
        "stress_market_shock",
    )

    strategies = strategy_checks(option_results, expected_option_legs)
    limitations = list(report.data_quality_notes)
    if has_options:
        limitations.append(
            "Options in this account-risk report use a delta approximation. These figures are not strategy-level expiry maximum losses and do not fully capture gamma, vega, time decay or early assignment."
        )
        limitations.append(
            "Expiry groups net all option legs with the same underlying and expiry, not original orders. Stock coverage is not included; cross-expiry groups must not be added into a single maximum loss. Entry, current-mark and mixed premium bases are different measurements."
        )
        if not strategies:
            limitations.append(
                "Strategy bounds are unavailable because a complete, valid set of option legs was not returned."
            )
    limitations.extend(
        [
            "Current-holdings historical risk is not your realized YTD return. Deposits are not investment gains.",
            "Report components can use different historical windows. The price-history date below is not a synchronized live quote for every metric.",
        ]
    )
    confidence = report.data_confidence
    missing = [m.label for m in metrics if m.value is None]
    limited = bool(
        missing
        or has_options
        or report.data_quality_notes
        or confidence is None
        or confidence.label == "low"
        or confidence.stale
        or not confidence.directional_allowed
    )
    findings: list[CheckFinding] = []
    if limited:
        findings.append(
            CheckFinding(
                key="coverage",
                title="Understand the coverage limits first",
                severity="info",
                explanation=("Unavailable: " + "; ".join(missing) + ". " if missing else "")
                + "This check covers the available model inputs, not every source of account risk. Review the limitations before comparing decisions.",
            )
        )
    # A low-confidence input may show measurements, but never a ranked verdict.
    if (
        confidence is not None
        and confidence.directional_allowed
        and confidence.label != "low"
        and not confidence.stale
    ):
        severity = {"high": 0, "elevated": 1}
        ordered = sorted(
            [d for d in report.dimensions if d.measurable and d.status in severity],
            key=lambda d: (severity[d.status], d.key),
        )
        findings.extend(
            CheckFinding(key=d.key, title=d.name, severity=d.status, explanation=d.explanation)
            for d in ordered
        )
    if not findings:
        findings.append(
            CheckFinding(
                key="review",
                title="Review the modeled downside",
                severity="info",
                explanation="No elevated dimension was returned by the available checks. This is not a guarantee of safety; inspect downside and model coverage below.",
            )
        )
    return RiskCheck(
        portfolio_id=portfolio_id,
        result_id=str(uuid4()),
        computed_at=computed_at,
        price_history_as_of=price_history_as_of,
        status="limited" if limited else "ready",
        summary="Start with what can hurt this portfolio, then inspect the evidence and limitations.",
        metrics=metrics,
        strategies=strategies,
        findings=findings[:3],
        limitations=list(dict.fromkeys(limitations)),
        data_confidence=confidence,
    )


def strategy_checks(results: list[dict] | None, expected: int) -> list[CheckStrategy]:
    """Do not turn a dropped leg into a fictitious naked strategy or zero risk."""
    if not results or expected != len(results):
        return []
    for leg in results:
        if (
            not leg.get("underlying")
            or not leg.get("expiry")
            or leg.get("option_type") not in ("call", "put")
        ):
            return []
        for key in ("quantity", "strike", "contract_multiplier"):
            value = leg.get(key)
            if not isinstance(value, (int, float)) or not math.isfinite(value) or value == 0:
                return []
            if key != "quantity" and value < 0:
                return []
        for key in ("cost_basis", "mark", "spot"):
            value = leg.get(key)
            if value is not None and (
                not isinstance(value, (int, float)) or not math.isfinite(value)
            ):
                return []
        # A signed entry cost must agree with the signed position; do not
        # reinterpret a direction conflict as a cheap spread.
        cost = leg.get("cost_basis")
        if cost is not None and cost * leg["quantity"] < 0:
            return []
        if any(leg.get(key) is not None and leg[key] < 0 for key in ("mark", "spot")):
            return []
    from .options_strategies import build_strategies

    out = []
    for group in build_strategies(results):
        measurable = bool(group["payoff"]) and group["premium_basis"] != "unavailable"
        out.append(
            CheckStrategy(
                underlying=group["underlying"],
                expiry=group["expiry"],
                name=group["name"],
                leg_count=group["leg_count"],
                premium_basis=group["premium_basis"],
                max_loss=group["max_loss"] if measurable else None,
                max_gain=group["max_gain"] if measurable else None,
                loss_status=(
                    ("bounded" if group["max_loss"] is not None else "unbounded")
                    if measurable
                    else "unavailable"
                ),
                gain_status=(
                    ("bounded" if group["max_gain"] is not None else "unbounded")
                    if measurable
                    else "unavailable"
                ),
            )
        )
    return out
