"""Deterministic earnings comparison (Phase 3).

Actual revenue/EPS (from Phase-1 quarterly statements) vs prior quarter / prior
year, and vs analyst estimate ONLY when estimate data exists (beat/miss is never
shown without an estimate). Transcript availability is explicit. No LLM here —
the LLM narrative lives in the thesis, which reads the transcript excerpt.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from ..schemas.earnings import (
    EarningsComparisonOutput,
    EarningsPeriod,
    EarningsThemeSummary,
    EarningsTranscriptMetadata,
)
from ..schemas.research import DataProvenanceItem, MissingDataItem
from . import research_financials as rfin
from ._common import iso_now
from .providers import fmp_provider

_log = logging.getLogger(__name__)
_MATCH_DAYS = 130  # an earnings report dates ~1 month after quarter-end
_growth = rfin._growth  # same fractional-growth-with-non-positive-base guard


def _date(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s)[:10])
    except (ValueError, TypeError):
        return None


def _reason(res) -> str:
    w = (res.warnings or [""])[0]
    if "key_missing" in w or "no_key" in w:
        return "no_key"
    if "Starter" in w or "402" in w:
        return "requires_paid_plan"
    if "error" in w:
        return "provider_error"
    return "empty"


def _match_earnings(fiscal_date: Optional[str], earn_rows: list[dict]) -> Optional[dict]:
    fd = _date(fiscal_date)
    if fd is None:
        return None
    best, best_gap = None, None
    for r in earn_rows:
        ed = _date(r.get("date"))
        if ed is None:
            continue
        gap = abs((ed - fd).days)
        if gap <= _MATCH_DAYS and (best_gap is None or gap < best_gap):
            best, best_gap = r, gap
    return best


def _summary(periods: list[EarningsPeriod]) -> EarningsThemeSummary:
    if not periods:
        return EarningsThemeSummary()
    p = periods[0]
    pts: list[str] = []
    if p.revenue_yoy is not None:
        pts.append(f"Revenue {p.revenue_yoy * 100:+.1f}% YoY")
    if p.revenue_qoq is not None:
        pts.append(f"Revenue {p.revenue_qoq * 100:+.1f}% QoQ")
    if p.eps_yoy is not None:
        pts.append(f"EPS {p.eps_yoy * 100:+.1f}% YoY")
    if p.revenue_beat is not None and p.revenue_surprise_pct is not None:
        pts.append(
            f"Revenue {'beat' if p.revenue_beat else 'missed'} estimate by "
            f"{abs(p.revenue_surprise_pct) * 100:.1f}%"
        )
    if p.eps_beat is not None and p.eps_surprise_pct is not None:
        pts.append(
            f"EPS {'beat' if p.eps_beat else 'missed'} estimate by "
            f"{abs(p.eps_surprise_pct) * 100:.1f}%"
        )
    headline = f"{p.period}: " + "; ".join(pts[:2]) if pts else None
    return EarningsThemeSummary(headline=headline, points=pts, ai_generated=False)


def build_earnings_comparison(ticker: str) -> EarningsComparisonOutput:
    """Deterministic earnings comparison. Never raises on provider failure."""
    tk = ticker.strip().upper()
    fetched = iso_now()
    prov: list[DataProvenanceItem] = []
    missing: list[MissingDataItem] = []

    stmt_res = fmp_provider.get_financial_statements(tk, period="quarter", limit=8)
    rows = stmt_res.data or []
    quarters = [rfin.quarter_from_row(r) for r in rows]  # newest first
    if quarters:
        prov.append(
            DataProvenanceItem(
                dataset="income_quarterly",
                source=stmt_res.source,
                as_of=stmt_res.as_of,
                fetched_at=fetched,
                coverage=stmt_res.coverage,
            )
        )
    else:
        missing.append(MissingDataItem(dataset="income_quarterly", reason=_reason(stmt_res)))

    earn_res = fmp_provider.get_earnings(tk, limit=8)
    earn_rows = earn_res.data or []
    if earn_rows:
        prov.append(
            DataProvenanceItem(
                dataset="earnings_estimates",
                source=earn_res.source,
                as_of=earn_res.as_of,
                fetched_at=fetched,
                coverage=earn_res.coverage,
            )
        )
        if "no_estimates" in earn_res.warnings:
            missing.append(MissingDataItem(dataset="earnings_estimates", reason="actuals_only"))
    else:
        missing.append(MissingDataItem(dataset="earnings_estimates", reason=_reason(earn_res)))

    periods: list[EarningsPeriod] = []
    for i, q in enumerate(quarters):
        p = EarningsPeriod(period=q.period, fiscal_date=q.fiscal_date, revenue=q.revenue, eps=q.eps)
        if i + 4 < len(quarters):
            p.revenue_yoy = _growth(q.revenue, quarters[i + 4].revenue)
            p.eps_yoy = _growth(q.eps, quarters[i + 4].eps)
        if i + 1 < len(quarters):
            p.revenue_qoq = _growth(q.revenue, quarters[i + 1].revenue)
            p.eps_qoq = _growth(q.eps, quarters[i + 1].eps)
        m = _match_earnings(q.fiscal_date, earn_rows)
        if m:
            ra, re = m.get("revenue_actual"), m.get("revenue_estimate")
            ea, ee = m.get("eps_actual"), m.get("eps_estimate")
            if re is not None:
                p.revenue_estimate = re
                if ra is not None and re != 0:
                    p.revenue_surprise_pct = ra / re - 1.0
                    p.revenue_beat = ra >= re
            if ee is not None:
                p.eps_estimate = ee
                if ea is not None and ee != 0:
                    p.eps_surprise_pct = (ea - ee) / abs(ee)
                    p.eps_beat = ea >= ee
        periods.append(p)

    tr_res = fmp_provider.get_transcript_meta(tk)
    tr = tr_res.data
    if tr:
        transcript = EarningsTranscriptMetadata(
            available=True,
            quarter=tr.get("quarter"),
            fiscal_year=tr.get("year"),
            date=tr.get("date"),
            source=tr_res.source,
            excerpt_length=int(tr.get("excerpt_length") or 0),
        )
        prov.append(
            DataProvenanceItem(
                dataset="transcript", source=tr_res.source, as_of=tr_res.as_of, fetched_at=fetched
            )
        )
    else:
        transcript = EarningsTranscriptMetadata(available=False)
        missing.append(MissingDataItem(dataset="transcript", reason=_reason(tr_res)))

    return EarningsComparisonOutput(
        ticker=tk,
        as_of=(quarters[0].fiscal_date if quarters else None),
        generated_at=fetched,
        periods=periods,
        transcript=transcript,
        summary=_summary(periods),
        provenance=prov,
        missing_data=missing,
    )
