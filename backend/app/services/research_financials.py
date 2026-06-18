"""Institutional Research FactPack (Phase 1) — deterministic financial trend
engine + fail-soft builder.

Product principles enforced here:
  * Every number/growth/margin/flag is computed in this module (pure Python).
    The LLM is never involved (this module has no LLM import).
  * Missing data is explicit: each dataset either lands in `provenance` (with
    source + freshness + coverage) or in `missing_data` (with a reason).
  * Educational/research only — the FactPack carries a disclaimer.

The growth/TTM/margin/flag helpers below are PURE functions over
`FinancialQuarter`/`FinancialAnnual` lists (newest first), so they are unit-
tested with hand-built fixtures and never touch the network.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from ..schemas.research import (
    CompanySnapshot,
    DataProvenanceItem,
    FinancialAnnual,
    FinancialQuarter,
    FinancialTrendSummary,
    MissingDataItem,
    ResearchFactPack,
)
from .providers import fmp_provider

_log = logging.getLogger(__name__)

# Growth/margin moves smaller than this (in fraction / ratio points) are treated
# as "flat" so trend flags don't fire on noise.
_EPS_FLAT = 0.005
# A statement dated within this many days of "now" counts as fresh.
_FRESH_DAYS = 200

_TTM_FIELDS = ("revenue", "ebitda", "free_cash_flow", "eps", "net_income")


# ── pure math helpers ───────────────────────────────────────────────


def _margin(numerator: Optional[float], revenue: Optional[float]) -> Optional[float]:
    """Ratio, or None when revenue is missing / non-positive (a margin off a
    zero/negative revenue base is meaningless)."""
    if numerator is None or revenue is None or revenue <= 0:
        return None
    return numerator / revenue


def _growth(current: Optional[float], base: Optional[float]) -> Optional[float]:
    """Fractional growth (0.12 = +12%). None when either side is missing or the
    base is non-positive — growth off a zero/negative base flips sign and
    misleads, so we decline to report it rather than emit a wrong number."""
    if current is None or base is None or base <= 0:
        return None
    return current / base - 1.0


def _ttm(quarters: list[FinancialQuarter], field: str) -> Optional[float]:
    """Sum of the field across the latest 4 quarters. None unless there are ≥4
    quarters AND all four have the field (no partial TTM)."""
    if len(quarters) < 4:
        return None
    vals = [getattr(q, field) for q in quarters[:4]]
    if any(v is None for v in vals):
        return None
    return sum(vals)


def _delta(current: Optional[float], base: Optional[float]) -> Optional[float]:
    if current is None or base is None:
        return None
    return current - base


# ── period mapping (normalized provider dict → schema + margins) ────


def _apply_margins(fig) -> None:
    rev = fig.revenue
    fig.gross_margin = _margin(fig.gross_profit, rev)
    fig.operating_margin = _margin(fig.operating_income, rev)
    fig.net_margin = _margin(fig.net_income, rev)
    fig.fcf_margin = _margin(fig.free_cash_flow, rev)


_FIG_FIELDS = (
    "revenue",
    "gross_profit",
    "operating_income",
    "net_income",
    "eps",
    "eps_diluted",
    "free_cash_flow",
    "capex",
    "cash",
    "debt",
    "shares_outstanding",
    "diluted_shares",
    "ebitda",
)


def quarter_from_row(row: dict) -> FinancialQuarter:
    q = FinancialQuarter(
        period=str(row.get("period") or row.get("fiscal_date") or ""),
        fiscal_date=row.get("fiscal_date"),
        **{f: row.get(f) for f in _FIG_FIELDS},
    )
    _apply_margins(q)
    return q


def annual_from_row(row: dict) -> FinancialAnnual:
    a = FinancialAnnual(
        fiscal_year=str(row.get("fiscal_year") or row.get("period") or ""),
        fiscal_date=row.get("fiscal_date"),
        **{f: row.get(f) for f in _FIG_FIELDS},
    )
    _apply_margins(a)
    return a


# ── trend summary (PURE) ────────────────────────────────────────────


def build_trend_summary(
    quarters: list[FinancialQuarter], annuals: list[FinancialAnnual]
) -> FinancialTrendSummary:
    """Deterministic trend read. `quarters`/`annuals` are NEWEST FIRST."""
    t = FinancialTrendSummary(quarters_used=len(quarters), annuals_used=len(annuals))

    # TTM (latest 4 quarters)
    t.ttm_revenue = _ttm(quarters, "revenue")
    t.ttm_ebitda = _ttm(quarters, "ebitda")
    t.ttm_fcf = _ttm(quarters, "free_cash_flow")
    t.ttm_eps = _ttm(quarters, "eps")
    t.ttm_net_income = _ttm(quarters, "net_income")

    q0 = quarters[0] if quarters else None
    q1 = quarters[1] if len(quarters) > 1 else None
    q4 = quarters[4] if len(quarters) > 4 else None
    q5 = quarters[5] if len(quarters) > 5 else None

    if q0 and q4:
        t.revenue_yoy = _growth(q0.revenue, q4.revenue)
        t.eps_yoy = _growth(q0.eps, q4.eps)
        t.net_income_yoy = _growth(q0.net_income, q4.net_income)
        t.gross_margin_delta_yoy = _delta(q0.gross_margin, q4.gross_margin)
        t.operating_margin_delta_yoy = _delta(q0.operating_margin, q4.operating_margin)
        t.net_margin_delta_yoy = _delta(q0.net_margin, q4.net_margin)
    if q0 and q1:
        t.revenue_qoq = _growth(q0.revenue, q1.revenue)
    if q1 and q5:
        t.prior_revenue_yoy = _growth(q1.revenue, q5.revenue)

    # Acceleration: latest YoY vs the YoY one quarter earlier.
    if t.revenue_yoy is not None and t.prior_revenue_yoy is not None:
        if t.revenue_yoy > t.prior_revenue_yoy + _EPS_FLAT:
            t.revenue_trend = "accelerating"
        elif t.revenue_yoy < t.prior_revenue_yoy - _EPS_FLAT:
            t.revenue_trend = "decelerating"
        else:
            t.revenue_trend = "stable"

    t.flags = _trend_flags(t)
    return t


def _pct(x: Optional[float]) -> str:
    return f"{x * 100:.1f}%" if x is not None else "n/a"


def _trend_flags(t: FinancialTrendSummary) -> list[str]:
    """Plain-language, factual flags derived ONLY from the computed numbers."""
    flags: list[str] = []
    if t.revenue_trend == "accelerating":
        flags.append(
            f"Revenue growth accelerating ({_pct(t.revenue_yoy)} YoY vs {_pct(t.prior_revenue_yoy)})"
        )
    elif t.revenue_trend == "decelerating":
        flags.append(
            f"Revenue growth decelerating ({_pct(t.revenue_yoy)} YoY vs {_pct(t.prior_revenue_yoy)})"
        )
    if t.revenue_yoy is not None and t.revenue_yoy < 0:
        flags.append(f"Revenue declining YoY ({_pct(t.revenue_yoy)})")
    if t.eps_yoy is not None and t.eps_yoy < 0:
        flags.append(f"EPS declining YoY ({_pct(t.eps_yoy)})")
    if t.net_margin_delta_yoy is not None:
        if t.net_margin_delta_yoy > _EPS_FLAT:
            flags.append(f"Net margin expanding YoY (+{t.net_margin_delta_yoy * 100:.1f} pts)")
        elif t.net_margin_delta_yoy < -_EPS_FLAT:
            flags.append(f"Net margin contracting YoY ({t.net_margin_delta_yoy * 100:.1f} pts)")
    return flags


# ── data confidence (PURE) ──────────────────────────────────────────


def compute_data_confidence(
    *,
    quarters: list[FinancialQuarter],
    annuals: list[FinancialAnnual],
    snapshot_ok: bool,
    fresh: bool,
    missing_count: int,
) -> tuple[float, str]:
    """0..1 deterministic confidence + a label. Weighted by how much of the
    target history (8Q / 5Y) is present, whether profile/price exists, whether
    the latest quarter has the critical fields, freshness, minus a missing-data
    penalty."""
    score = 0.0
    score += 0.30 * min(len(quarters), 8) / 8  # quarterly depth
    score += 0.20 * min(len(annuals), 5) / 5  # annual depth
    if snapshot_ok:
        score += 0.15  # profile/price present
    if quarters:  # critical fields in the latest quarter
        q = quarters[0]
        crit = [q.revenue, q.net_income, q.eps]
        score += 0.20 * sum(1 for x in crit if x is not None) / len(crit)
    if fresh:
        score += 0.15
    score -= 0.05 * max(0, missing_count)
    score = max(0.0, min(1.0, round(score, 3)))
    label = "high" if score >= 0.75 else "medium" if score >= 0.45 else "low"
    return score, label


# ── builder (fail-soft; orchestrates providers + the pure engine) ───


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_fresh(fiscal_date: Optional[str]) -> bool:
    if not fiscal_date:
        return False
    try:
        d = datetime.fromisoformat(str(fiscal_date)[:10]).replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return False
    return (datetime.now(timezone.utc) - d).days <= _FRESH_DAYS


def _snapshot(ticker: str, profile, quarters: list[FinancialQuarter]) -> CompanySnapshot:
    shares = quarters[0].shares_outstanding if quarters else None
    if profile is None:
        return CompanySnapshot(ticker=ticker, shares_outstanding=shares)
    return CompanySnapshot(
        ticker=ticker,
        name=profile.name,
        sector=profile.sector,
        industry=profile.industry,
        exchange=profile.exchange,
        currency=profile.currency or "USD",
        price=profile.price,
        market_cap=profile.market_cap,
        beta=profile.beta,
        shares_outstanding=shares,
    )


def build_research_fact_pack(ticker: str) -> ResearchFactPack:
    """Build the institutional FactPack. Never raises on provider failure — a
    failed dataset becomes a `missing_data` entry and the pack returns partial."""
    tk = ticker.strip().upper()
    fetched = _iso_now()
    provenance: list[DataProvenanceItem] = []
    missing: list[MissingDataItem] = []

    # 1) Company profile (snapshot)
    prof_res = fmp_provider.get_profile(tk)
    profile = prof_res.data
    if profile is not None:
        provenance.append(
            DataProvenanceItem(
                dataset="profile",
                source=prof_res.source,
                as_of=prof_res.as_of,
                fetched_at=fetched,
                coverage=prof_res.coverage,
            )
        )
    else:
        missing.append(MissingDataItem(dataset="profile", reason=_reason(prof_res)))

    # 2) Quarterly statements (last 8) and 3) annual statements (last 5)
    quarters = _statements(
        tk, "quarter", 8, "income_quarterly", provenance, missing, fetched, quarter_from_row
    )
    annuals = _statements(
        tk, "annual", 5, "income_annual", provenance, missing, fetched, annual_from_row
    )

    snapshot = _snapshot(tk, profile, quarters)
    trend = build_trend_summary(quarters, annuals)

    as_of = (quarters[0].fiscal_date if quarters else None) or (
        annuals[0].fiscal_date if annuals else None
    )
    fresh = _is_fresh(as_of)
    score, label = compute_data_confidence(
        quarters=quarters,
        annuals=annuals,
        snapshot_ok=profile is not None or bool(quarters),
        fresh=fresh,
        missing_count=len(missing),
    )

    return ResearchFactPack(
        ticker=tk,
        as_of=as_of,
        generated_at=fetched,
        snapshot=snapshot,
        quarters=quarters,
        annuals=annuals,
        trend=trend,
        provenance=provenance,
        missing_data=missing,
        data_confidence=score,
        confidence_label=label,
    )


def _reason(res) -> str:
    w = (res.warnings or [""])[0]
    if "key_missing" in w or "no_key" in w:
        return "no_key"
    if "error" in w:
        return "provider_error"
    return "empty"


def _statements(
    tk: str,
    period: str,
    limit: int,
    dataset: str,
    provenance: list[DataProvenanceItem],
    missing: list[MissingDataItem],
    fetched: str,
    mapper,
) -> list:
    res = fmp_provider.get_financial_statements(tk, period=period, limit=limit)
    rows = res.data or []
    if not rows:
        missing.append(MissingDataItem(dataset=dataset, reason=_reason(res)))
        return []
    target = limit
    if len(rows) < target:
        missing.append(MissingDataItem(dataset=dataset, reason="insufficient_history"))
    provenance.append(
        DataProvenanceItem(
            dataset=dataset,
            source=res.source,
            as_of=res.as_of,
            fetched_at=fetched,
            coverage=res.coverage,
            note=f"{len(rows)}/{target} periods" if len(rows) < target else None,
        )
    )
    return [mapper(r) for r in rows[:limit]]
