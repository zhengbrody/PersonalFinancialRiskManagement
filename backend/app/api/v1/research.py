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

from fastapi import APIRouter, Depends, Path, Request

from ...core.deps_auth import AuthedUser, require_user
from ...core.responses import ok, too_many_requests, unprocessable
from ...schemas.news import TickerNewsResponse
from ...schemas.research import FactPack, VerdictRequest
from ...services import news as news_svc
from ...services import research_factpack as rf

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
