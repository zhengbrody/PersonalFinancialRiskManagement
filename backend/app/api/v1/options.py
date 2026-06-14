"""``POST /api/v1/options/analyze`` — option-contract analytics.

Authed, deterministic, **credit-free** (no LLM): prices the supplied option
contracts off free yfinance chains and returns Black-Scholes Greeks / IV / mark
/ at-expiry payoff + a portfolio-level Greeks roll-up. Thin by design — the
route validates the body, then delegates to ``services.options_analytics``,
which fail-softs per contract so one bad contract never sinks the batch.
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends, Request

from ...core.deps_auth import AuthedUser, require_user
from ...core.responses import ok
from ...schemas.options import (
    OptionAnalyzeRequest,
    OptionAnalyzeResponse,
    OptionExplainInput,
)
from ...services import (
    options_analytics,
    options_explain,
    options_exposure,
    options_scenarios,
)

router = APIRouter(prefix="/api/v1/options", tags=["options"])


@router.post(
    "/analyze",
    summary="Black-Scholes Greeks / IV / payoff for a set of option contracts",
    response_model=None,  # we wrap the response in the envelope ourselves
)
def analyze_options_endpoint(
    body: OptionAnalyzeRequest,
    request: Request,
    user: AuthedUser = Depends(require_user),
):
    """Return per-contract analytics + a portfolio Greeks roll-up. Auth-gated
    (so anonymous scraping can't hammer yfinance), but no credit cost — every
    number is deterministic math over market data."""
    started = time.perf_counter()
    data = options_analytics.analyze_contracts(body.contracts, risk_free_rate=body.risk_free_rate)
    results = data.get("results", [])
    # Portfolio-level exposure + the BS stress grid, both over the SAME analyzed
    # results — so the cockpit gets exposure + scenarios from ONE call (no second
    # yfinance chain fetch). The grid captures gamma/vega/theta the equity
    # report's delta overlay can't.
    data["exposure"] = options_exposure.build_exposure(results)
    data["scenarios"] = options_scenarios.scenario_grid(results, risk_free_rate=body.risk_free_rate)
    data["scenarios"]["as_of"] = data.get("as_of")
    payload = OptionAnalyzeResponse.model_validate(data).model_dump()
    return ok(payload, request=request, started_at=started)


@router.post(
    "/explain",
    summary="Plain-language explanation of the option book's risk (deterministic skeleton → LLM)",
    response_model=None,
)
def option_explain_endpoint(
    body: OptionExplainInput,
    request: Request,
    user: AuthedUser = Depends(require_user),
):
    """Explain the option exposure: a deterministic skeleton (severity, primary
    driver, educational inspection actions) the LLM may only rephrase — it never
    invents numbers or changes severity/actions. FREE (no credit gate); cost is
    logged. Cached by input hash so identical exposure skips the LLM."""
    import json

    from ...services.ai_cache import explain_cache
    from ...services.ai_telemetry import input_hash
    from ...services.llm_client import get_llm_callable

    started = time.perf_counter()
    cache_key = "opt:" + input_hash(json.dumps(body.model_dump(), default=str, sort_keys=True))
    cached = explain_cache.get(cache_key)
    if cached is not None:
        return ok(cached, request=request, started_at=started)

    llm = get_llm_callable(with_tools=False)
    out = options_explain.explain(body, llm_callable=llm)
    if out.ai_generated:
        explain_cache.put(cache_key, out.model_dump())
    return ok(out.model_dump(), request=request, started_at=started)
