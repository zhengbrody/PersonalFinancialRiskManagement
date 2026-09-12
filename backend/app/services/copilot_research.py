"""Bounded projection of ONE captured Research FactPack. No fetching or LLM calls.

No article body, external instructions, ratings, drivers or provider prose enter
the numerical evidence or a prompt. Method questions are our untested hypotheses,
not analyst quotes. Block-level provenance cannot establish reporting periods.
"""

import ipaddress
import math
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from ..schemas.copilot_research import (
    CopilotResearch,
    ResearchLead,
    ResearchObservation,
    ResearchQuestion,
)
from .analyst_methods import select_methods

_FIELDS = (
    ("valuation.pe", "fundamentals", "ratio"),
    ("quality.net_margin", "fundamentals", "fraction"),
    ("quality.debt_to_equity", "fundamentals", "ratio"),
    ("growth.revenue_cagr", "growth", "fraction"),
)


def _date(value):
    try:
        date = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return date if date.tzinfo is not None else None
    except (ValueError, TypeError):
        return None


def safe_research_url(value):
    """Only outbound public HTTPS links. Never fetch user/provider URLs."""
    try:
        parsed = urlsplit(value or "")
        host = parsed.hostname or ""
        if (
            parsed.scheme != "https"
            or parsed.username
            or parsed.password
            or parsed.port not in (None, 443)
            or "." not in host
            or host.endswith((".local", ".internal", ".localhost"))
            or any(ord(char) < 33 for char in value)
        ):
            return None
        try:
            ipaddress.ip_address(host)
            return None
        except ValueError:
            return value
    except (ValueError, TypeError):
        return None


def build_context(ticker, fp, *, now=None):
    now = now or datetime.now(timezone.utc)
    # A mislabeled or wrong-security cache entry is never reused.
    if fp is not None and fp.ticker != ticker:
        fp = None
    sources = {s.field: s for s in fp.data_quality.sources} if fp else {}
    observations = []
    for metric, block, unit in _FIELDS:
        part, field = metric.split(".")
        value = getattr(getattr(fp, part, None), field, None)
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
        ):
            value = None
        source = sources.get(block)
        if source and source.source not in {"fmp", "yfinance", "fmp+yfinance"}:
            source = None
        as_of = _date(source.as_of) if source else None
        provenance = (
            "block_only" if source and source.source not in ("", "unavailable") else "unavailable"
        )
        status = "available"
        if value is None:
            status = "missing"
        elif not as_of or as_of > now or provenance == "unavailable":
            status = "undated"
        elif now - as_of > timedelta(days=1) or (fp.cache and fp.cache.stale):
            status = "stale"
        observations.append(
            ResearchObservation(
                id=f"{ticker}:{metric}",
                ticker=ticker,
                metric=metric,
                value=value,
                unit=unit,
                source=source.source if source else "unavailable",
                source_as_of=as_of,
                basis=(
                    "computed_from_series"
                    if metric == "growth.revenue_cagr"
                    else "provider_projection"
                ),
                provenance=provenance,
                status=status,
            )
        )
    questions = [
        ResearchQuestion(
            method_id="valuation",
            hypothesis="A business-growth story needs support from revenue growth and sustainable margins.",
            observation_ids=[f"{ticker}:growth.revenue_cagr", f"{ticker}:quality.net_margin"],
            counterpoint="Past growth can reflect a favourable cycle or acquisitions; margins may not persist.",
            invalidation_check="Check comparable reporting periods, organic growth and the next filing for deteriorating margins before accepting the story.",
        ),
        ResearchQuestion(
            method_id="downside",
            hypothesis="An apparently modest earnings multiple still needs a financing and earnings-quality check.",
            observation_ids=[f"{ticker}:valuation.pe", f"{ticker}:quality.debt_to_equity"],
            counterpoint="Low multiples can accompany declining earnings; debt-to-equity alone cannot establish liquidity or debt-service capacity.",
            invalidation_check="Inspect cash flow, debt maturities and downside earnings. Missing funding information leaves this hypothesis unresolved.",
        ),
    ]
    leads, seen = [], set()
    for item in (fp.news[:6] if fp else []):
        url = safe_research_url(item.url)
        if not url or url in seen:
            continue
        seen.add(url)
        leads.append(
            ResearchLead(
                title=item.title[:240],
                publisher=(item.site or "")[:120] or None,
                published_at=_date(item.published),
                url=url,
            )
        )
        if len(leads) == 3:
            break
    present = sum(o.value is not None for o in observations)
    return CopilotResearch(
        ticker=ticker,
        captured_at=now,
        status=(
            "unavailable"
            if not present
            else ("available" if all(o.status == "available" for o in observations) else "partial")
        ),
        observations=observations,
        questions=questions,
        leads=leads,
        methods=select_methods("valuation"),
        limitations=[
            "Existing Research providers are reused; this is not a new data feed or model training.",
            "Sources are attributed at data-block level. Exact field origin and financial reporting periods are not established.",
            "Freshness describes the provider snapshot timestamp, not the underlying financial reporting period.",
            "Questions are untested MindMarket hypotheses, not conclusions or analyst recommendations.",
            "News links are unverified metadata only. Article text, author identity, conflicts and opposing coverage have not been verified.",
            "Company research is not account evidence and cannot authorize tools, rank candidates or save a plan.",
        ],
    )


def context_evidence(context):
    """Only dated numerical observations enter the existing evidence/prompt gate."""
    from ..schemas.copilot2 import EvidenceItem

    return [
        EvidenceItem(
            label=f"{row.ticker} {row.metric}",
            value=(f"{row.value * 100:.1f}%" if row.unit == "fraction" else f"{row.value:.2f}x"),
            source="derived" if row.basis == "computed_from_series" else row.source,
            source_type="derived" if row.basis == "computed_from_series" else "secondary",
        )
        for row in context.observations
        if row.status == "available" and row.value is not None
    ]
