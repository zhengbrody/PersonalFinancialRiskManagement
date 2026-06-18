"""Deterministic DCF valuation engine (Phase 2).

No LLM, no randomness — a pure unlevered-FCF DCF with a Gordon-growth terminal
value, plus bear/base/bull scenarios and two sensitivity grids. Assumptions are
DERIVED from Phase-1 reported financials where possible and otherwise filled with
clearly-labeled conservative defaults; every assumption carries a `source_type`.
User overrides re-label the affected assumption `user_override`.

Hard guardrail: terminal growth must be < WACC (an equal/greater terminal growth
makes the Gordon terminal value explode/negative — we never emit that number).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from ..schemas.research import DataProvenanceItem, MissingDataItem
from ..schemas.valuation import (
    DCFAssumption,
    DCFInput,
    DCFOverrides,
    DCFProjectionYear,
    DCFScenario,
    DCFSensitivityTable,
    DCFValuationOutput,
)
from .providers import fmp_provider

_log = logging.getLogger(__name__)

# Clearly-labeled conservative defaults (used only when nothing reportable).
_DEF_TAX = 0.21
_DEF_DA_PCT = 0.04
_DEF_CAPEX_PCT = 0.04
_DEF_NWC_PCT = 0.02
_DEF_WACC = 0.09
_DEF_TERMINAL_GROWTH = 0.025
# CAPM defaults for the derived WACC.
_RISK_FREE = 0.042
_EQUITY_RISK_PREMIUM = 0.05
_DEFAULT_YEARS = 5


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── pure projection core ────────────────────────────────────────────


class InvalidDCF(ValueError):
    """Raised when assumptions can't produce a valid valuation (e.g. g ≥ WACC)."""


def project(
    *,
    base_revenue: float,
    growths: list[float],
    margins: list[float],
    tax: float,
    da_pct: float,
    capex_pct: float,
    nwc_pct: float,
    wacc: float,
    terminal_growth: float,
    net_debt: float,
    shares: float,
) -> dict:
    """Pure DCF. Returns projections + terminal value + EV/equity/per-share.
    Raises InvalidDCF for WACC ≤ 0, terminal growth ≥ WACC, or no shares."""
    if wacc is None or wacc <= 0:
        raise InvalidDCF("WACC must be positive")
    if terminal_growth >= wacc:
        raise InvalidDCF("terminal growth must be below WACC")
    if not shares or shares <= 0:
        raise InvalidDCF("diluted shares unavailable")

    rev_prev = base_revenue
    pv_sum = 0.0
    projections: list[dict] = []
    last_fcf = 0.0
    n = len(growths)
    for t in range(1, n + 1):
        g = growths[t - 1]
        m = margins[t - 1]
        rev = rev_prev * (1.0 + g)
        ebit = rev * m
        nopat = ebit * (1.0 - tax)
        da = rev * da_pct
        capex = rev * capex_pct
        dnwc = (rev - rev_prev) * nwc_pct
        fcf = nopat + da - capex - dnwc
        df = 1.0 / (1.0 + wacc) ** t
        pv = fcf * df
        projections.append(
            {
                "year": t,
                "revenue": rev,
                "revenue_growth": g,
                "operating_margin": m,
                "ebit": ebit,
                "nopat": nopat,
                "da": da,
                "capex": capex,
                "change_nwc": dnwc,
                "fcf": fcf,
                "discount_factor": df,
                "pv_fcf": pv,
            }
        )
        pv_sum += pv
        last_fcf = fcf
        rev_prev = rev

    tv = last_fcf * (1.0 + terminal_growth) / (wacc - terminal_growth)
    df_n = 1.0 / (1.0 + wacc) ** n
    pv_tv = tv * df_n
    ev = pv_sum + pv_tv
    equity = ev - net_debt
    per_share = equity / shares
    return {
        "projections": projections,
        "terminal_value": tv,
        "pv_terminal_value": pv_tv,
        "enterprise_value": ev,
        "equity_value": equity,
        "implied_value_per_share": per_share,
    }


