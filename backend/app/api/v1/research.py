"""``/api/v1/research/*`` — Ticker Research 2.0 (FactPack + Verdict).

Two stages, mirroring the equity endpoints but built on the compact, source-
attributed FactPack instead of the raw dossier:

* ``GET /research/fact_pack/{ticker}`` — authed, NO credit. Deterministic
  provider+free composition (valuation band, CAGR, drivers, risk flags,
  provenance). Paints the research cockpit instantly.
* ``POST /research/verdict`` — authed + **credit-gated**. The LLM ranks/explains
  over the FactPack the client passes back (no second fetch). Degrades to the
  deterministic verdict with no LLM key. Full AI telemetry recorded post-call.
"""

from __future__ import annotations

import json
import logging
import time

from fastapi import APIRouter, Depends, Path, Query, Request

from ...core.deps_auth import AuthedUser, require_user
from ...core.responses import ok, too_many_requests, unprocessable
from ...schemas.news import TickerNewsResponse
from ...schemas.research import FactPack, VerdictRequest
from ...schemas.valuation import DCFRequest
from ...services import news as news_svc
from ...services import research_dcf as rdcf
from ...services import research_earnings as rearn
from ...services import research_factpack as rf
from ...services import research_financials as rfin
from ...services import research_peers as rpeers
from ...services import research_report as rreport
from ...services import research_thesis as rthesis

router = APIRouter(prefix="/api/v1/research", tags=["research"])

_log = logging.getLogger(__name__)
_VERDICT_MODEL = "claude-sonnet-4-6"


