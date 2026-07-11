"""Server-rendered, self-contained HTML reports.

Pure presentation. The caller passes the data it already fetched (the risk
report / research fact-pack + verdict / options analysis); these functions render
ONE self-contained HTML document — inline CSS incl. ``@media print``, a
server-generated SVG payoff (no JavaScript), no LLM, no recompute. The visual
summary comes first; a professional appendix follows. Deterministic metrics are
visually separated from the clearly-labelled AI narrative, and every text field
is HTML-escaped (XSS-safe even though the data is the user's own).
"""

from __future__ import annotations

import html as _html
from typing import Any, Optional

from libs.mindmarket_core.score_version import SCORE_VERSION

_DISCLAIMER = (
    "Educational analysis, not investment advice. Figures are computed from "
    "market data; the AI narrative only explains those numbers and never invents "
    "them. Confirm before acting."
)


# ── primitives ──────────────────────────────────────────────────────


def esc(v: Any) -> str:
    return _html.escape(str(v)) if v is not None else ""


def _g(obj: Any, attr: str, default: Any = None) -> Any:
    return getattr(obj, attr, default) if obj is not None else default


def _pct(x: Optional[float], dp: int = 1) -> str:
    return f"{x * 100:.{dp}f}%" if isinstance(x, (int, float)) else "—"


def _signed_pct(x: Optional[float], dp: int = 1) -> str:
    if not isinstance(x, (int, float)):
        return "—"
    return f"{'+' if x >= 0 else ''}{x * 100:.{dp}f}%"


def _num(x: Optional[float], dp: int = 2) -> str:
    return f"{x:.{dp}f}" if isinstance(x, (int, float)) else "—"


def _money(x: Optional[float]) -> str:
    if not isinstance(x, (int, float)):
        return "—"
    a = abs(x)
    sign = "-" if x < 0 else ""
    if a >= 1e12:
        return f"{sign}${a / 1e12:.2f}T"
    if a >= 1e9:
        return f"{sign}${a / 1e9:.2f}B"
    if a >= 1e6:
        return f"{sign}${a / 1e6:.2f}M"
    return f"{sign}${a:,.0f}"


# ── section builders (return HTML fragments) ────────────────────────


def _kpis(items: list[tuple[str, str]]) -> str:
    cells = "".join(
        f'<div class="kpi"><div class="kpi-label">{esc(lbl)}</div>'
        f'<div class="kpi-val">{esc(val)}</div></div>'
        for lbl, val in items
    )
    return f'<div class="kpi-grid">{cells}</div>'


def _table(headers: list[str], rows: list[list[str]]) -> str:
    if not rows:
        return '<p class="muted">No data.</p>'
    head = "".join(f"<th>{esc(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{esc(c)}</td>" for c in r) + "</tr>" for r in rows)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def _bullets(items: list[str], *, empty: str = "None.") -> str:
    items = [i for i in (items or []) if i]
    if not items:
        return f'<p class="muted">{esc(empty)}</p>'
    return "<ul>" + "".join(f"<li>{esc(i)}</li>" for i in items) + "</ul>"


def _section(title: str, inner: str, *, appendix: bool = False) -> str:
    cls = "section appendix" if appendix else "section"
    return f'<section class="{cls}"><h2>{esc(title)}</h2>{inner}</section>'


def _ai_box(title: str, ai_generated: bool, inner: str) -> str:
    tag = "AI-generated" if ai_generated else "Deterministic summary"
    return (
        f'<section class="section ai-box"><div class="ai-head"><h2>{esc(title)}</h2>'
        f'<span class="badge">{esc(tag)}</span></div>{inner}</section>'
    )


def _provenance(sources: list[Any], warnings: list[str]) -> str:
    rows = []
    for s in sources or []:
        field = _g(s, "field") if not isinstance(s, dict) else s.get("field")
        src = _g(s, "source") if not isinstance(s, dict) else s.get("source")
        cov = _g(s, "coverage") if not isinstance(s, dict) else s.get("coverage")
        rows.append([field or "—", src or "—", _pct(cov, 0) if cov is not None else "—"])
    warn_html = (
        '<ul class="warn">' + "".join(f"<li>{esc(w)}</li>" for w in warnings) + "</ul>"
        if warnings
        else ""
    )
    return warn_html + _table(["Field", "Source", "Coverage"], rows)