def _per_share_or_none(**kw) -> Optional[float]:
    try:
        return project(**kw)["implied_value_per_share"]
    except InvalidDCF:
        return None


def _v(a: DCFAssumption) -> Optional[float]:
    return a.value


# ── run a full valuation over a prepared DCFInput ───────────────────


def run_dcf(inp: DCFInput, *, current_price: Optional[float]) -> DCFValuationOutput:
    out = DCFValuationOutput(
        ticker=inp.ticker,
        generated_at=_iso_now(),
        inputs=inp,
        current_price=current_price,
    )

    growths = [g.value for g in inp.revenue_growth if g.value is not None]
    margins = [m.value for m in inp.operating_margin if m.value is not None]
    base_rev = _v(inp.base_revenue)
    tax = _v(inp.tax_rate)
    wacc = _v(inp.wacc)
    tg = _v(inp.terminal_growth)
    shares = _v(inp.diluted_shares)
    net_debt = _v(inp.net_debt) or 0.0

    if base_rev is None or not growths or not margins or tax is None or wacc is None or tg is None:
        out.valid = False
        out.warnings.append("Insufficient inputs to run the DCF.")
        return out

    core = dict(
        base_revenue=base_rev,
        tax=tax,
        da_pct=_v(inp.da_pct_revenue) or 0.0,
        capex_pct=_v(inp.capex_pct_revenue) or 0.0,
        nwc_pct=_v(inp.nwc_pct_revenue) or 0.0,
        net_debt=net_debt,
        shares=shares,
    )

    try:
        base = project(growths=growths, margins=margins, wacc=wacc, terminal_growth=tg, **core)
    except InvalidDCF as exc:
        out.valid = False
        out.warnings.append(str(exc))
        if "terminal growth" in str(exc):
            out.warnings.append("Terminal growth must be below WACC — adjust the assumptions.")
        return out

    out.projections = [DCFProjectionYear(**p) for p in base["projections"]]
    out.terminal_value = base["terminal_value"]
    out.pv_terminal_value = base["pv_terminal_value"]
    out.enterprise_value = base["enterprise_value"]
    out.equity_value = base["equity_value"]
    out.implied_value_per_share = base["implied_value_per_share"]
    if current_price and base["implied_value_per_share"] is not None:
        out.upside_pct = base["implied_value_per_share"] / current_price - 1.0

    out.scenarios = _scenarios(growths, margins, wacc, tg, core, current_price)
    out.sensitivity = _sensitivity(growths, margins, wacc, tg, core)
    if shares is None:
        out.warnings.append("Diluted shares unavailable — per-share value omitted.")
    return out


def _scenario(name, growths, margins, wacc, tg, core, current_price) -> DCFScenario:
    sc = DCFScenario(name=name)
    try:
        r = project(growths=growths, margins=margins, wacc=wacc, terminal_growth=tg, **core)
    except InvalidDCF:
        return sc
    sc.implied_value_per_share = r["implied_value_per_share"]
    sc.enterprise_value = r["enterprise_value"]
    sc.equity_value = r["equity_value"]
    if current_price and r["implied_value_per_share"] is not None:
        sc.upside_pct = r["implied_value_per_share"] / current_price - 1.0
    return sc


def _scenarios(growths, margins, wacc, tg, core, current_price) -> list[DCFScenario]:
    """Bear/base/bull by shifting growth, margin, WACC and terminal growth in a
    consistent (deterministic) direction."""
    bull_g = [g + 0.02 for g in growths]
    bear_g = [g - 0.02 for g in growths]
    bull_m = [m + 0.01 for m in margins]
    bear_m = [max(0.0, m - 0.01) for m in margins]
    bull_wacc = max(0.01, wacc - 0.01)
    bear_wacc = wacc + 0.01
    bull_tg = min(tg + 0.005, bull_wacc - 0.005)  # keep g < WACC
    bear_tg = tg - 0.005
    return [
        _scenario("bear", bear_g, bear_m, bear_wacc, bear_tg, core, current_price),
        _scenario("base", growths, margins, wacc, tg, core, current_price),
        _scenario("bull", bull_g, bull_m, bull_wacc, bull_tg, core, current_price),
    ]


