"""Deterministic peer comparison engine (Phase 2).

Selects a peer set (user → FMP peers → curated mega-cap map → sector fallback),
fetches each company's metrics, and computes the peer median + the subject's
percentile rank per metric — all in backend code, no LLM. Missing metrics are
explicit; each metric carries a source. Fail-soft: a provider failure for any
ticker degrades that row to nulls rather than raising.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from statistics import median
from typing import Optional

from ..schemas.research import MissingDataItem
from ..schemas.valuation import (
    PeerComparisonOutput,
    PeerComparisonRow,
    PeerMetricProvenance,
    PeerPercentile,
)
from .providers import fmp_provider

_log = logging.getLogger(__name__)
_MAX_PEERS = 6

# Curated mega-cap fallback (used only when FMP peers are unavailable).
_CURATED_BY_TICKER: dict[str, list[str]] = {
    "AAPL": ["MSFT", "GOOGL", "AMZN", "META", "SAMSUNG"],
    "MSFT": ["AAPL", "GOOGL", "AMZN", "ORCL", "CRM"],
    "GOOGL": ["MSFT", "META", "AMZN", "AAPL"],
    "AMZN": ["MSFT", "GOOGL", "WMT", "AAPL"],
    "META": ["GOOGL", "SNAP", "PINS", "MSFT"],
    "NVDA": ["AMD", "AVGO", "INTC", "QCOM", "TSM"],
    "AMD": ["NVDA", "INTC", "AVGO", "QCOM"],
    "TSLA": ["GM", "F", "RIVN", "TM", "NIO"],
    "JPM": ["BAC", "WFC", "C", "GS", "MS"],
    "BAC": ["JPM", "WFC", "C", "USB"],
}

# Sector fallback (representative large caps per sector).
_CURATED_BY_SECTOR: dict[str, list[str]] = {
    "Technology": ["AAPL", "MSFT", "NVDA", "GOOGL", "AVGO"],
    "Communication Services": ["GOOGL", "META", "NFLX", "DIS"],
    "Consumer Cyclical": ["AMZN", "TSLA", "HD", "MCD"],
    "Financial Services": ["JPM", "BAC", "WFC", "GS", "MS"],
    "Healthcare": ["UNH", "JNJ", "LLY", "PFE", "MRK"],
    "Energy": ["XOM", "CVX", "COP", "SLB"],
    "Industrials": ["GE", "CAT", "BA", "HON"],
}

# Metrics ranked. `lower_is_better` flips the percentile so "good" is always 1.0.
_METRICS = [
    "revenue_growth",
    "gross_margin",
    "operating_margin",
    "net_margin",
    "fcf_margin",
    "roe",
    "roic",
    "pe",
    "forward_pe",
    "ev_sales",
    "ev_ebitda",
    "ps",
    "debt_to_equity",
    "net_cash",
    "market_cap",
]
_DERIVED = {"revenue_growth", "fcf_margin", "ev_sales", "net_cash"}


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_div(a, b):
    if a is None or b in (None, 0):
        return None
    return a / b


def _growth(curr, base):
    if curr is None or base is None or base <= 0:
        return None
    return curr / base - 1.0


def _metrics_for(ticker: str, *, is_subject: bool) -> PeerComparisonRow:
    """Fetch one ticker's comparison metrics. Fail-soft per provider call."""
    tk = ticker.strip().upper()
    prof = fmp_provider.get_profile(tk).data
    rat = fmp_provider.get_fundamentals(tk).data
    stmts = fmp_provider.get_financial_statements(tk, period="annual", limit=2).data or []
    latest = stmts[0] if stmts else {}
    prior = stmts[1] if len(stmts) > 1 else {}

    rev = latest.get("revenue")
    mcap = getattr(prof, "market_cap", None)
    net_debt = None
    if latest.get("debt") is not None or latest.get("cash") is not None:
        net_debt = (latest.get("debt") or 0.0) - (latest.get("cash") or 0.0)
    ev_sales = (
        (mcap + net_debt) / rev if (mcap is not None and net_debt is not None and rev) else None
    )

    return PeerComparisonRow(
        ticker=tk,
        name=getattr(prof, "name", None),
        is_subject=is_subject,
        market_cap=mcap,
        revenue_growth=_growth(rev, prior.get("revenue")),
        gross_margin=(
            getattr(rat, "gross_margin", None)
            if rat
            else _safe_div(latest.get("gross_profit"), rev)
        ),
        operating_margin=(
            getattr(rat, "operating_margin", None)
            if rat
            else _safe_div(latest.get("operating_income"), rev)
        ),
        net_margin=getattr(rat, "net_margin", None),
        fcf_margin=_safe_div(latest.get("free_cash_flow"), rev),
        roe=getattr(rat, "roe", None),
        roic=getattr(rat, "roic", None),
        pe=getattr(rat, "pe", None),
        forward_pe=getattr(rat, "forward_pe", None),
        ev_sales=ev_sales,
        ev_ebitda=getattr(rat, "ev_ebitda", None),
        ps=getattr(rat, "ps", None),
        debt_to_equity=getattr(rat, "debt_to_equity", None),
        net_cash=(-net_debt if net_debt is not None else None),
        return_1y=None,  # deferred: a per-peer price-history fetch is call-heavy
    )


