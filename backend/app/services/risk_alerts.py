"""Deterministic top-risk alerts.

Pure Python — every alert's headline, severity, metric and suggested follow-up
question is derived from numbers the caller already computed. The LLM is NEVER
involved here (it only runs later if the user clicks an alert's "Ask Copilot"
CTA, which routes through the existing /copilot path). Mirrors risk_explain's
"numbers → labels" discipline so the proactive cards can never invent a figure.

Thresholds live here, documented in one place, so the rules are auditable.
"""

from __future__ import annotations

from ..schemas.risk_alerts import RiskAlert, RiskAlertsInput

# ── tunable thresholds (aligned with risk_explain.py where shared) ──────────
_CONC_HIGH = 0.40  # one name ≥40% of VaR
_CONC_MOD = 0.30
_SECTOR_HIGH = 0.50  # one sector ≥50% of the book
_SECTOR_MOD = 0.35
_LEV_HIGH = 2.0  # gross/equity leverage
_LEV_MOD = 1.5
_STRESS_HIGH = 0.25  # ≥25% loss under the stress shock
_STRESS_MOD = 0.15
_VOL_HIGH = 0.30  # 30% annualized
_VOL_MOD = 0.22
_DD_HIGH = -0.45  # max drawdown at/under −45%
_DD_MOD = -0.32

_SEVERITY_RANK = {"high": 3, "elevated": 2, "moderate": 1, "low": 0}

_OPTION_FLAG_LABEL = {
    "short_gamma": "net short gamma",
    "large_negative_theta": "heavy time decay (theta)",
    "concentrated_expiry": "clustered expiry",
    "high_single_underlying": "single-underlying concentration",
    "under_collateralized_short": "under-collateralized short",
    "uncovered_short_call": "uncovered short call",
    "missing_option_data": "incomplete option data",
}


def _pct(x: float) -> str:
    return f"{x * 100:.0f}%"


def build_risk_alerts(inp: RiskAlertsInput, *, limit: int = 5) -> list[RiskAlert]:
    """Return the top-`limit` deterministic risk alerts, ranked by severity.
    At most one alert per type; only fires a type when its threshold is met."""
    alerts: list[RiskAlert] = []

    # ── single-name concentration ───────────────────────────────────────────
    cv = sorted(inp.component_var_pct, key=lambda r: r.pct, reverse=True)
    top = cv[0] if cv else None
    conc = inp.concentration
    name = top.ticker if top else (conc.top_holding_ticker if conc else None)
    weight = top.pct if top else (conc.top_holding_weight if conc else None)
    if name and weight is not None:
        sev = "high" if weight >= _CONC_HIGH else "elevated" if weight >= _CONC_MOD else None
        if sev:
            alerts.append(
                RiskAlert(
                    type="concentration",
                    severity=sev,
                    headline=f"{name} drives {_pct(weight)} of your risk",
                    detail=f"A single position concentrates much of your downside in {name}.",
                    metric=f"{_pct(weight)} of portfolio VaR",
                    ask_copilot=f"Why is {name} the biggest risk in my portfolio?",
                )
            )

    # ── sector / theme concentration ────────────────────────────────────────
    if conc and conc.top_sector and conc.top_sector_weight is not None:
        w = conc.top_sector_weight
        sev = "high" if w >= _SECTOR_HIGH else "elevated" if w >= _SECTOR_MOD else None
        if sev:
            alerts.append(
                RiskAlert(
                    type="sector",
                    severity=sev,
                    headline=f"{_pct(w)} of your book is in {conc.top_sector}",
                    detail=f"One sector shock to {conc.top_sector} moves most of your portfolio at once.",
                    metric=f"{_pct(w)} {conc.top_sector}",
                    ask_copilot=f"How concentrated is my {conc.top_sector} exposure?",
                )
            )

    # ── margin fragility ────────────────────────────────────────────────────
    if inp.leverage and inp.leverage > 1.0001:
        lev = inp.leverage
        sev = "high" if lev >= _LEV_HIGH else "elevated" if lev >= _LEV_MOD else "moderate"
        cost = inp.margin_cost_annual
        cost_txt = f", costing ~{cost * 100:.1f}%/yr" if cost else ""
        alerts.append(
            RiskAlert(
                type="margin",
                severity=sev,
                headline=f"You're running {lev:.1f}× leverage",
                detail=f"Margin amplifies losses{cost_txt}; a drawdown hits your equity ~{lev:.1f}× harder.",
                metric=f"{lev:.2f}× gross/equity",
                ask_copilot="Am I over-leveraged, and what happens to my margin in a selloff?",
            )
        )

    # ── stress loss ─────────────────────────────────────────────────────────
    if inp.stress_loss is not None and inp.stress_loss >= _STRESS_MOD:
        sev = "high" if inp.stress_loss >= _STRESS_HIGH else "elevated"
        shock = inp.stress_market_shock
        shock_txt = f"A {_pct(abs(shock))} market drop" if shock else "A market shock"
        worst = sorted(inp.stress_asset_losses, key=lambda r: r.loss_pct)[:1]
        worst_txt = f" {worst[0].ticker} leads the loss." if worst else ""
        alerts.append(
            RiskAlert(
                type="stress",
                severity=sev,
                headline=f"{shock_txt} ≈ −{_pct(inp.stress_loss)} of your book",
                detail=f"Your largest modelled stress loss is material.{worst_txt}",
                metric=f"−{_pct(inp.stress_loss)} under stress",
                ask_copilot="What would hurt my portfolio most in a crash?",
            )
        )

    # ── options exposure ────────────────────────────────────────────────────
    if inp.option_flags:
        flag = inp.option_flags[0]
        label = _OPTION_FLAG_LABEL.get(flag, flag.replace("_", " "))
        alerts.append(
            RiskAlert(
                type="options",
                severity="elevated",
                headline=f"Options risk: {label}",
                detail="Your option positions carry a flagged exposure worth inspecting before expiry.",
                metric=label,
                # Phrased to route to the options_risk intent (avoids the
                # explain_metric 'explain'/'what is' triggers).
                ask_copilot="How risky are my options positions before expiry?",
            )
        )

    # ── volatility / drawdown (work even with score-only input) ─────────────
    if inp.annual_volatility is not None and inp.annual_volatility >= _VOL_MOD:
        sev = "elevated" if inp.annual_volatility >= _VOL_HIGH else "moderate"
        alerts.append(
            RiskAlert(
                type="volatility",
                severity=sev,
                headline=f"High volatility — {_pct(inp.annual_volatility)}/yr",
                detail="Annualized volatility is high for a core book; expect larger swings.",
                metric=f"{_pct(inp.annual_volatility)} ann. vol",
                ask_copilot="Why is my portfolio so volatile?",
            )
        )
    if inp.max_drawdown is not None and inp.max_drawdown <= _DD_MOD:
        sev = "high" if inp.max_drawdown <= _DD_HIGH else "elevated"
        alerts.append(
            RiskAlert(
                type="drawdown",
                severity=sev,
                headline=f"Deep drawdown risk — {_pct(inp.max_drawdown)}",
                detail="The modelled max drawdown is large; a sustained selloff could be painful.",
                metric=f"{_pct(inp.max_drawdown)} max drawdown",
                ask_copilot="How bad could my drawdown get?",
            )
        )

    alerts.sort(key=lambda a: _SEVERITY_RANK.get(a.severity, 0), reverse=True)
    return alerts[:limit]
