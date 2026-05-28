"""``POST /api/v1/equity/deep_analysis`` — single-name research view.

Public for now (Phase 1) so the frontend can fetch a deep-analysis
payload from a ticker without round-tripping a session. We DO NOT
run the LLM by default — the placeholder ``DeepAnalysis`` returned
when ``llm_callable=None`` is enough to drive the dashboard skeleton
during the migration. A future Phase 4 will accept the user's JWT
and route LLM calls through the billing layer.

The endpoint takes EITHER a ticker (and pulls the dossier server-side
via the existing ``market_intelligence.fetch_ticker_research`` chain)
OR an inline dossier (so tests + offline demos don't need network).
"""

from __future__ import annotations

import time
from typing import Any, Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from ...core.responses import ok, unprocessable

router = APIRouter(prefix="/api/v1/equity", tags=["equity"])


class DeepAnalysisRequest(BaseModel):
    ticker: Optional[str] = Field(default=None, min_length=1, max_length=20)
    fmp_key: Optional[str] = Field(
        default=None,
        description="Pass-through FMP key for the dossier fetch. Optional.",
    )
    dossier_override: Optional[dict[str, Any]] = Field(
        default=None,
        description=(
            "When supplied, the endpoint SKIPS the network dossier fetch and "
            "uses this dict verbatim. Lets tests + offline clients exercise "
            "the analysis without yfinance / FMP."
        ),
    )


@router.post(
    "/deep_analysis",
    summary="Run the single-name equity analyst (no LLM in Phase 1)",
    response_model=None,
)
def deep_analysis(body: DeepAnalysisRequest, request: Request):
    """Return the deterministic ``DeepAnalysis`` placeholder for the
    requested ticker / dossier.

    Phase 1 does NOT invoke the LLM: it returns the placeholder
    analysis (HOLD / low confidence) so the frontend can wire the
    dashboard before we plumb billing-aware LLM routing. The placeholder
    is the same one the equity module emits when its ``llm_callable``
    argument is None — see ``libs.analysis.equity_research``.
    """
    started = time.perf_counter()

    if not body.ticker and not body.dossier_override:
        raise unprocessable("Provide either `ticker` or `dossier_override`.")

    from libs.analysis.equity_research import analyze_equity, build_company_dossier

    if body.dossier_override is not None:
        dossier = body.dossier_override
    else:
        try:
            dossier = build_company_dossier(str(body.ticker), fmp_key=body.fmp_key or "")
        except Exception as exc:
            raise unprocessable(f"Dossier fetch failed: {exc}")

    # llm_callable=None → DeepAnalysis returns the data-only placeholder.
    analysis = analyze_equity(dossier, llm_callable=None)

    return ok(
        {
            "dossier": dossier,
            "analysis": analysis.model_dump(),
        },
        request=request,
        started_at=started,
    )