def _axis(center: float, step: float, n: int = 2) -> list[float]:
    return [round(center + step * i, 6) for i in range(-n, n + 1)]


def _sensitivity(growths, margins, wacc, tg, core) -> list[DCFSensitivityTable]:
    # 1) WACC (rows) × terminal growth (cols)
    waccs = [w for w in _axis(wacc, 0.005) if w > 0]
    tgs = _axis(tg, 0.005)
    t1 = DCFSensitivityTable(
        title="Implied value/share — WACC × terminal growth",
        row_label="WACC",
        col_label="Terminal growth",
        rows=waccs,
        cols=tgs,
        values=[
            [
                _per_share_or_none(
                    growths=growths, margins=margins, wacc=w, terminal_growth=g, **core
                )
                for g in tgs
            ]
            for w in waccs
        ],
    )

    # 2) revenue CAGR (rows, flat each year) × terminal operating margin (cols)
    base_cagr = sum(growths) / len(growths)
    base_margin = margins[-1]
    cagrs = _axis(base_cagr, 0.02)
    tmargins = [m for m in _axis(base_margin, 0.02) if m > 0]
    t2 = DCFSensitivityTable(
        title="Implied value/share — revenue CAGR × terminal operating margin",
        row_label="Revenue CAGR",
        col_label="Terminal op. margin",
        rows=cagrs,
        cols=tmargins,
        values=[
            [
                _per_share_or_none(
                    growths=[c] * len(growths),
                    margins=[m] * len(margins),
                    wacc=wacc,
                    terminal_growth=tg,
                    **core,
                )
                for m in tmargins
            ]
            for c in cagrs
        ],
    )
    return [t1, t2]


# ── derive a DCFInput from reported financials (+ overrides) ─────────


def _asm(name, value, source_type, source=None, note=None) -> DCFAssumption:
    return DCFAssumption(name=name, value=value, source_type=source_type, source=source, note=note)


def _safe_div(a, b):
    if a is None or b in (None, 0):
        return None
    return a / b


