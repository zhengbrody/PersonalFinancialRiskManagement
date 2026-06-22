"""``GET /api/v1/ml/regime`` — the trained market-regime risk-STATE classifier.

Public + fail-soft (the service never raises): returns the model's 4-class risk
state with confidence, top drivers, and full provenance (model version, training
window, data coverage). Falls back to a deterministic current-vol heuristic when
the model/artifact is unavailable, or an explicit ``unavailable`` when even the
market data is down. This is market CONTEXT — never advice, never part of the
deterministic Health Score.
"""

from __future__ import annotations

import logging
import time

from fastapi import APIRouter, Request

from ...core.responses import ok
from ...schemas.ml import MLRegimeOut
from ...services import ml_regime as ml_regime_service

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/ml", tags=["ml"])


@router.get("/regime", summary="Trained market-regime risk-state (model, fail-soft)")
def ml_regime(request: Request):
    started = time.perf_counter()
    snapshot = ml_regime_service.get_regime()
    return ok(MLRegimeOut(**snapshot).model_dump(), request=request, started_at=started)
