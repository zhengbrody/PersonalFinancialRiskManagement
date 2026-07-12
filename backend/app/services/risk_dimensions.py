"""Explainable risk-cockpit assembly — turn the report's already-computed
numbers into the unified per-dimension model + the %/$ loss breakdown.

Pure, deterministic, NO new risk math and NO LLM: every value is read from the
serialized ``RiskReportOut`` (or a small ``DimensionContext`` of extras the
endpoint already derived — portfolio beta, leverage, net option delta-notional,
current drawdown). Status bands, plain-English explanations and the Copilot
prompts are fixed lookups. Percentiles come from the user's own snapshot history
via ``metric_history.percentile_rank``.

Design notes:
  * A dimension the book can't measure (no options, no liquidity data) is emitted
    with ``measurable=False`` + ``status='n/a'`` — never a fake zero.
  * ``contribution`` is a severity-normalised ATTENTION share (sums to ~1 across
    the measurable dimensions), NOT a variance decomposition — the dimensions
    overlap. The name is honest in the UI.
  * ``percentile`` is the raw position of the current value in the user's history
    (fraction ≤ current); the per-dimension explanation says whether high is good
    or bad, so no confusing inversion.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

from ..schemas.risk import (
    LossBreakdown,
    LossFigure,
    MarginBuffer,
    RiskDimension,
    RiskReportOut,
)
from . import metric_history

# Reg-T style maintenance requirement (conservative; real broker reqs vary).
_MAINTENANCE_FRACTION = 0.25

# Severity weight per status band → the attention-share normaliser.
_SEVERITY = {"calm": 0.10, "normal": 0.35, "elevated": 0.70, "high": 1.0, "n/a": 0.0}

# Confidence ordering for per-dimension min().
_CONF_ORDER = {"low": 0, "medium": 1, "high": 2}


@dataclass
class DimensionContext:
    """Extras the report endpoint already derived, threaded in so the assembler
    stays a pure function over data (no re-fetch, no recompute)."""

    portfolio_beta: Optional[float] = None
    leverage: Optional[float] = None
    net_option_delta_notional: Optional[float] = None  # signed $, net across options
    has_options: bool = False
    current_drawdown: Optional[float] = None  # fraction, positive
    net_equity: Optional[float] = None
    observations: Optional[int] = None
    base_confidence: Optional[str] = None  # report-level high|medium|low
    history: list[dict] = field(default_factory=list)  # get_snapshot_history rows


# ── small formatters ──────────────────────────────────────────────────────────
def _finite(v: object) -> Optional[float]:
    try:
        x = float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _pct(v: Optional[float]) -> Optional[str]:
    return None if v is None else f"{v * 100:.1f}%"


def _x(v: Optional[float]) -> Optional[str]:
    return None if v is None else f"{v:.2f}×"


def _ratio(v: Optional[float]) -> Optional[str]:
    return None if v is None else f"{v:.2f}"


def _band(value: Optional[float], calm: float, normal: float, elevated: float) -> str:
    """Ascending band: value < calm → calm, < normal → normal, < elevated →
    elevated, else high. ``None`` → n/a."""
    if value is None:
        return "n/a"
    if value < calm:
        return "calm"
    if value < normal:
        return "normal"
    if value < elevated:
        return "elevated"
    return "high"


def _cap_conf(base: Optional[str], cap: str) -> str:
    """min(base, cap) over the low<medium<high ordering. Missing base = cap."""
    if base not in _CONF_ORDER:
        return cap
    return base if _CONF_ORDER[base] <= _CONF_ORDER[cap] else cap


def _history_series(history: list[dict], key: str) -> list[object]:
    return [r.get(key) for r in history if isinstance(r, dict)]


def _portfolio_beta_from_report(report: RiskReportOut) -> Optional[float]:
    """Portfolio market beta = the SPY row of the factor regression (NOT the
    per-holding ``betas`` map)."""
    for row in report.factor_betas or []:
        if str(getattr(row, "factor", "")).upper() == "SPY":
            return _finite(getattr(row, "beta", None))
    return None


# ── per-dimension builders ─────────────────────────────────────────────────────
def _dim_concentration(report: RiskReportOut, ctx: DimensionContext) -> RiskDimension:
    c = report.concentration
    top = _finite(getattr(c, "top_holding_weight", None)) if c else None
    ticker = getattr(c, "top_holding_ticker", None) if c else None
    status = _band(top, 0.15, 0.25, 0.40)
    pct, n = metric_history.percentile_rank(
        _history_series(ctx.history, "concentration_top_holding"), top
    )
    if top is None:
        expl = "Couldn't measure single-name concentration for this book."
    else:
        who = f" ({ticker})" if ticker else ""
        expl = f"Your largest position{who} is {top * 100:.0f}% of the invested book" + (
            " — a big single-name bet; a shock there moves the whole portfolio."
            if status in ("elevated", "high")
            else " — reasonably spread across names."
        )
    return RiskDimension(
        key="concentration",
        name="Concentration",
        value=top,
        display=_pct(top),
        unit="pct",
        status=status,
        percentile=pct,
        percentile_n=n,
        confidence=_cap_conf(ctx.base_confidence, "high") if top is not None else "low",
        explanation=expl,
        action="How concentrated is my portfolio and what would reduce single-name risk?",
        measurable=top is not None,
    )


def _dim_volatility(report: RiskReportOut, ctx: DimensionContext) -> RiskDimension:
    vol = _finite(report.annual_volatility)
    rv = report.rolling_volatility
    # Prefer the rolling-vol state label (already a calm/normal/elevated read);
    # fall back to an annualized-vol band.
    rv_state = getattr(rv, "state", None) if rv else None
    status = (
        rv_state if rv_state in ("calm", "normal", "elevated") else _band(vol, 0.12, 0.20, 0.30)
    )
    # bump elevated→high for a genuinely extreme level even if rolling said elevated
    if vol is not None and vol >= 0.35:
        status = "high"
    pct, n = metric_history.percentile_rank(_history_series(ctx.history, "annual_volatility"), vol)
    expl = (
        f"Annualized volatility is {vol * 100:.0f}%."
        if vol is not None
        else "Couldn't estimate volatility."
    )
    if status in ("elevated", "high"):
        expl += " Expect larger day-to-day swings than a broad index."
    return RiskDimension(
        key="volatility",
        name="Volatility",
        value=vol,
        display=_pct(vol),
        unit="pct",
        status=status,
        percentile=pct,
        percentile_n=n,
        confidence=_cap_conf(ctx.base_confidence, "high") if vol is not None else "low",
        explanation=expl,
        action="Is my portfolio's volatility high, and what drives it?",
        measurable=vol is not None,
    )


def _dim_drawdown(report: RiskReportOut, ctx: DimensionContext) -> RiskDimension:
    cur = _finite(ctx.current_drawdown)
    worst = _finite(report.max_drawdown)
    # Value = CURRENT drawdown from peak (0 = at a high); worst is context.
    value = cur if cur is not None else worst
    status = _band(value, 0.05, 0.15, 0.30)
    pct, n = metric_history.percentile_rank(_history_series(ctx.history, "max_drawdown"), worst)
    if cur is None and worst is None:
        expl = "Couldn't compute drawdown."
    elif cur is not None and cur < 0.01:
        expl = "You're at (or near) a portfolio high — no active drawdown right now."
        if worst is not None:
            expl += f" Worst historical drawdown in the window was {worst * 100:.0f}%."
    else:
        expl = f"You're {value * 100:.0f}% below your recent peak."
        if worst is not None and cur is not None and worst > cur + 0.02:
            expl += f" The worst in the window was {worst * 100:.0f}%."
    return RiskDimension(
        key="drawdown",
        name="Drawdown",
        value=value,
        display=_pct(value),
        unit="pct",
        status=status,
        percentile=pct,
        percentile_n=n,
        confidence=_cap_conf(ctx.base_confidence, "high") if value is not None else "low",
        explanation=expl,
        action="How deep is my current drawdown and how does it compare to history?",
        measurable=value is not None,
    )


def _dim_beta(report: RiskReportOut, ctx: DimensionContext) -> RiskDimension:
    beta = _finite(ctx.portfolio_beta)
    if beta is None:
        beta = _portfolio_beta_from_report(report)
    status = _band(abs(beta) if beta is not None else None, 0.30, 0.80, 1.20)
    pct, n = metric_history.percentile_rank(_history_series(ctx.history, "beta_to_benchmark"), beta)
    thin = (ctx.observations or 0) < 60
    if beta is None:
        expl = "Couldn't estimate market beta (too little overlapping history)."
    else:
        expl = f"Market beta is {beta:.2f} — a 1% market move implies about {beta:.2f}% here."
        if abs(beta) >= 1.2:
            expl += " You amplify market moves."
        elif abs(beta) < 0.3:
            expl += " You move largely independently of the market."
    return RiskDimension(
        key="beta",
        name="Market beta",
        value=beta,
        display=_ratio(beta),
        unit="ratio",
        status=status,
        percentile=pct,
        percentile_n=n,
        confidence=(
            _cap_conf(ctx.base_confidence, "low" if thin else "high") if beta is not None else "low"
        ),
        explanation=expl,
        action="What's my market beta and what would make me less sensitive to a selloff?",
        measurable=beta is not None,
    )


def _dim_correlation(report: RiskReportOut, ctx: DimensionContext) -> RiskDimension:
    corr = report.correlation
    dr = _finite(getattr(corr, "diversification_ratio", None)) if corr else None
    avg = _finite(getattr(corr, "avg_pairwise", None)) if corr else None
    # Higher DR = better diversified. Descending band → invert via a helper.
    if dr is None:
        status = "n/a"
    elif dr >= 1.5:
        status = "calm"
    elif dr >= 1.3:
        status = "normal"
    elif dr >= 1.15:
        status = "elevated"
    else:
        status = "high"
    thin = (ctx.observations or 0) < 60
    if dr is None:
        expl = "Not enough holdings/history to measure correlation clustering."
    else:
        expl = f"Diversification ratio is {dr:.2f}"
        if avg is not None:
            expl += f" (average pairwise correlation {avg:.2f})"
        expl += (
            " — your names move together, so diversification is doing little."
            if status in ("elevated", "high")
            else " — your holdings diversify each other well."
        )
    return RiskDimension(
        key="correlation",
        name="Correlation clustering",
        value=dr,
        display=_ratio(dr),
        unit="ratio",
        status=status,
        percentile=None,  # not yet in snapshot history
        percentile_n=0,
        confidence=(
            _cap_conf(ctx.base_confidence, "low" if thin else "medium") if dr is not None else "low"
        ),
        explanation=expl,
        action="Are my holdings too correlated, and which ones cluster together?",
        measurable=dr is not None,
    )


def _dim_liquidity(report: RiskReportOut, ctx: DimensionContext) -> RiskDimension:
    rows = report.liquidity or []
    days = [
        _finite(getattr(r, "days_to_liquidate", None))
        for r in rows
        if _finite(getattr(r, "days_to_liquidate", None)) is not None
    ]
    worst = max(days) if days else None
    worst_ticker = None
    if worst is not None:
        for r in rows:
            if _finite(getattr(r, "days_to_liquidate", None)) == worst:
                worst_ticker = getattr(r, "ticker", None)
                break
    status = _band(worst, 1.0, 3.0, 7.0)
    if worst is None:
        expl = "Liquidity data (average daily volume) wasn't available for your holdings."
    else:
        who = f" ({worst_ticker})" if worst_ticker else ""
        expl = (
            f"Your least-liquid position{who} would take about {worst:.1f} trading day(s) "
            "to exit at a normal share of daily volume."
        )
        if status in ("elevated", "high"):
            expl += " Exiting quickly could move the price against you."
    return RiskDimension(
        key="liquidity",
        name="Liquidity",
        value=worst,
        display=(None if worst is None else f"{worst:.1f}d"),
        unit="days",
        status=status,
        percentile=None,
        percentile_n=0,
        confidence=(_cap_conf(ctx.base_confidence, "medium") if worst is not None else "low"),
        explanation=expl,
        action="How liquid is my portfolio and which positions are hardest to exit?",
        measurable=worst is not None,
    )


def _dim_leverage(report: RiskReportOut, ctx: DimensionContext) -> RiskDimension:
    lev = _finite(ctx.leverage)
    margin = _finite(report.margin_loan) or 0.0
    if lev is None:
        status = "n/a"
    elif lev <= 1.001:
        status = "calm"
    elif lev <= 1.5:
        status = "normal"
    elif lev <= 2.0:
        status = "elevated"
    else:
        status = "high"
    pct, n = metric_history.percentile_rank(_history_series(ctx.history, "leverage"), lev)
    if lev is None:
        expl = "Couldn't determine leverage."
    elif margin <= 0 and lev <= 1.001:
        expl = "You're unlevered (no margin loan) — market moves aren't amplified."
    else:
        expl = f"You're levered {lev:.2f}× — gains and losses are amplified by roughly that factor."
        if status in ("elevated", "high"):
            expl += " A sharp drop could trigger a margin call."
    return RiskDimension(
        key="leverage",
        name="Leverage & margin",
        value=lev,
        display=_x(lev),
        unit="x",
        status=status,
        percentile=pct,
        percentile_n=n,
        confidence=_cap_conf(ctx.base_confidence, "high") if lev is not None else "low",
        explanation=expl,
        action="How much leverage am I running and what's my margin buffer?",
        measurable=lev is not None,
    )


def _dim_options(report: RiskReportOut, ctx: DimensionContext) -> RiskDimension:
    if not ctx.has_options:
        return RiskDimension(
            key="options",
            name="Options exposure",
            status="n/a",
            explanation="No option positions in this portfolio.",
            measurable=False,
        )
    notional = _finite(ctx.net_option_delta_notional)
    ne = _finite(ctx.net_equity)
    exposure = (abs(notional) / ne) if (notional is not None and ne and ne > 0) else None
    status = _band(exposure, 0.10, 0.25, 0.50)
    if exposure is None:
        expl = "You hold options, but their delta-equivalent exposure couldn't be sized."
    else:
        direction = "long" if (notional or 0) >= 0 else "short"
        expl = (
            f"Your options add a {direction} delta-equivalent exposure of about "
            f"{exposure * 100:.0f}% of net equity."
        )
        if status in ("elevated", "high"):
            expl += " That's a material, non-linear tilt — check the options desk view."
    return RiskDimension(
        key="options",
        name="Options exposure",
        value=exposure,
        display=_pct(exposure),
        unit="pct",
        status=status,
        percentile=None,
        percentile_n=0,
        confidence=(_cap_conf(ctx.base_confidence, "medium") if exposure is not None else "low"),
        explanation=expl,
        action="What's my net options exposure and biggest option risk?",
        measurable=exposure is not None,
    )


_BUILDERS = [
    _dim_concentration,
    _dim_volatility,
    _dim_drawdown,
    _dim_beta,
    _dim_correlation,
    _dim_liquidity,
    _dim_leverage,
    _dim_options,
]


def build_dimensions(report: RiskReportOut, ctx: DimensionContext) -> list[RiskDimension]:
    """Assemble all eight risk dimensions + their severity-normalised attention
    shares. Order is stable (matches ``_BUILDERS``)."""
    dims = [b(report, ctx) for b in _BUILDERS]

    # Attention share: severity of each MEASURABLE dimension, normalised to sum 1.
    weights = [_SEVERITY.get(d.status, 0.0) if d.measurable else 0.0 for d in dims]
    total = sum(weights)
    if total > 0:
        for d, w in zip(dims, weights):
            if d.measurable and d.status != "n/a":
                d.contribution = round(w / total, 4)
    return dims


def build_losses(
    report: RiskReportOut,
    *,
    var_1d_95: Optional[float],
    cvar_1d_95: Optional[float],
    current_drawdown: Optional[float],
    net_equity: Optional[float],
    gross_assets: Optional[float],
    margin_loan: Optional[float],
) -> LossBreakdown:
    """Losses in BOTH % and $. 1-day VaR/CVaR are a genuine 1-day historical
    estimate from the report's price window; the report's headline ``var_95``
    (a 21-day Monte-Carlo number) is surfaced here correctly labelled."""
    basis = _finite(net_equity)

    def _fig(label: str, horizon: str, pct: Optional[float]) -> Optional[LossFigure]:
        p = _finite(pct)
        if p is None:
            return None
        p = abs(p)
        usd = p * basis if basis is not None else None
        return LossFigure(label=label, horizon=horizon, pct=p, usd=usd)

    v1 = _fig("1-day VaR (95%)", "1d", var_1d_95)
    c1 = _fig("1-day CVaR (95%)", "1d", cvar_1d_95)
    v21 = _fig("21-day VaR (95%)", "21d", report.var_95)
    shock = _finite(report.stress_market_shock)
    stress_label = "Stress loss" if shock is None else f"Stress ({shock * 100:.0f}% market)"
    stress = _fig(stress_label, "scenario", report.stress_loss)
    cur_dd = _fig("Current drawdown", "current", current_drawdown)

    # Margin buffer: how much equity sits above the maintenance line.
    buf = MarginBuffer(status="n/a")
    gross = _finite(gross_assets)
    loan = _finite(margin_loan)
    if basis is not None and gross is not None:
        maint = _MAINTENANCE_FRACTION * gross
        buffer_usd = basis - maint
        buf = MarginBuffer(
            net_equity=basis,
            margin_loan=loan,
            gross_assets=gross,
            maintenance_requirement=maint,
            buffer_usd=buffer_usd,
            buffer_pct=(buffer_usd / gross if gross > 0 else None),
            status=_margin_status(loan, buffer_usd, gross),
        )

    return LossBreakdown(
        basis_value=basis,
        var_1d_95=v1,
        cvar_1d_95=c1,
        var_21d_95=v21,
        stress=stress,
        current_drawdown=cur_dd,
        margin_buffer=buf,
    )


def _margin_status(
    loan: Optional[float], buffer_usd: Optional[float], gross: Optional[float]
) -> str:
    if loan is None or loan <= 0:
        return "none"
    if buffer_usd is None or gross is None or gross <= 0:
        return "n/a"
    frac = buffer_usd / gross
    if frac > 0.20:
        return "comfortable"
    if frac > 0.10:
        return "tight"
    return "call_risk"