def _svg_payoff(payoff: list[Any], breakevens: list[float]) -> str:
    """A minimal inline SVG P&L-at-expiry line — deterministic, no JS."""
    pts = []
    for p in payoff or []:
        price = _g(p, "price") if not isinstance(p, dict) else p.get("price")
        pnl = _g(p, "pnl") if not isinstance(p, dict) else p.get("pnl")
        if isinstance(price, (int, float)) and isinstance(pnl, (int, float)):
            pts.append((float(price), float(pnl)))
    if len(pts) < 2:
        return ""
    W, H, pad = 360.0, 130.0, 10.0
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    xmin, xmax = min(xs), max(xs)
    ymin, ymax = min(ys), max(ys)
    xr = (xmax - xmin) or 1.0
    yr = (ymax - ymin) or 1.0

    def sx(x: float) -> float:
        return pad + (x - xmin) / xr * (W - 2 * pad)

    def sy(y: float) -> float:
        return H - pad - (y - ymin) / yr * (H - 2 * pad)

    poly = " ".join(f"{sx(x):.1f},{sy(y):.1f}" for x, y in pts)
    zero = ""
    if ymin < 0 < ymax:
        zy = sy(0.0)
        zero = f'<line x1="{pad:.1f}" y1="{zy:.1f}" x2="{W - pad:.1f}" y2="{zy:.1f}" class="zero"/>'
    be_lines = "".join(
        f'<line x1="{sx(b):.1f}" y1="{pad:.1f}" x2="{sx(b):.1f}" y2="{H - pad:.1f}" class="be"/>'
        for b in (breakevens or [])
        if isinstance(b, (int, float)) and xmin <= b <= xmax
    )
    return (
        f'<svg viewBox="0 0 {W:.0f} {H:.0f}" class="payoff" role="img" '
        f'aria-label="Payoff at expiry">{zero}{be_lines}'
        f'<polyline points="{poly}" class="curve"/></svg>'
    )


# ── document shell ──────────────────────────────────────────────────

_CSS = """
:root{--ink:#0b0e11;--muted:#5b6470;--line:#e3e7ec;--accent:#0b6b75;--bad:#b4232a;--good:#1a7f47;}
*{box-sizing:border-box;}
body{margin:0;background:#f6f7f9;color:var(--ink);font:14px/1.55 -apple-system,Segoe UI,Inter,Arial,sans-serif;}
main{max-width:880px;margin:0 auto;background:#fff;padding:40px 48px;}
.brand{font-size:11px;letter-spacing:.14em;text-transform:uppercase;color:var(--accent);font-weight:600;}
h1{font-size:26px;margin:.2em 0 .1em;}
.subtitle{color:var(--muted);margin:0;}
.asof{color:var(--muted);font-size:12px;margin-top:4px;}
h2{font-size:15px;margin:0 0 10px;padding-bottom:6px;border-bottom:1px solid var(--line);}
.section{margin-top:26px;}
.muted{color:var(--muted);}
.kpi-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;}
.kpi{border:1px solid var(--line);border-radius:8px;padding:9px 11px;}
.kpi-label{font-size:10px;letter-spacing:.06em;text-transform:uppercase;color:var(--muted);}
.kpi-val{font-variant-numeric:tabular-nums;font-weight:600;font-size:16px;margin-top:2px;}
table{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums;}
th,td{text-align:left;padding:5px 8px;border-bottom:1px solid var(--line);font-size:13px;}
th{font-size:10px;letter-spacing:.05em;text-transform:uppercase;color:var(--muted);}
td:not(:first-child),th:not(:first-child){text-align:right;}
ul{margin:6px 0;padding-left:18px;}li{margin:3px 0;}
.warn li{color:var(--bad);}
.ai-box{background:#f4faf9;border:1px solid #d4ebe8;border-radius:10px;padding:14px 16px;margin-top:26px;}
.ai-head{display:flex;align-items:center;justify-content:space-between;gap:10px;}
.ai-head h2{border:0;margin:0;padding:0;}
.badge{font-size:10px;font-weight:600;border:1px solid var(--accent);color:var(--accent);border-radius:999px;padding:2px 8px;text-transform:uppercase;letter-spacing:.05em;}
.pill{display:inline-block;font-weight:600;border-radius:6px;padding:2px 10px;}
.svg-wrap{margin-top:8px;}
.payoff{width:100%;height:auto;}
.payoff .curve{fill:none;stroke:var(--accent);stroke-width:2;}
.payoff .zero{stroke:var(--muted);stroke-width:1;}
.payoff .be{stroke:var(--accent);stroke-width:1;stroke-dasharray:3 3;opacity:.6;}
.disclaimer{margin-top:34px;padding-top:14px;border-top:1px solid var(--line);color:var(--muted);font-size:11px;}
@media print{
  body{background:#fff;}main{max-width:none;padding:0 8px;}
  .appendix{page-break-inside:avoid;}
  h1{font-size:22px;}
  @page{margin:14mm;}
}
"""


