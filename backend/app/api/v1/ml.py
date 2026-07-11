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
from ...schemas.envelope import Envelope
from ...schemas.ml import MLHealthOut, MLRegimeOut
from ...schemas.model_card import ModelCardOut
from ...services import ml_health as ml_health_service
from ...services import ml_regime as ml_regime_service
from ...services import model_card as model_card_service

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/ml", tags=["ml"])


@router.get(
    "/regime",
    summary="Trained market-regime risk-state (model, fail-soft)",
    response_model=Envelope[MLRegimeOut],
)
def ml_regime(request: Request):
    started = time.perf_counter()
    snapshot = ml_regime_service.get_regime()
    return ok(MLRegimeOut(**snapshot).model_dump(), request=request, started_at=started)


@router.get(
    "/health",
    summary="Model + drift health (PSI/KS vs training reference)",
    response_model=Envelope[MLHealthOut],
)
def ml_health(request: Request):
    """Read-only: artifact identity, sklearn skew, and per-feature/prediction
    drift vs the training reference. Computed on demand off the cached serving
    frame — a daily GH cron curls this; nothing schedules on the box."""
    started = time.perf_counter()
    snapshot = ml_health_service.get_ml_health()
    return ok(MLHealthOut(**snapshot).model_dump(), request=request, started_at=started)


@router.get(
    "/model_card",
    summary="Public model card — honest metrics from committed artifacts",
    response_model=Envelope[ModelCardOut],
)
def ml_model_card(request: Request):
    """The classifier's model card, read straight from the committed ML
    artifacts (never hand-typed) — provenance, class definitions, features, and
    the honest validation metrics (4-class accuracy vs persistence, elevated-risk
    ROC-AUC, Brier, calibration). Public, deterministic, fail-soft."""
    started = time.perf_counter()
    card = model_card_service.get_model_card()
    return ok(ModelCardOut(**card).model_dump(), request=request, started_at=started)
