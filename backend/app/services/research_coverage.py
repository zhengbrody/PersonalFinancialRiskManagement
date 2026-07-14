"""Research data-coverage matrix (Phase 5) — assembly only, no new fetching.

Builds the per-ticker coverage matrix from the SAME cached builders the
research page already triggers (fact pack, financial statements, earnings,
DCF inputs), so a request after the page loads is cache-warm. Rules:

  * Every absent dataset carries a TYPED ``MissingReason`` — never a fake 0,
    "N/A" placeholder or invented text.
  * CORE fields (the retail-first questions: what the company does, the
    price, financial health, the statements, valuation) are graded
    ``critical`` and drive the shared conviction gates via
    ``build_data_confidence`` — thin critical coverage caps conviction
    exactly like every other surface.
  * Sources keep their honest tier: a fallback (yfinance) is labelled a
    fallback, a derived figure is ``derived`` — never provider-reported.
  * Every leg is fail-soft: a dead provider turns its rows into missing
    entries (``provider_error``), never a 500.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from ..schemas.confidence import FieldProvenance, MissingReason
from ..schemas.research_coverage import ResearchCoverageOut
from ._common import iso_now, safe
from .confidence import build_data_confidence, classify_missing_reason, field_provenance

_log = logging.getLogger(__name__)

# Retail-worded display groups.
G_PROFILE = "What the company does"
G_PRICE = "Price & history"
G_HEALTH = "Financial health"
G_STATEMENTS = "Financial statements"
G_VALUATION = "Valuation"
G_ANALYSTS = "Analysts & earnings"
G_OWNERSHIP = "Ownership & insiders"
G_NEWS = "News"
G_DCF = "DCF assumptions"


def build_coverage(ticker: str) -> ResearchCoverageOut:
    tk = (ticker or "").strip().upper()
    fields: list[FieldProvenance] = []
    missing: list[FieldProvenance] = []

    fp = safe("coverage.factpack", lambda: _factpack(tk))
    _factpack_rows(fp, fields, missing)

    fin = safe("coverage.financials", lambda: _financials(tk))
    _financials_rows(fin, fields, missing)

    earn = safe("coverage.earnings", lambda: _earnings(tk))
    _earnings_rows(earn, fields, missing)

    dcf = safe("coverage.dcf", lambda: _dcf_input(tk))
    _dcf_rows(dcf, fields, missing)

    crit_total = sum(1 for r in (*fields, *missing) if r.critical)
    crit_present = sum(1 for r in fields if r.critical)
    total = len(fields) + len(missing)
    dc = build_data_confidence(
        overall_coverage=(len(fields) / total) if total else 0.0,
        critical_coverage=(crit_present / crit_total) if crit_total else 0.0,
        sources=fields,
        missing=missing,
        as_of=getattr(fp, "as_of", None) if fp is not None else None,
        base_conviction="high",
    )
    return ResearchCoverageOut(
        ticker=tk,
        as_of=getattr(fp, "as_of", None) if fp is not None else None,
        generated_at=iso_now(),
        fields=fields,
        missing=missing,
        data_confidence=dc,
    )


# ── loaders (seams for tests; all cache-backed in production) ─────────


def _factpack(tk: str):
    from .research_factpack import build_fact_pack_cached

    return build_fact_pack_cached(tk)


def _financials(tk: str):
    from .research_financials import build_research_fact_pack

    return build_research_fact_pack(tk)


def _earnings(tk: str):
    from .research_earnings import build_earnings_comparison

    return build_earnings_comparison(tk)


def _dcf_input(tk: str):
    from .research_dcf import build_dcf_input

    return build_dcf_input(tk)


# ── row builders ──────────────────────────────────────────────────────


def _row(
    field: str,
    group: str,
    *,
    critical: bool,
    present: bool,
    source: str,
    as_of: Optional[str] = None,
    fetched_at: Optional[str] = None,
    stale: bool = False,
    coverage: Optional[float] = None,
    missing_reason: Optional[MissingReason] = None,
    note: Optional[str] = None,
) -> FieldProvenance:
    row = field_provenance(
        field,
        source,
        as_of=as_of,
        fetched_at=fetched_at,
        stale=stale,
        coverage=coverage if coverage is not None else (1.0 if present else 0.0),
        critical=critical,
        missing_reason=missing_reason,
        note=note,
    )
    row.group = group
    return row


def _add(
    fields: list,
    missing: list,
    field: str,
    group: str,
    value: Any,
    *,
    critical: bool,
    source: str,
    as_of: Optional[str] = None,
    stale: bool = False,
    reason: Optional[MissingReason] = None,
) -> None:
    present = value is not None and value != [] and value != ""
    if present:
        fields.append(
            _row(
                field,
                group,
                critical=critical,
                present=True,
                source=source,
                as_of=as_of,
                stale=stale,
            )
        )
    else:
        missing.append(
            _row(
                field,
                group,
                critical=critical,
                present=False,
                source=source,
                missing_reason=reason or "empty",
            )
        )


def _factpack_rows(fp, fields: list, missing: list) -> None:
    if fp is None:
        for f, g, crit in (
            ("company_profile", G_PROFILE, True),
            ("price", G_PRICE, True),
            ("technicals", G_PRICE, False),
            ("profit_margins", G_HEALTH, True),
            ("return_on_equity", G_HEALTH, True),
            ("revenue_growth", G_HEALTH, False),
            ("valuation_pe", G_VALUATION, True),
            ("forward_pe", G_VALUATION, False),
            ("analyst_estimates", G_ANALYSTS, False),
            ("institutional_ownership", G_OWNERSHIP, False),
            ("insider_activity", G_OWNERSHIP, False),
            ("news", G_NEWS, False),
        ):
            missing.append(
                _row(
                    f,
                    g,
                    critical=crit,
                    present=False,
                    source="unavailable",
                    missing_reason="provider_error",
                )
            )
        return

    stale = bool(getattr(getattr(fp, "cache", None), "stale", False))
    warn_blob = " ".join(getattr(fp.data_quality, "warnings", None) or [])
    reason = classify_missing_reason(warn_blob) if warn_blob else "empty"
    refs = {r.field: r for r in (getattr(fp.data_quality, "sources", None) or [])}

    def src(*keys: str, default: str = "yfinance") -> tuple[str, Optional[str]]:
        for k in keys:
            if k in refs:
                return refs[k].source, refs[k].as_of
        return default, getattr(fp, "as_of", None)

    s, a = src("profile")
    _add(
        fields,
        missing,
        "company_profile",
        G_PROFILE,
        getattr(fp, "name", None),
        critical=True,
        source=s,
        as_of=a,
        stale=stale,
        reason=reason,
    )
    s, a = src("price")
    _add(
        fields,
        missing,
        "price",
        G_PRICE,
        fp.price,
        critical=True,
        source=s,
        as_of=a,
        stale=stale,
        reason=reason,
    )
    s, a = src("momentum", "technicals")
    _add(
        fields,
        missing,
        "technicals",
        G_PRICE,
        fp.momentum.rsi_14,
        critical=False,
        source=s,
        as_of=a,
        stale=stale,
        reason=reason,
    )
    s, a = src("ratios", "fundamentals")
    _add(
        fields,
        missing,
        "profit_margins",
        G_HEALTH,
        fp.quality.net_margin,
        critical=True,
        source=s,
        as_of=a,
        stale=stale,
        reason=reason,
    )
    _add(
        fields,
        missing,
        "return_on_equity",
        G_HEALTH,
        fp.quality.roe,
        critical=True,
        source=s,
        as_of=a,
        stale=stale,
        reason=reason,
    )
    _add(
        fields,
        missing,
        "revenue_growth",
        G_HEALTH,
        fp.growth.revenue_cagr,
        critical=False,
        source="derived",
        as_of=a,
        reason=reason,
    )
    s, a = src("ratios", "valuation")
    _add(
        fields,
        missing,
        "valuation_pe",
        G_VALUATION,
        fp.valuation.pe,
        critical=True,
        source=s,
        as_of=a,
        stale=stale,
        reason=reason,
    )
    _add(
        fields,
        missing,
        "forward_pe",
        G_VALUATION,
        fp.valuation.forward_pe,
        critical=False,
        source=s,
        as_of=a,
        stale=stale,
        reason=reason,
    )
    s, a = src("analyst")
    _add(
        fields,
        missing,
        "analyst_estimates",
        G_ANALYSTS,
        fp.analyst.target_consensus or fp.analyst.implied_upside_pct,
        critical=False,
        source=s,
        as_of=a,
        stale=stale,
        reason=reason,
    )
    s, a = src("ownership")
    _add(
        fields,
        missing,
        "institutional_ownership",
        G_OWNERSHIP,
        fp.ownership.institutional_pct,
        critical=False,
        source=s,
        as_of=a,
        stale=stale,
        reason=reason,
    )
    s, a = src("insider")
    _add(
        fields,
        missing,
        "insider_activity",
        G_OWNERSHIP,
        fp.insider.signal,
        critical=False,
        source=s,
        as_of=a,
        stale=stale,
        reason=reason,
    )
    s, a = src("news")
    _add(
        fields,
        missing,
        "news",
        G_NEWS,
        fp.news or None,
        critical=False,
        source=s,
        as_of=a,
        stale=stale,
        reason=reason,
    )


# Which FinancialQuarter FIELDS constitute each statement — the provider merges
# income + balance-sheet + cash-flow into ONE dataset per period (provenance
# dataset "income_quarterly"), so per-statement presence is derived from the
# quarter rows themselves, never from dataset names that don't exist.
_STATEMENT_FIELDS = (
    ("income_statement_quarterly", True, ("revenue", "net_income", "eps")),
    ("balance_sheet_quarterly", True, ("cash", "debt")),
    ("cashflow_statement_quarterly", True, ("free_cash_flow", "capex")),
)


def _financials_rows(fin, fields: list, missing: list) -> None:
    if fin is None:
        for name, crit, _cols in _STATEMENT_FIELDS:
            missing.append(
                _row(
                    name,
                    G_STATEMENTS,
                    critical=crit,
                    present=False,
                    source="unavailable",
                    missing_reason="provider_error",
                )
            )
        return
    prov = {p.dataset: p for p in (getattr(fin, "provenance", None) or [])}
    reasons = {
        m.dataset: classify_missing_reason(getattr(m, "reason", None))
        for m in (getattr(fin, "missing_data", None) or [])
    }
    quarters = getattr(fin, "quarters", None) or []
    stmt_prov = prov.get("income_quarterly")  # the merged-statements fetch
    base_reason = reasons.get("income_quarterly", "empty")
    for name, crit, cols in _STATEMENT_FIELDS:
        rows_with_data = [q for q in quarters if any(getattr(q, c, None) is not None for c in cols)]
        if rows_with_data:
            fields.append(
                _row(
                    name,
                    G_STATEMENTS,
                    critical=crit,
                    present=True,
                    source=(getattr(stmt_prov, "source", None) or "fmp"),
                    as_of=getattr(stmt_prov, "as_of", None)
                    or getattr(rows_with_data[0], "fiscal_date", None),
                    fetched_at=getattr(stmt_prov, "fetched_at", None),
                    coverage=round(len(rows_with_data) / max(len(quarters), 1), 3),
                )
            )
        else:
            missing.append(
                _row(
                    name,
                    G_STATEMENTS,
                    critical=crit,
                    present=False,
                    source=(getattr(stmt_prov, "source", None) or "unavailable"),
                    missing_reason=base_reason,
                )
            )


def _earnings_rows(earn, fields: list, missing: list) -> None:
    if earn is None:
        for f in ("earnings_history", "earnings_estimates", "transcripts"):
            missing.append(
                _row(
                    f,
                    G_ANALYSTS,
                    critical=False,
                    present=False,
                    source="unavailable",
                    missing_reason="provider_error",
                )
            )
        return
    periods = getattr(earn, "periods", None) or []
    reasons = {
        m.dataset: classify_missing_reason(getattr(m, "reason", None))
        for m in (getattr(earn, "missing_data", None) or [])
    }
    src = "fmp"
    prov = getattr(earn, "provenance", None) or []
    if prov:
        src = prov[0].source or "fmp"
    _add(
        fields,
        missing,
        "earnings_history",
        G_ANALYSTS,
        periods or None,
        critical=False,
        source=src,
        as_of=getattr(earn, "as_of", None),
        reason=reasons.get("earnings_history", "empty"),
    )
    has_estimates = any(
        getattr(p, "eps_estimate", None) is not None
        or getattr(p, "revenue_estimate", None) is not None
        for p in periods
    )
    _add(
        fields,
        missing,
        "earnings_estimates",
        G_ANALYSTS,
        has_estimates or None,
        critical=False,
        source=src,
        as_of=getattr(earn, "as_of", None),
        reason=reasons.get("earnings_estimates", reasons.get("no_estimates", "unsupported")),
    )
    transcript = getattr(getattr(earn, "transcript", None), "available", None)
    _add(
        fields,
        missing,
        "transcripts",
        G_ANALYSTS,
        transcript or None,
        critical=False,
        source=src,
        reason=reasons.get("transcript", "unsupported"),
    )


def _dcf_rows(dcf, fields: list, missing: list) -> None:
    if dcf is None:
        missing.append(
            _row(
                "dcf_assumptions",
                G_DCF,
                critical=False,
                present=False,
                source="unavailable",
                missing_reason="provider_error",
            )
        )
        return
    scalars = ("base_revenue", "tax_rate", "wacc", "terminal_growth", "net_debt", "diluted_shares")
    kinds = [
        getattr(getattr(dcf, name, None), "source_type", "unavailable")
        for name in scalars
        if getattr(dcf, name, None) is not None
    ]
    for series in ("revenue_growth", "operating_margin"):
        rows = getattr(dcf, series, None) or []
        if rows:
            kinds.append(getattr(rows[0], "source_type", "unavailable"))
    known = [k for k in kinds if k not in ("unavailable",)]
    coverage = (len(known) / len(kinds)) if kinds else 0.0
    if coverage > 0:
        fields.append(
            _row(
                "dcf_assumptions",
                G_DCF,
                critical=False,
                present=True,
                source="derived",
                coverage=round(coverage, 3),
                note="each assumption carries reported/derived/default labelling in the DCF panel",
            )
        )
    else:
        missing.append(
            _row(
                "dcf_assumptions",
                G_DCF,
                critical=False,
                present=False,
                source="unavailable",
                missing_reason="insufficient_history",
            )
        )