def _document(*, title: str, subtitle: str, as_of: str, kind: str, body: str) -> str:
    asof_html = f'<div class="asof">As of {esc(as_of)}</div>' if as_of else ""
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{esc(title)} — MindMarket</title><style>{_CSS}</style></head><body><main>"
        f'<div class="brand">MindMarket · {esc(kind)} report</div>'
        f'<h1>{esc(title)}</h1><p class="subtitle">{esc(subtitle)}</p>{asof_html}'
        f"{body}"
        f'<footer class="disclaimer">Methodology version {esc(SCORE_VERSION)}. '
        f"{esc(_DISCLAIMER)}</footer>"
        "</main></body></html>"
    )


# ── renderers ───────────────────────────────────────────────────────


def render_portfolio_report(report: Any, diagnosis: Any) -> str:
    r = report
    # Visual summary first: AI exec summary (if any) + headline KPIs + top risks.
    ai = ""
    if diagnosis is not None:
        inner = f"<p><strong>{esc(_g(diagnosis, 'headline'))}</strong></p>" + _bullets(
            list(_g(diagnosis, "summary_bullets", []) or [])
        )
        ai = _ai_box("Executive summary", bool(_g(diagnosis, "ai_generated")), inner)

    kpis = _kpis(
        [
            ("Net equity", _money(_g(r, "net_equity") or _g(r, "total_value"))),
            ("Annual vol", _pct(_g(r, "annual_volatility"))),
            ("Sharpe", _num(_g(r, "sharpe_ratio"))),
            ("Max drawdown", _pct(_g(r, "max_drawdown"))),
            # RiskEngine's Monte-Carlo horizon is 21 trading days — label it.
            ("21-day VaR 95%", _pct(_g(r, "var_95"), 2)),
            ("21-day VaR 99%", _pct(_g(r, "var_99"), 2)),
            ("21-day CVaR 95%", _pct(_g(r, "cvar_95"), 2)),
            ("Annual return", _pct(_g(r, "annual_return"))),
        ]
    )

    cv = sorted(_g(r, "component_var_pct", []) or [], key=lambda x: _g(x, "pct", 0), reverse=True)
    drivers = _table(
        ["Holding", "Share of VaR"],
        [[_g(x, "ticker"), _pct(_g(x, "pct"))] for x in cv[:6]],
    )

    conc = _g(r, "concentration")
    conc_html = ""
    if conc is not None:
        conc_html = _kpis(
            [
                (
                    "Top holding",
                    f"{esc(_g(conc, 'top_holding_ticker') or '—')} {_pct(_g(conc, 'top_holding_weight'))}",
                ),
                ("Top 5 weight", _pct(_g(conc, "top5_weight"))),
                ("Effective holdings", _num(_g(conc, "effective_holdings"), 1)),
                (
                    "Top sector",
                    f"{esc(_g(conc, 'top_sector') or '—')} {_pct(_g(conc, 'top_sector_weight'))}",
                ),
            ]
        )

    corr = _g(r, "correlation")
    div_html = ""
    if corr is not None:
        pair = _g(corr, "top_pair")
        best = _g(corr, "best_diversifier")
        dr = _g(corr, "diversification_ratio")
        div_html = _kpis(
            [
                ("Avg pairwise \u03c1", _num(_g(corr, "avg_pairwise"))),
                ("Diversification ratio", f"{_num(dr)}\u00d7" if dr is not None else "—"),
                (
                    "Most correlated pair",
                    (
                        f"{esc(_g(pair, 'a'))} \u00d7 {esc(_g(pair, 'b'))} ({_num(_g(pair, 'rho'))})"
                        if pair is not None
                        else "—"
                    ),
                ),
                (
                    "Best diversifier",
                    (
                        f"{esc(_g(best, 'ticker'))} (avg \u03c1 {_num(_g(best, 'avg_rho'))})"
                        if best is not None
                        else "—"
                    ),
                ),
            ]
        )

    rv = _g(r, "rolling_volatility")
    rv_html = ""
    if rv is not None:
        rv_html = (
            f"<p>21-day rolling annualized volatility: current "
            f"<strong>{_pct(_g(rv, 'current'))}</strong> vs "
            f"{_pct(_g(rv, 'median'))} median over the window "
            f"(<strong>{esc(str(_g(rv, 'state') or 'normal'))}</strong>)."
            " Leverage-adjusted; the headline annual vol is the faster-reacting"
            " EWMA estimate.</p>"
        )

    factor = _table(
        ["Factor", "Beta", "R²"],
        [
            [_g(x, "factor"), _num(_g(x, "beta")), _num(_g(x, "r_squared"))]
            for x in _g(r, "factor_betas", []) or []
        ],
    )

    stress_shock = _g(r, "stress_market_shock")
    stress_rows = sorted(_g(r, "stress_asset_losses", []) or [], key=lambda x: _g(x, "loss_pct", 0))
    stress = (
        f'<p>Modelled portfolio loss under a {_pct(abs(stress_shock)) if stress_shock else "market"} '
        f'shock: <strong>{_signed_pct(-(_g(r, "stress_loss") or 0))}</strong>.</p>'
        + _table(
            ["Holding", "Loss"],
            [[_g(x, "ticker"), _signed_pct(_g(x, "loss_pct"))] for x in stress_rows[:8]],
        )
    )

    liq = _table(
        ["Holding", "Days to liquidate", "ADV (30d)"],
        [
            [_g(x, "ticker"), _num(_g(x, "days_to_liquidate"), 1), _money(_g(x, "adv_30d"))]
            for x in _g(r, "liquidity", []) or []
        ],
    )

    checklist = (
        _bullets(
            [_g(a, "title") for a in _g(diagnosis, "suggested_actions", []) or []],
            empty="No actions flagged.",
        )
        if diagnosis is not None
        else '<p class="muted">Run the AI diagnosis to populate a monitoring checklist.</p>'
    )

    notes = _bullets(list(_g(r, "data_quality_notes", []) or []), empty="No data-quality caveats.")

    body = (
        ai
        + _section("Key metrics", kpis)
        + _section("Top risk drivers", drivers)
        + (_section("Concentration", conc_html) if conc_html else "")
        + (_section("Diversification & correlation", div_html) if div_html else "")
        + (_section("Realized volatility", rv_html) if rv_html else "")
        + _section("Monitoring checklist", checklist)
        + _section("Factor exposure", factor, appendix=True)
        + _section("Stress test", stress, appendix=True)
        + _section("Liquidity", liq, appendix=True)
        + _section("Data quality & caveats", notes, appendix=True)
    )
    return _document(
        title="Portfolio Risk Report",
        subtitle="Health, risk drivers, factor exposure, stress and liquidity.",
        as_of="",
        kind="portfolio",
        body=body,
    )