def _select_peers(tk: str, profile, user_peers: Optional[list[str]]) -> tuple[list[str], str]:
    if user_peers:
        return [p for p in user_peers if p != tk][:_MAX_PEERS], "user"
    fmp = fmp_provider.get_peers(tk).data or []
    syms = [p.ticker.upper() for p in fmp if p.ticker and p.ticker.upper() != tk][:_MAX_PEERS]
    if syms:
        return syms, "fmp"
    if tk in _CURATED_BY_TICKER:
        return [p for p in _CURATED_BY_TICKER[tk] if p != tk][:_MAX_PEERS], "curated"
    sector = getattr(profile, "sector", None)
    if sector and sector in _CURATED_BY_SECTOR:
        return [p for p in _CURATED_BY_SECTOR[sector] if p != tk][:_MAX_PEERS], "sector"
    return [], "none"


def compute_percentiles(rows: list[PeerComparisonRow]) -> list[PeerPercentile]:
    """Per metric: peer median + the subject's percentile rank (fraction of the
    set strictly below the subject; 0 = lowest, 1 = highest). Needs ≥2 non-null
    values; otherwise percentile is None but the median still reports if present."""
    subject = next((r for r in rows if r.is_subject), None)
    out: list[PeerPercentile] = []
    for m in _METRICS:
        vals = [getattr(r, m) for r in rows if getattr(r, m) is not None]
        sv = getattr(subject, m) if subject else None
        med = median(vals) if vals else None
        pct = None
        if sv is not None and len(vals) >= 2:
            below = sum(1 for v in vals if v < sv)
            pct = round(below / (len(vals) - 1), 4)
        out.append(
            PeerPercentile(metric=m, subject_value=sv, peer_median=med, percentile=pct, n=len(vals))
        )
    return out


def build_peer_comparison(
    ticker: str, *, user_peers: Optional[list[str]] = None
) -> PeerComparisonOutput:
    """Build the peer set + metrics + percentiles. Never raises on provider
    failure (degrades to nulls + missing-data entries)."""
    tk = ticker.strip().upper()
    fetched = _iso_now()
    profile = fmp_provider.get_profile(tk).data
    peer_syms, source = _select_peers(tk, profile, user_peers)

    rows = [_metrics_for(tk, is_subject=True)]
    for sym in peer_syms:
        rows.append(_metrics_for(sym, is_subject=False))

    percentiles = compute_percentiles(rows)

    missing: list[MissingDataItem] = []
    if not peer_syms:
        missing.append(MissingDataItem(dataset="peers", reason="empty"))
    for p in percentiles:
        if p.subject_value is None:
            missing.append(MissingDataItem(dataset=f"subject.{p.metric}", reason="empty"))
    missing.append(MissingDataItem(dataset="return_1y", reason="not_fetched"))

    provenance = [
        PeerMetricProvenance(
            metric=m, source=("derived" if m in _DERIVED else "fmp"), as_of=fetched
        )
        for m in _METRICS
    ]

    return PeerComparisonOutput(
        ticker=tk,
        as_of=fetched,
        generated_at=fetched,
        peer_source=source,
        rows=rows,
        percentiles=percentiles,
        provenance=provenance,
        missing_data=missing,
    )
