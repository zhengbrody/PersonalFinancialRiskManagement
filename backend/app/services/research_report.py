"""Institutional analyst HTML report (Phase 3).

Assembles the deterministic engines SERVER-SIDE (financials FactPack + compact
FactPack + DCF + peers + earnings + a deterministic thesis) into ONE
self-contained, PDF-ready HTML document. No recomputation in the frontend, no LLM
number — the executive summary uses the DETERMINISTIC thesis fallback so the
report is free + always renders. Reuses the report_html helpers (inline CSS,
@media print, html.escape). Fail-soft per section; a missing engine becomes an
explicit note + a provenance/missing-data appendix entry.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from ..schemas.report import (
    AnalystReportOutput,
    AnalystReportProvenanceAppendix,
    AnalystReportSection,
)
from ..schemas.research import DataProvenanceItem, MissingDataItem
from . import report_html as rh
from . import (
    research_dcf,
    research_earnings,
    research_factpack,
    research_financials,
    research_peers,
    research_thesis,
)

_log = logging.getLogger(__name__)


def _safe(fn):
    try:
        return fn()
    except Exception:  # noqa: BLE001 - each section is best-effort
        return None


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_analyst_report(ticker: str) -> AnalystReportOutput:
    tk = ticker.strip().upper()
    gen = _iso_now()

    fin = _safe(lambda: research_financials.build_research_fact_pack(tk))
    fp = _safe(lambda: research_factpack.build_fact_pack(tk))
    dcf = _safe(lambda: research_dcf.build_dcf(tk))
    peers = _safe(lambda: research_peers.build_peer_comparison(tk))
    earn = _safe(lambda: research_earnings.build_earnings_comparison(tk))
    thesis = _safe(lambda: research_thesis.build_thesis(tk, llm_callable=None))

    name = (getattr(fin, "snapshot", None) and fin.snapshot.name) or tk
    as_of = (getattr(fin, "as_of", None)) or (getattr(earn, "as_of", None)) or ""

    sections: list[AnalystReportSection] = []
    prov: list[DataProvenanceItem] = []
    missing: list[MissingDataItem] = []
    body: list[str] = []

    def add(key: str, title: str, inner: str | None, *, note: str | None = None):
        if inner:
            body.append(rh._section(title, inner))
            sections.append(AnalystReportSection(key=key, title=title, included=True))
        else:
            body.append(
                rh._section(title, f"<p class='muted'>{rh.esc(note or 'Data unavailable.')}</p>")
            )
            sections.append(AnalystReportSection(key=key, title=title, included=False, note=note))

    # ── Company snapshot
    if fin is not None:
        s = fin.snapshot
        add(
            "snapshot",
            "Company snapshot",
            rh._kpis(
                [
                    ("Sector", rh.esc(s.sector or "—")),
                    ("Industry", rh.esc(s.industry or "—")),
                    ("Price", rh._money(s.price)),
                    ("Market cap", rh._money(s.market_cap)),
                    (
                        "Data confidence",
                        f"{fin.confidence_label} ({round(fin.data_confidence * 100)}%)",
                    ),
                ]
            ),
        )
        prov.extend(fin.provenance)
        missing.extend(fin.missing_data)
    else:
        add("snapshot", "Company snapshot", None, note="Financial data unavailable.")
        missing.append(MissingDataItem(dataset="financials", reason="empty"))

    # ── Executive summary (deterministic thesis)
    if thesis is not None:
        inner = ""
        if thesis.key_debate:
            inner += f"<p>{rh.esc(thesis.key_debate)}</p>"
        inner += "<h4>Bull case</h4>" + rh._bullets(thesis.bull_case)
        inner += "<h4>Bear case</h4>" + rh._bullets(thesis.bear_case)
        add("exec_summary", "Executive summary", inner)
    else:
        add("exec_summary", "Executive summary", None)

    # ── Financial trend
    if fin is not None and fin.quarters:
        rows = [
            [
                rh.esc(q.period),
                rh._money(q.revenue),
                rh._pct(q.gross_margin),
                rh._pct(q.operating_margin),
                rh._pct(q.net_margin),
                rh._num(q.eps),
            ]
            for q in fin.quarters
        ]
        t = fin.trend
        inner = rh._kpis(
            [
                ("TTM revenue", rh._money(t.ttm_revenue)),
                ("Revenue YoY", rh._signed_pct(t.revenue_yoy)),
                ("Revenue QoQ", rh._signed_pct(t.revenue_qoq)),
                ("EPS YoY", rh._signed_pct(t.eps_yoy)),
            ]
        ) + rh._table(["Period", "Revenue", "Gross %", "Op %", "Net %", "EPS"], rows)
        add("financials", "Financial trend (quarterly)", inner)
    else:
        add("financials", "Financial trend (quarterly)", None)

    # ── DCF model summary + scenario range
    if dcf is not None and dcf.valid:
        i = dcf.inputs
        scen = {s.name: s.implied_value_per_share for s in dcf.scenarios}
        inner = rh._kpis(
            [
                ("Current price", rh._money(dcf.current_price)),
                ("Bear", rh._money(scen.get("bear"))),
                ("Base", rh._money(scen.get("base"))),
                ("Bull", rh._money(scen.get("bull"))),
                ("Base upside", rh._signed_pct(dcf.upside_pct)),
            ]
        )
        inner += rh._table(
            ["Assumption", "Value", "Source"],
            [
                ["WACC", rh._pct(i.wacc.value), rh.esc(i.wacc.source_type)],
                [
                    "Terminal growth",
                    rh._pct(i.terminal_growth.value),
                    rh.esc(i.terminal_growth.source_type),
                ],
                ["Tax rate", rh._pct(i.tax_rate.value), rh.esc(i.tax_rate.source_type)],
                ["Net debt", rh._money(i.net_debt.value), rh.esc(i.net_debt.source_type)],
                [
                    "Diluted shares",
                    rh._num(i.diluted_shares.value, 0),
                    rh.esc(i.diluted_shares.source_type),
                ],
            ],
        )
        add("dcf", "DCF model & scenario valuation", inner)
        prov.extend(i.provenance)
        missing.extend(i.missing_data)
    else:
        add("dcf", "DCF model & scenario valuation", None, note="Not enough data for a DCF.")

    # ── Peer comparison
    if peers is not None and len(peers.rows) > 1:
        rows = [
            [
                rh.esc(r.ticker) + (" *" if r.is_subject else ""),
                rh._money(r.market_cap),
                rh._signed_pct(r.revenue_growth),
                rh._pct(r.net_margin),
                rh._num(r.pe),
                rh._num(r.ev_ebitda),
            ]
            for r in peers.rows
        ]
        add(
            "peers",
            f"Peer comparison ({rh.esc(peers.peer_source)})",
            rh._table(["Ticker", "Mkt cap", "Rev gr", "Net %", "P/E", "EV/EBITDA"], rows)
            + "<p class='muted'>* subject. Percentiles + charts in the live cockpit.</p>",
        )
        missing.extend(peers.missing_data)
    else:
        add("peers", "Peer comparison", None)

    # ── Earnings analysis
    if earn is not None and earn.periods:
        rows = [
            [
                rh.esc(p.period),
                rh._money(p.revenue),
                rh._signed_pct(p.revenue_yoy),
                rh._num(p.eps),
                rh._signed_pct(p.eps_yoy),
                ("—" if p.revenue_beat is None else ("Beat" if p.revenue_beat else "Miss")),
            ]
            for p in earn.periods
        ]
        inner = ""
        if earn.summary.headline:
            inner += f"<p>{rh.esc(earn.summary.headline)}</p>"
        inner += rh._table(["Period", "Revenue", "Rev YoY", "EPS", "EPS YoY", "vs est."], rows)
        tr = earn.transcript
        inner += (
            f"<p class='muted'>Transcript: {'available' if tr.available else 'unavailable'}"
            + (
                f" — FY{tr.fiscal_year} Q{tr.quarter}, {rh.esc(tr.date or '')}"
                if tr.available
                else ""
            )
            + "</p>"
        )
        add("earnings", "Earnings analysis", inner)
        prov.extend(earn.provenance)
        missing.extend(earn.missing_data)
    else:
        add("earnings", "Earnings analysis", None)

    # ── Risks + monitoring checklist (deterministic)
    risk_items = list(getattr(fp, "risk_flags", []) or [])
    if thesis is not None:
        risk_items += [r for r in thesis.red_flags if r not in risk_items]
    add("risks", "Risks", rh._bullets(risk_items, empty="No deterministic risk flags surfaced."))
    monitor = thesis.monitor_next_quarter if thesis is not None else []
    add("monitoring", "Monitoring checklist (next quarter)", rh._bullets(monitor, empty="—"))

    # ── Provenance appendix
    prov_rows = [
        [rh.esc(p.dataset), rh.esc(p.source), rh.esc(p.as_of or "—"), rh._pct(p.coverage)]
        for p in prov
    ]
    miss_rows = [[rh.esc(m.dataset), rh.esc(m.reason)] for m in missing]
    appendix = rh._table(["Dataset", "Source", "As of", "Coverage"], prov_rows) + (
        "<h4>Missing data</h4>" + rh._table(["Dataset", "Reason"], miss_rows) if miss_rows else ""
    )
    body.append(rh._section("Data provenance appendix", appendix, appendix=True))
    sections.append(AnalystReportSection(key="provenance", title="Data provenance appendix"))

    html = rh._document(
        title=f"{name} ({tk}) — Research report",
        subtitle="Deterministic, source-attributed equity research · educational only, not financial advice",
        as_of=str(as_of or ""),
        kind="research",
        body="".join(body),
    )

    return AnalystReportOutput(
        ticker=tk,
        title=f"{name} ({tk}) — Research report",
        generated_at=gen,
        as_of=str(as_of or "") or None,
        html=html,
        sections=sections,
        provenance=AnalystReportProvenanceAppendix(items=prov, missing_data=missing),
    )
