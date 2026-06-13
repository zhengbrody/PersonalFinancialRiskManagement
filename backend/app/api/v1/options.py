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
from ...schemas.options import OptionAnalyzeRequest, OptionAnalyzeResponse
from ...services import options_analytics

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
    # Validate/normalise through the response schema before enveloping.
    payload = OptionAnalyzeResponse.model_validate(data).model_dump()
    return ok(payload, request=request, started_at=started)