def build_dcf_input(ticker: str, overrides: Optional[DCFOverrides] = None) -> DCFInput:
    """Derive a fully-labeled DCFInput from reported annual financials + profile,
    applying any user overrides. Fail-soft: missing data → defaults (labeled) or
    'unavailable', recorded in provenance/missing_data."""
    tk = ticker.strip().upper()
    ov = overrides or DCFOverrides()
    fetched = _iso_now()
    prov: list[DataProvenanceItem] = []
    missing: list[MissingDataItem] = []

    ann_res = fmp_provider.get_financial_statements(tk, period="annual", limit=5)
    rows = ann_res.data or []
    if rows:
        prov.append(
            DataProvenanceItem(
                dataset="income_annual",
                source=ann_res.source,
                as_of=ann_res.as_of,
                fetched_at=fetched,
                coverage=ann_res.coverage,
            )
        )
    else:
        missing.append(MissingDataItem(dataset="income_annual", reason="empty"))

    latest = rows[0] if rows else {}
    oldest = rows[-1] if rows else {}
    years = int(ov.projection_years or _DEFAULT_YEARS)

    prof = fmp_provider.get_profile(tk).data
    beta = getattr(prof, "beta", None)
    price = getattr(prof, "price", None)

    # base revenue
    rev0 = latest.get("revenue")
    if ov.base_revenue is not None:
        base_revenue = _asm("base_revenue", ov.base_revenue, "user_override", "user")
    elif rev0 is not None:
        base_revenue = _asm("base_revenue", rev0, "reported", "fmp", "latest fiscal-year revenue")
    else:
        base_revenue = _asm("base_revenue", None, "unavailable")
        missing.append(MissingDataItem(dataset="base_revenue", reason="empty"))

    # historical revenue CAGR → year-1 growth, fading to terminal growth
    n_rev = len(rows)
    hist_cagr = None
    if n_rev >= 2 and oldest.get("revenue") and latest.get("revenue") and oldest["revenue"] > 0:
        hist_cagr = (latest["revenue"] / oldest["revenue"]) ** (1.0 / (n_rev - 1)) - 1.0

    # terminal growth (default) — needed to build the growth fade
    if ov.terminal_growth is not None:
        terminal_growth = _asm("terminal_growth", ov.terminal_growth, "user_override", "user")
    else:
        terminal_growth = _asm(
            "terminal_growth", _DEF_TERMINAL_GROWTH, "default", "default", "long-run ~GDP"
        )
    tg_val = terminal_growth.value or _DEF_TERMINAL_GROWTH

    revenue_growth: list[DCFAssumption] = []
    if ov.revenue_growth:
        seq = ov.revenue_growth
        for i in range(years):
            val = seq[i] if i < len(seq) else seq[-1]
            revenue_growth.append(_asm(f"revenue_growth_y{i + 1}", val, "user_override", "user"))
    else:
        start = hist_cagr if hist_cagr is not None else tg_val
        start = max(min(start, 0.40), -0.20)  # clamp wild history
        for i in range(years):
            # linear fade from start (y1) toward terminal growth (yN)
            frac = i / max(1, years - 1)
            val = start + (tg_val - start) * frac
            st = "derived" if hist_cagr is not None else "default"
            revenue_growth.append(
                _asm(f"revenue_growth_y{i + 1}", round(val, 6), st, "derived:revenue_cagr")
            )
        if hist_cagr is None:
            missing.append(MissingDataItem(dataset="revenue_growth", reason="insufficient_history"))

    # operating margin (flat at latest, or override / fade to terminal margin)
    op_m = _safe_div(latest.get("operating_income"), latest.get("revenue"))
    operating_margin: list[DCFAssumption] = []
    if ov.operating_margin is not None:
        for i in range(years):
            operating_margin.append(
                _asm(f"operating_margin_y{i + 1}", ov.operating_margin, "user_override", "user")
            )
    elif op_m is not None:
        term_m = ov.terminal_operating_margin if ov.terminal_operating_margin is not None else op_m
        term_src = "user_override" if ov.terminal_operating_margin is not None else "reported"
        for i in range(years):
            frac = i / max(1, years - 1)
            val = op_m + (term_m - op_m) * frac
            operating_margin.append(
                _asm(f"operating_margin_y{i + 1}", round(val, 6), term_src, "fmp")
            )
    else:
        missing.append(MissingDataItem(dataset="operating_margin", reason="empty"))

    # tax rate
    eff_tax = _safe_div(latest.get("income_tax"), latest.get("pretax_income"))
    if ov.tax_rate is not None:
        tax_rate = _asm("tax_rate", ov.tax_rate, "user_override", "user")
    elif eff_tax is not None and 0.0 <= eff_tax <= 0.5:
        tax_rate = _asm("tax_rate", round(eff_tax, 4), "derived", "derived:effective", "tax/pretax")
    else:
        tax_rate = _asm("tax_rate", _DEF_TAX, "default", "default", "US statutory ~21%")

    da_pct = _pct_asm("da_pct_revenue", ov.da_pct_revenue, latest.get("d_and_a"), rev0, _DEF_DA_PCT)
    capex_pct = _pct_asm(
        "capex_pct_revenue",
        ov.capex_pct_revenue,
        abs(latest.get("capex")) if latest.get("capex") is not None else None,
        rev0,
        _DEF_CAPEX_PCT,
    )
    # ΔNWC as a fraction of incremental revenue
    nwc_pct = _nwc_asm(ov.nwc_pct_revenue, latest, oldest)

    # WACC (CAPM-derived from beta, else default)
    wacc = _wacc_asm(ov.wacc, beta, latest.get("debt"), latest.get("revenue"), tax_rate.value)

    # net debt + diluted shares
    nd = None
    if latest.get("debt") is not None or latest.get("cash") is not None:
        nd = (latest.get("debt") or 0.0) - (latest.get("cash") or 0.0)
    if ov.net_debt is not None:
        net_debt = _asm("net_debt", ov.net_debt, "user_override", "user")
    elif nd is not None:
        net_debt = _asm("net_debt", nd, "reported", "fmp", "total debt − cash")
    else:
        net_debt = _asm("net_debt", 0.0, "default", "default", "assumed zero")

    shares = latest.get("diluted_shares") or latest.get("shares_outstanding")
    if ov.diluted_shares is not None:
        diluted_shares = _asm("diluted_shares", ov.diluted_shares, "user_override", "user")
    elif shares:
        diluted_shares = _asm("diluted_shares", shares, "reported", "fmp")
    else:
        diluted_shares = _asm("diluted_shares", None, "unavailable")
        missing.append(MissingDataItem(dataset="diluted_shares", reason="empty"))

    return DCFInput(
        ticker=tk,
        projection_years=years,
        base_revenue=base_revenue,
        revenue_growth=revenue_growth,
        operating_margin=operating_margin,
        tax_rate=tax_rate,
        da_pct_revenue=da_pct,
        capex_pct_revenue=capex_pct,
        nwc_pct_revenue=nwc_pct,
        wacc=wacc,
        terminal_growth=terminal_growth,
        net_debt=net_debt,
        diluted_shares=diluted_shares,
        provenance=prov,
        missing_data=missing,
    )


