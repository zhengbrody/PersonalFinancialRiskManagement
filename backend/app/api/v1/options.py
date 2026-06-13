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
    OptionScenarioRequest,
    OptionScenarioResponse,
)
from ...services import options_analytics, options_exposure, options_scenarios

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
    # Portfolio-level exposure + deterministic risk flags over the same results.
    data["exposure"] = options_exposure.build_exposure(data.get("results", []))
    # Validate/normalise through the response schema before enveloping.
    payload = OptionAnalyzeResponse.model_validate(data).model_dump()
    return ok(payload, request=request, started_at=started)


@router.post(
    "/scenarios",
    summary="Black-Scholes stress grid (underlying × IV × time) for option contracts",
    response_model=None,
)
def option_scenarios_endpoint(
    body: OptionScenarioRequest,
    request: Request,
    user: AuthedUser = Depends(require_user),
):
    """Full-reprice option stress grid + the top-5 impacted positions. Deterministic,
    credit-free; captures gamma/vega/theta that the equity report's delta overlay
    can't. Each contract is priced from its live analytics, then repriced across the
    shock axes."""
    started = time.perf_counter()
    analytics = options_analytics.analyze_contracts(
        body.contracts, risk_free_rate=body.risk_free_rate
    )
    grid = options_scenarios.scenario_grid(
        analytics.get("results", []), risk_free_rate=body.risk_free_rate
    )
    grid["as_of"] = analytics.get("as_of")
    payload = OptionScenarioResponse.model_validate(grid).model_dump()
    return ok(payload, request=request, started_at=started)