def render_ticker_report(fact_pack: Any, verdict: Any) -> str:
    fp = fact_pack
    name = _g(fp, "name") or _g(fp, "ticker")
    subtitle = " · ".join(x for x in [_g(fp, "sector"), _g(fp, "industry")] if x)

    ai = ""
    if verdict is not None:
        dims = _table(
            ["Dimension", "Score", "Note"],
            [
                [_g(d, "name"), f"{_num(_g(d, 'score'), 0)}/100", _g(d, "note") or ""]
                for d in _g(verdict, "dimensions", []) or []
            ],
        )
        inner = (
            f'<p><span class="pill">{esc(_g(verdict, "rating"))}</span> '
            f'<span class="muted">{esc(_g(verdict, "conviction"))} conviction</span></p>'
            f"<p>{esc(_g(verdict, 'summary'))}</p>{dims}"
        )
        ai = _ai_box("AI analyst view", not bool(_g(verdict, "data_only")), inner)

    head = _kpis(
        [
            ("Price", _money(_g(fp, "price"))),
            ("Market cap", _money(_g(fp, "market_cap"))),
            ("Beta", _num(_g(fp, "beta"))),
            ("Ticker", esc(_g(fp, "ticker"))),
        ]
    )

    v = _g(fp, "valuation")
    valuation = _kpis(
        [
            ("P/E", _num(_g(v, "pe"))),
            ("Fwd P/E", _num(_g(v, "forward_pe"))),
            ("P/S", _num(_g(v, "ps"))),
            ("EV/EBITDA", _num(_g(v, "ev_ebitda"))),
            ("FCF yield", _pct(_g(v, "fcf_yield"))),
            ("Div yield", _pct(_g(v, "dividend_yield"))),
            ("Band", esc(_g(v, "band") or "—")),
            ("Peer median P/E", _num(_g(v, "peer_median_pe"))),
        ]
    )

    q = _g(fp, "quality")
    grw = _g(fp, "growth")
    fundamentals = _kpis(
        [
            ("Gross margin", _pct(_g(q, "gross_margin"))),
            ("Net margin", _pct(_g(q, "net_margin"))),
            ("ROE", _pct(_g(q, "roe"))),
            ("Debt/Equity", _num(_g(q, "debt_to_equity"))),
            ("Revenue CAGR", _pct(_g(grw, "revenue_cagr"))),
            ("EPS CAGR", _pct(_g(grw, "eps_cagr"))),
            ("FCF CAGR", _pct(_g(grw, "fcf_cagr"))),
            ("Revenue YoY", _pct(_g(grw, "revenue_growth_yoy"))),
        ]
    )

    m = _g(fp, "momentum")
    technicals = (
        _kpis(
            [
                ("RSI (14)", _num(_g(m, "rsi_14"))),
                ("Trend", esc(_g(m, "trend") or "—")),
                ("From 52w high", _signed_pct(_g(m, "pct_from_52w_high"))),
                ("Realized vol 60d", _pct(_g(m, "realized_vol_60d"))),
            ]
        )
        if m is not None
        else '<p class="muted">No technicals available.</p>'
    )

    a = _g(fp, "analyst")
    analyst = _kpis(
        [
            ("Rating", esc(_g(a, "rating") or "—")),
            ("# analysts", _num(_g(a, "num_analysts"), 0)),
            ("Consensus target", _money(_g(a, "target_consensus"))),
            ("Implied upside", _signed_pct(_g(a, "implied_upside_pct"))),
        ]
    )

    peers = _table(
        ["Peer", "P/E", "P/S", "Net margin", "ROE"],
        [
            [
                _g(p, "ticker"),
                _num(_g(p, "pe")),
                _num(_g(p, "ps")),
                _pct(_g(p, "net_margin")),
                _pct(_g(p, "roe")),
            ]
            for p in _g(fp, "peers", []) or []
        ],
    )

    news = _bullets(
        [
            f"{_g(n, 'title')} — {_g(n, 'site') or ''} {_g(n, 'published') or ''}".strip()
            for n in _g(fp, "news", []) or []
        ],
        empty="No recent headlines.",
    )

    drivers = _bullets(list(_g(fp, "drivers", []) or []), empty="No standout drivers.")
    flags = _bullets(list(_g(fp, "risk_flags", []) or []), empty="No risk flags.")
    casework = ""
    if verdict is not None:
        casework = (
            "<h3>Catalysts</h3>"
            + _bullets(list(_g(verdict, "catalysts", []) or []))
            + "<h3>Key risks</h3>"
            + _bullets(list(_g(verdict, "risks", []) or []))
            + "<h3>What would change the view</h3>"
            + _bullets(list(_g(verdict, "what_would_change_my_mind", []) or []))
        )

    dq = _g(fp, "data_quality")
    sources = _provenance(_g(dq, "sources", []) or [], list(_g(dq, "warnings", []) or []))

    body = (
        _section("Overview", head)
        + ai
        + _section("Valuation", valuation, appendix=True)
        + _section("Fundamentals & growth", fundamentals, appendix=True)
        + _section("Technicals", technicals, appendix=True)
        + _section("Analyst consensus", analyst, appendix=True)
        + _section("Peers", peers, appendix=True)
        + _section("News & events", news, appendix=True)
        + _section("Drivers", drivers, appendix=True)
        + _section("Risk flags", flags, appendix=True)
        + (_section("Bull / bear case", casework, appendix=True) if casework else "")
        + _section("Sources & provenance", sources, appendix=True)
    )
    return _document(
        title=f"{name} ({_g(fp, 'ticker')}) — Research Report",
        subtitle=subtitle,
        as_of=str(_g(fp, "as_of") or ""),
        kind="ticker",
        body=body,
    )