def _pct_asm(name, override, numerator, revenue, default) -> DCFAssumption:
    if override is not None:
        return _asm(name, override, "user_override", "user")
    pct = _safe_div(numerator, revenue)
    if pct is not None and 0.0 <= pct <= 0.5:
        return _asm(name, round(pct, 4), "derived", "derived:pct_of_revenue")
    return _asm(name, default, "default", "default")


def _nwc_asm(override, latest, oldest) -> DCFAssumption:
    if override is not None:
        return _asm("nwc_pct_revenue", override, "user_override", "user")
    d_rev = None
    if latest.get("revenue") is not None and oldest.get("revenue") is not None:
        d_rev = latest["revenue"] - oldest["revenue"]
    pct = _safe_div(latest.get("change_in_nwc"), d_rev)
    if pct is not None and -0.5 <= pct <= 0.5:
        return _asm("nwc_pct_revenue", round(abs(pct), 4), "derived", "derived:delta_nwc")
    return _asm("nwc_pct_revenue", _DEF_NWC_PCT, "default", "default", "assumed ~2% of Δrevenue")


def _wacc_asm(override, beta, debt, revenue, tax) -> DCFAssumption:
    if override is not None:
        return _asm("wacc", override, "user_override", "user")
    if beta is not None and beta > 0:
        ke = _RISK_FREE + beta * _EQUITY_RISK_PREMIUM
        wacc = ke  # equity-only unless we have a debt weight; conservative
        return _asm(
            "wacc",
            round(wacc, 4),
            "derived",
            "derived:capm",
            f"CAPM: rf {_RISK_FREE:.1%} + β {beta:.2f}×ERP {_EQUITY_RISK_PREMIUM:.1%}",
        )
    return _asm("wacc", _DEF_WACC, "default", "default", "assumed 9%")


# ── orchestrator (fail-soft) ────────────────────────────────────────


def build_dcf(ticker: str, overrides: Optional[DCFOverrides] = None) -> DCFValuationOutput:
    """Build the DCF input from reported data + overrides, then run the
    valuation. Never raises on provider failure; returns valid=False with a
    reason when the inputs can't support a valuation."""
    tk = ticker.strip().upper()
    inp = build_dcf_input(tk, overrides)
    price = getattr(fmp_provider.get_profile(tk).data, "price", None)
    out = run_dcf(inp, current_price=price)
    out.as_of = inp.provenance[0].as_of if inp.provenance else None
    return out
