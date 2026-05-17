"""Reusable data-quality panel for analysis pages.

A DataQualityReport summarizes the upstream data sources behind an
analysis result so the user can tell when a graph or KPI is built on
incomplete inputs (yfinance rate-limited, FMP key missing, fewer
tickers loaded than configured, etc.). The label (High/Medium/Low) is
mechanically computed from the fraction of sources that returned
something usable.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal, Optional

Status = Literal["ok", "partial", "missing", "stale"]
Freshness = Literal["live", "cached", "fallback", "unavailable"]

_STATUS_ICON = {
    "ok": "✅",
    "partial": "🟡",
    "missing": "❌",
    "stale": "⚠️",
}

_FRESHNESS_LABEL = {
    "live": "live",
    "cached": "cached",
    "fallback": "fallback",
    "unavailable": "unavailable",
}


@dataclass(frozen=True)
class DataSource:
    """A single upstream data source feeding an analysis page.

    Attributes:
        name:        human-readable, e.g. "Yahoo Finance prices"
        status:      ok / partial / missing / stale
        note:        free-form e.g. "8/10 tickers loaded"
        freshness:   live / cached / fallback / unavailable. Optional —
                     omit when the page doesn't have a meaningful answer.
                     Surfaces in the panel so the user can tell at a
                     glance whether a number is real-time or stale.
        last_updated: when the source was last refreshed. Optional;
                     rendered as relative time ("12m ago"). UTC datetime.
    """

    name: str
    status: Status
    note: Optional[str] = None
    freshness: Optional[Freshness] = None
    last_updated: Optional[datetime] = None


@dataclass(frozen=True)
class DataQualityReport:
    """Aggregate report over all data sources powering a page."""

    sources: tuple[DataSource, ...]

    @property
    def label(self) -> Literal["High", "Medium", "Low"]:
        ok = sum(1 for s in self.sources if s.status == "ok")
        partial = sum(1 for s in self.sources if s.status == "partial")
        total = len(self.sources)
        if total == 0:
            return "Low"
        score = (ok + 0.5 * partial) / total
        if score >= 0.8:
            return "High"
        if score >= 0.5:
            return "Medium"
        return "Low"

    @property
    def coverage_str(self) -> str:
        ok = sum(1 for s in self.sources if s.status == "ok")
        return f"{ok}/{len(self.sources)} sources"


# ── Rendering ───────────────────────────────────────────────


def render_data_quality_panel(report: DataQualityReport, *, expanded: bool = False) -> None:
    """Render the report as a Streamlit expander.

    Uses ``st.expander`` so it doesn't take vertical space by default.
    Shows label + coverage in the header; details (per-source status
    and notes) when expanded. Color-coded with an emoji per status.
    """
    # Import inside the function so unit tests can mock the streamlit module
    # at call time via monkeypatch.setitem(sys.modules, "streamlit", ...).
    import streamlit as st  # noqa: WPS433 (intentional local import)

    label = report.label
    label_emoji = {"High": "🟢", "Medium": "🟡", "Low": "🔴"}.get(label, "•")
    header = f"Data quality: {label_emoji} {label} ({report.coverage_str})"

    try:
        ctx = st.expander(header, expanded=expanded)
    except Exception:
        # Defensive: in a non-Streamlit context just no-op.
        return

    # The expander returned by streamlit is a context manager. Mocks may not
    # implement __enter__/__exit__, so guard the with-block.
    enter = getattr(ctx, "__enter__", None)
    exit_ = getattr(ctx, "__exit__", None)
    if callable(enter) and callable(exit_):
        with ctx:
            _render_source_rows(st, report)
    else:
        _render_source_rows(st, report)


def _humanize_age(dt: Optional[datetime]) -> Optional[str]:
    """Render a datetime as a short relative-time string ('12m ago')."""
    if dt is None:
        return None
    try:
        now = datetime.now(timezone.utc)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        delta = now - dt
        sec = int(delta.total_seconds())
        if sec < 0:
            return "in the future"
        if sec < 60:
            return f"{sec}s ago"
        if sec < 3600:
            return f"{sec // 60}m ago"
        if sec < 86400:
            return f"{sec // 3600}h ago"
        return f"{sec // 86400}d ago"
    except Exception:
        return None


def _render_source_rows(st: Any, report: DataQualityReport) -> None:
    if not report.sources:
        st.caption("No data sources tracked.")
        return
    for s in report.sources:
        icon = _STATUS_ICON.get(s.status, "•")
        bits = [f"{icon} **{s.name}** — _{s.status}_"]
        if s.freshness:
            bits.append(f"_{_FRESHNESS_LABEL[s.freshness]}_")
        age = _humanize_age(s.last_updated)
        if age:
            bits.append(age)
        if s.note:
            bits.append(s.note)
        st.markdown("  ·  ".join(bits))


# ── Per-page report-builders ────────────────────────────────


def _safe_len(x: Any) -> int:
    try:
        return len(x)  # type: ignore[arg-type]
    except Exception:
        return 0


def _prices_coverage(weights: dict, prices_df: Any) -> tuple[Status, str]:
    """Return status + note describing how much of `weights` has price columns."""
    expected = list(weights.keys()) if weights else []
    if not expected:
        return "missing", "no holdings configured"
    cols = getattr(prices_df, "columns", None)
    if cols is None:
        return "missing", "no price history loaded"
    try:
        col_set = set(cols)
    except TypeError:
        col_set = set(list(cols))
    have = sum(1 for tk in expected if tk in col_set)
    total = len(expected)
    note = f"{have}/{total} tickers loaded"
    if have == 0:
        return "missing", note
    if have < total:
        return "partial", note
    return "ok", note


def overview_report(*, weights: dict, prices_df: Any, meta: Optional[dict]) -> DataQualityReport:
    """Build a DataQualityReport for pages/1_Overview.py."""
    weights = weights or {}
    meta = meta or {}

    # 1) Holdings loaded
    holdings_status: Status = "ok" if len(weights) > 0 else "missing"
    holdings_note = f"{len(weights)} positions"

    # 2) Price coverage
    price_status, price_note = _prices_coverage(weights, prices_df)

    # 3) Cost basis coverage — pulled from the ACTIVE portfolio resolver
    # (DB-backed for authed users, hardcoded demo only for anonymous
    # visitors). Reading portfolio_config.PORTFOLIO_HOLDINGS directly
    # would attribute the developer's cost basis to every signed-in
    # user — a data-attribution bug we fixed elsewhere in this codebase.
    cost_status: Status
    cost_note: str
    try:
        from libs.auth.active_portfolio import get_active_holdings

        active_holdings = get_active_holdings() or {}
    except Exception:
        active_holdings = {}
    if not weights:
        cost_status, cost_note = "missing", "no holdings"
    else:
        with_cost = 0
        for tk in weights:
            h = active_holdings.get(tk, {}) if isinstance(active_holdings, dict) else {}
            if h and h.get("avg_cost") is not None:
                with_cost += 1
        total = len(weights)
        cost_note = f"{with_cost}/{total} holdings have cost"
        if with_cost == total:
            cost_status = "ok"
        elif with_cost == 0:
            cost_status = "missing"
        else:
            cost_status = "partial"

    # 4) Portfolio meta
    net_equity = meta.get("net_equity") if isinstance(meta, dict) else None
    meta_status: Status = "ok" if net_equity not in (None, 0) else "missing"
    meta_note = (
        f"net equity ${net_equity:,.0f}"
        if isinstance(net_equity, (int, float)) and net_equity
        else None
    )

    # Freshness signals — Yahoo Finance prices come from a cached
    # DataProvider (24h TTL via @st.cache_resource), so "live" is rarely
    # accurate. Mark them as cached unless they're missing entirely.
    yf_freshness: Optional[Freshness]
    yf_last: Optional[datetime]
    if price_status == "missing":
        yf_freshness = "unavailable"
        yf_last = None
    else:
        yf_freshness = "cached"
        yf_last = _now_utc()
    return DataQualityReport(
        sources=(
            DataSource("Portfolio holdings", holdings_status, holdings_note),
            DataSource(
                "Price history (Yahoo Finance)",
                price_status,
                price_note,
                freshness=yf_freshness,
                last_updated=yf_last,
            ),
            DataSource("Cost basis coverage", cost_status, cost_note),
            DataSource("Portfolio meta (equity, leverage)", meta_status, meta_note),
        )
    )


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _has_values(obj: Any) -> bool:
    """Return True if `obj` is non-None and non-empty."""
    if obj is None:
        return False
    # numpy arrays
    try:
        n = len(obj)  # type: ignore[arg-type]
        return n > 0
    except TypeError:
        pass
    # pandas-like with .empty
    empty = getattr(obj, "empty", None)
    if empty is not None:
        try:
            return not bool(empty)
        except Exception:
            return True
    return True


def risk_report(*, weights: dict, prices_df: Any, report_obj: Any) -> DataQualityReport:
    """Build a DataQualityReport for pages/2_Risk.py."""
    weights = weights or {}
    price_status, price_note = _prices_coverage(weights, prices_df)

    mc_returns = getattr(report_obj, "mc_portfolio_returns", None)
    mc_status: Status = "ok" if _has_values(mc_returns) else "missing"
    mc_note: Optional[str] = None
    try:
        n = len(mc_returns) if mc_returns is not None else 0  # type: ignore[arg-type]
        if n:
            mc_note = f"{n:,} simulated paths"
    except TypeError:
        pass

    factor_betas = getattr(report_obj, "factor_betas", None)
    factor_status: Status = "ok" if _has_values(factor_betas) else "missing"

    comp_var = getattr(report_obj, "component_var_pct", None)
    comp_status: Status = "ok" if _has_values(comp_var) else "missing"

    margin_info = getattr(report_obj, "margin_call_info", None)
    margin_status: Status = "ok" if margin_info else "missing"

    # MC + factor + component-VaR all derived from the current run.
    # Their freshness mirrors the underlying analysis: "live" when the
    # report exists, "unavailable" otherwise.
    derived_freshness: Freshness = "live" if mc_status == "ok" else "unavailable"
    now = _now_utc()
    return DataQualityReport(
        sources=(
            DataSource(
                "Price history (Yahoo Finance)",
                price_status,
                price_note,
                freshness="cached" if price_status != "missing" else "unavailable",
                last_updated=now if price_status != "missing" else None,
            ),
            DataSource(
                "Monte Carlo simulation",
                mc_status,
                mc_note,
                freshness=derived_freshness,
                last_updated=now if mc_status == "ok" else None,
            ),
            DataSource("Factor exposures", factor_status, freshness=derived_freshness),
            DataSource("Component VaR", comp_status, freshness=derived_freshness),
            DataSource("Margin call check", margin_status, freshness=derived_freshness),
        )
    )


def trading_floor_report(
    *,
    regime_data: Any,
    sector_data: Any,
    movers_data: Any,
    market_regime_data: Any,
) -> DataQualityReport:
    """Build a DataQualityReport for pages/7_Trading_Floor.py."""

    def _s(x: Any) -> Status:
        return "ok" if _has_values(x) else "missing"

    return DataQualityReport(
        sources=(
            DataSource("Regime detector", _s(regime_data)),
            DataSource("Sector scan", _s(sector_data)),
            DataSource("S&P 500 movers", _s(movers_data)),
            DataSource("Market regime (VIX / yield / F&G)", _s(market_regime_data)),
        )
    )


def quant_lab_report(*, weights: dict, prices_df: Any, report_obj: Any) -> DataQualityReport:
    """Build a DataQualityReport for pages/9_Quant_Lab.py.

    Same inputs as risk_report but also reflects whether a backtest result
    has been cached in session_state.
    """
    base = risk_report(weights=weights, prices_df=prices_df, report_obj=report_obj)

    # Backtest status — peek at streamlit session_state if available.
    bt_status: Status = "missing"
    try:
        import streamlit as st  # noqa: WPS433

        bt = st.session_state.get("backtest_result")
        if _has_values(bt):
            bt_status = "ok"
    except Exception:
        pass

    return DataQualityReport(
        sources=base.sources + (DataSource("Backtest result (cached)", bt_status),)
    )