@router.get(
    "/fact_pack/{ticker}",
    summary="Compact, source-attributed FactPack for a ticker (no credit)",
    response_model=None,
)
def fact_pack(
    request: Request,
    ticker: str = Path(min_length=1, max_length=20),
    user: AuthedUser = Depends(require_user),
):
    started = time.perf_counter()
    try:
        fp = rf.build_fact_pack(ticker)
    except ValueError as exc:
        raise unprocessable(str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - fetch/compose failure
        _log.warning("research.factpack.failed ticker=%s err=%s", ticker, type(exc).__name__)
        raise unprocessable(f"Could not build a FactPack for {ticker!r}.") from exc

    return ok({"fact_pack": fp.model_dump()}, request=request, started_at=started)


@router.get(
    "/{ticker}/fact-pack",
    summary="Institutional research FactPack: financials + deterministic trends (no credit)",
    response_model=None,
)
def research_fact_pack(
    request: Request,
    ticker: str = Path(min_length=1, max_length=20),
    user: AuthedUser = Depends(require_user),
):
    """Phase 1 institutional FactPack: company snapshot + up to 8 quarters & 5
    fiscal years of financials + a deterministic trend summary (margins, YoY/QoQ,
    TTM, acceleration flags), with explicit provenance, missing-data, and a
    confidence score. Every number is computed in backend code — no LLM. Builds
    fail-soft (partial pack on provider failure), so this raises only on an
    unexpected internal error."""
    started = time.perf_counter()
    try:
        pack = rfin.build_research_fact_pack(ticker)
    except Exception as exc:  # noqa: BLE001 - builder is fail-soft; this is a backstop
        _log.warning(
            "research.research_factpack.failed ticker=%s err=%s", ticker, type(exc).__name__
        )
        raise unprocessable(f"Could not build a research FactPack for {ticker!r}.") from exc
    return ok({"fact_pack": pack.model_dump()}, request=request, started_at=started)


@router.post(
    "/{ticker}/dcf",
    summary="Deterministic DCF valuation (accepts user overrides; no credit)",
    response_model=None,
)
def dcf_valuation(
    body: DCFRequest,
    request: Request,
    ticker: str = Path(min_length=1, max_length=20),
    user: AuthedUser = Depends(require_user),
):
    """Deterministic DCF — assumptions derived from reported financials (each
    labeled with its source_type) + optional user overrides. Returns the full
    DCFValuationOutput; an invalid setup (e.g. terminal growth ≥ WACC, or
    insufficient data) comes back with `valid=false` + warnings rather than a
    bogus number. No LLM, no credit, fail-soft."""
    started = time.perf_counter()
    try:
        out = rdcf.build_dcf(ticker, body.overrides if body else None)
    except Exception as exc:  # noqa: BLE001 - builder is fail-soft; backstop
        _log.warning("research.dcf.failed ticker=%s err=%s", ticker, type(exc).__name__)
        raise unprocessable(f"Could not build a DCF for {ticker!r}.") from exc
    return ok({"dcf": out.model_dump()}, request=request, started_at=started)


@router.get(
    "/{ticker}/peers",
    summary="Deterministic peer comparison with percentiles (no credit)",
    response_model=None,
)
def peer_comparison(
    request: Request,
    ticker: str = Path(min_length=1, max_length=20),
    peers: str | None = Query(default=None, description="Optional comma-separated user peers"),
    user: AuthedUser = Depends(require_user),
):
    """Deterministic peer set (FMP peers → sector/industry → curated → user) with
    per-metric peer median + the subject's percentile rank, missing-data flags,
    and provenance. No LLM, no credit, fail-soft."""
    started = time.perf_counter()
    user_peers = [p.strip().upper() for p in peers.split(",") if p.strip()] if peers else None
    try:
        out = rpeers.build_peer_comparison(ticker, user_peers=user_peers)
    except Exception as exc:  # noqa: BLE001 - fail-soft backstop
        _log.warning("research.peers.failed ticker=%s err=%s", ticker, type(exc).__name__)
        raise unprocessable(f"Could not build a peer comparison for {ticker!r}.") from exc
    return ok({"peers": out.model_dump()}, request=request, started_at=started)


@router.get(
    "/{ticker}/earnings",
    summary="Deterministic earnings comparison + transcript metadata (no credit)",
    response_model=None,
)
def earnings_comparison(
    request: Request,
    ticker: str = Path(min_length=1, max_length=20),
    user: AuthedUser = Depends(require_user),
):
    """Recent quarters: revenue/EPS vs prior-quarter / prior-year, beat/miss vs
    estimate ONLY when estimate data exists, plus transcript metadata. Missing
    estimates/transcript are explicit. No LLM, no credit, fail-soft."""
    started = time.perf_counter()
    try:
        out = rearn.build_earnings_comparison(ticker)
    except Exception as exc:  # noqa: BLE001 - fail-soft backstop
        _log.warning("research.earnings.failed ticker=%s err=%s", ticker, type(exc).__name__)
        raise unprocessable(f"Could not build an earnings comparison for {ticker!r}.") from exc
    return ok({"earnings": out.model_dump()}, request=request, started_at=started)


@router.get(
    "/{ticker}/report",
    summary="Institutional analyst HTML report — all sections, deterministic (no credit)",
    response_model=None,
)
def analyst_report(
    request: Request,
    ticker: str = Path(min_length=1, max_length=20),
    user: AuthedUser = Depends(require_user),
):
    """Self-contained, PDF-ready HTML research report assembled server-side from
    the deterministic engines (snapshot, exec summary, financials, DCF + scenario,
    peers, earnings, risks, monitoring, provenance appendix, disclaimer). No
    recomputation in the frontend, no LLM number. Fail-soft per section."""
    started = time.perf_counter()
    try:
        out = rreport.build_analyst_report(ticker)
    except Exception as exc:  # noqa: BLE001 - fail-soft backstop
        _log.warning("research.report.failed ticker=%s err=%s", ticker, type(exc).__name__)
        raise unprocessable(f"Could not build a report for {ticker!r}.") from exc
    return ok({"report": out.model_dump()}, request=request, started_at=started)


@router.post(
    "/{ticker}/thesis",
    summary="AI-grounded bull/bear/monitor thesis over deterministic evidence (credit-gated)",
    response_model=None,
)
def research_thesis(
    request: Request,
    ticker: str = Path(min_length=1, max_length=20),
    user: AuthedUser = Depends(require_user),
):
    """Bull/bear debate + what-to-monitor + management questions, written by the
    LLM over the deterministic FactPack/DCF/earnings evidence ONLY (no invented
    numbers — validated + flagged; no buy/sell/hold). No LLM key / failure →
    deterministic fallback. Credit-gated; cache hit is free."""
    started = time.perf_counter()
    tk = ticker.strip().upper()

    from ...services.ai_cache import verdict_cache
    from ...services.ai_telemetry import input_hash

    cache_key = input_hash(f"thesis:{tk}")
    cached = verdict_cache.get(cache_key)
    if cached is not None:
        return ok({"thesis": cached}, request=request, started_at=started)

    from ...services.llm_client import get_llm_callable

    llm = get_llm_callable(with_tools=False)
    if llm is not None:
        from libs.billing.usage import ESTIMATED_COST_USD, QuotaExceeded, check_credits

        try:
            check_credits(
                user.id, email=user.email, estimated_cost_usd=ESTIMATED_COST_USD["analysis"]
            )
        except QuotaExceeded as exc:
            raise too_many_requests(str(exc)) from exc
        except Exception as exc:  # noqa: BLE001 - fail-open on a metering blip
            _log.warning("research.thesis.credit_check_failed reason=%s", type(exc).__name__)

    try:
        out = rthesis.build_thesis(tk, llm_callable=llm)
    except Exception as exc:  # noqa: BLE001 - builder is fail-soft; backstop
        _log.warning("research.thesis.failed ticker=%s err=%s", tk, type(exc).__name__)
        raise unprocessable(f"Could not build a thesis for {tk!r}.") from exc

    if llm is not None and out.ai_generated:
        _record_thesis_cost(user.id, out, started, input_hash_value=cache_key)
        verdict_cache.put(cache_key, out.model_dump())
    return ok({"thesis": out.model_dump()}, request=request, started_at=started)


def _record_thesis_cost(user_id: str, thesis, started: float, *, input_hash_value: str) -> None:
    from libs.billing.costs import estimate_tokens

    from ...services.ai_telemetry import record_ai_call

    body = json.dumps(thesis.model_dump(), default=str)
    record_ai_call(
        user_id,
        "analysis",
        model=_VERDICT_MODEL,
        tokens_in=1500,  # evidence + system prompt (rough)
        tokens_out=estimate_tokens(body),
        latency_ms=(time.perf_counter() - started) * 1000,
        input_hash=input_hash_value,
    )


@router.get(
    "/news/{ticker}",
    summary="Unified, source-labeled news for a ticker (FMP news + press releases + SEC), no credit",
    response_model=None,
)
def ticker_news(
    request: Request,
    ticker: str = Path(min_length=1, max_length=20),
    user: AuthedUser = Depends(require_user),
):
    """Combine FMP stock news + press releases (primary) with a SEC filings link,
    deduped + classified + source-labeled. Fail-soft — never 500s, always returns
    at least the SEC entry."""
    started = time.perf_counter()
    data = news_svc.get_ticker_news(ticker)
    payload = TickerNewsResponse.model_validate(data).model_dump()
    return ok(payload, request=request, started_at=started)


@router.post(
    "/verdict",
    summary="LLM verdict over a FactPack (credit-gated)",
    response_model=None,
)
def verdict(
    body: VerdictRequest,
    request: Request,
    user: AuthedUser = Depends(require_user),
):
    started = time.perf_counter()

    if not body.ticker and not body.fact_pack:
        raise unprocessable("Provide either `ticker` or a `fact_pack`.")

    # Prefer the FactPack the client already fetched (no second network hit).
    if body.fact_pack is not None:
        fp: FactPack = body.fact_pack
    else:
        try:
            fp = rf.build_fact_pack(str(body.ticker))
        except ValueError as exc:
            raise unprocessable(str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            _log.warning("research.verdict.factpack_failed err=%s", type(exc).__name__)
            raise unprocessable(f"Could not build a FactPack for {body.ticker!r}.") from exc

    # ── Response cache (input-hash, 45 min). A repeat verdict over the same
    # FactPack costs nothing — return it before the credit gate so a cache
    # hit never burns credits. The FactPack carries no user data, so the
    # cache is safely shared across users researching the same ticker.
    from ...services.ai_cache import verdict_cache
    from ...services.ai_telemetry import input_hash

    fp_json = json.dumps(fp.model_dump(), default=str, sort_keys=True)
    cache_key = input_hash(fp_json)
    cached = verdict_cache.get(cache_key)
    if cached is not None:
        return ok(
            {"verdict": cached, "fact_pack": fp.model_dump()},
            request=request,
            started_at=started,
        )

    # ── Credit gate (LLM). Out of credits → 429; metering blip → fail-open. ──
    from libs.billing.usage import ESTIMATED_COST_USD, QuotaExceeded, check_credits

    try:
        check_credits(user.id, email=user.email, estimated_cost_usd=ESTIMATED_COST_USD["analysis"])
    except QuotaExceeded as exc:
        raise too_many_requests(str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        _log.warning("research.verdict.credit_check_failed reason=%s", type(exc).__name__)

    from ...services.llm_client import get_llm_callable

    llm = get_llm_callable(with_tools=False)
    result = rf.build_verdict(fp, llm_callable=llm)

    # Record ACTUAL cost + full telemetry — only when a real model ran.
    if llm is not None and not result.data_only:
        _record_verdict_cost(user.id, fp, result, started)
        verdict_cache.put(cache_key, result.model_dump())

    return ok(
        {"verdict": result.model_dump(), "fact_pack": fp.model_dump()},
        request=request,
        started_at=started,
    )


def _record_verdict_cost(user_id: str, fp: FactPack, verdict, started: float) -> None:
    from libs.billing.costs import estimate_tokens

    from ...services.ai_telemetry import input_hash, record_ai_call

    fp_json = json.dumps(fp.model_dump(), default=str, sort_keys=True)
    tokens_in = estimate_tokens(fp_json) + 700  # + system prompt
    tokens_out = estimate_tokens(json.dumps(verdict.model_dump(), default=str))
    record_ai_call(
        user_id,
        "analysis",
        model=_VERDICT_MODEL,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        latency_ms=(time.perf_counter() - started) * 1000,
        input_hash=input_hash(fp_json),
    )