def render_options_report(analysis: Any) -> str:
    exp = _g(analysis, "exposure")
    exposure = (
        _kpis(
            [
                ("Net delta", _num(_g(exp, "net_delta"), 1)),
                ("Net gamma", _num(_g(exp, "net_gamma"), 2)),
                ("Net theta/day", _num(_g(exp, "net_theta"), 1)),
                ("Net vega", _num(_g(exp, "net_vega"), 1)),
                ("Option notional", _money(_g(exp, "option_notional"))),
                ("Short collateral", _money(_g(exp, "short_collateral_estimate"))),
                ("Contracts", _num(_g(exp, "contracts"), 0)),
                ("Short contracts", _num(_g(exp, "short_contracts"), 0)),
            ]
        )
        if exp is not None
        else ""
    )
    flags = (
        _bullets(
            [_g(f, "detail") for f in _g(exp, "flags", []) or []], empty="No option risk flags."
        )
        if exp is not None
        else ""
    )

    strat_html = ""
    for s in _g(analysis, "strategies", []) or []:
        credit = (_g(s, "net_debit") or 0) < 0
        g = _g(s, "net_greeks") or {}
        rows = _kpis(
            [
                ("Net " + ("credit" if credit else "debit"), _money(abs(_g(s, "net_debit") or 0))),
                (
                    "Max loss",
                    _money(_g(s, "max_loss")) if _g(s, "max_loss") is not None else "Unbounded",
                ),
                (
                    "Max gain",
                    _money(_g(s, "max_gain")) if _g(s, "max_gain") is not None else "Unbounded",
                ),
                ("Break-even", ", ".join(_money(b) for b in (_g(s, "break_evens") or [])) or "—"),
            ]
        )
        greeks = _kpis(
            [
                ("Net Δ", _num(g.get("delta"), 1)),
                ("Net Γ", _num(g.get("gamma"), 2)),
                ("Net Θ/day", _num(g.get("theta"), 1)),
                ("Net ν", _num(g.get("vega"), 1)),
            ]
        )
        svg = _svg_payoff(_g(s, "payoff", []) or [], list(_g(s, "break_evens", []) or []))
        svg_block = f'<div class="svg-wrap">{svg}</div>' if svg else ""
        title = f"{_g(s, 'name')} · {_g(s, 'underlying')} {_g(s, 'expiry')}"
        strat_html += _section(esc(title), rows + greeks + svg_block)

    legs = _table(
        ["Underlying", "Type", "Strike", "Qty", "Mark", "Source"],
        [
            [
                _g(c, "underlying"),
                _g(c, "option_type"),
                _num(_g(c, "strike"), 0),
                _num(_g(c, "quantity"), 0),
                _money(_g(c, "mark")),
                _g(c, "source"),
            ]
            for c in _g(analysis, "results", []) or []
        ],
    )

    body = (
        (_section("Portfolio option exposure", exposure + flags) if exposure else "")
        + strat_html
        + _section("All legs (price source noted)", legs, appendix=True)
    )
    return _document(
        title="Options Strategy Report",
        subtitle="Net strategy economics, Greeks, payoff and price provenance.",
        as_of=str(_g(analysis, "as_of") or ""),
        kind="options",
        body=body,
    )
