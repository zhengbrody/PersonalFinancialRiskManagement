"""``GET /api/v1/regime/summary`` — the composed, plain-language market
risk-state readout (model + VIX/F&G/curve) that powers the public /risk-today
page and a quotable social ``post_text``.

Public + fail-soft (the underlying services never raise). Deterministic — no LLM.
Reuses the already-cached ml_regime + market_regime services, so it's cheap to
fetch on an SSR page that revalidates every ~30 min.
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Request

from ...core.responses import ok
from ...schemas.envelope import Envelope
from ...schemas.regime_summary import RegimeSummaryOut
from ...services import regime_summary as regime_summary_service

router = APIRouter(prefix="/api/v1/regime", tags=["regime"])


@router.get(
    "/summary",
    summary="Composed market risk-state readout + social post_text",
    response_model=Envelope[RegimeSummaryOut],
)
def regime_summary(request: Request):
    started = time.perf_counter()
    payload = regime_summary_service.get_regime_summary()
    return ok(RegimeSummaryOut(**payload).model_dump(), request=request, started_at=started)
