"""ML health + drift status — the serving-side consumer of monitoring.py.

Same contract family as ml_regime.py: in-process 10-minute cache, fail-soft
tiers, never raises into a request. Computation is on demand (a GH cron
curls the endpoint daily); there is no resident scheduler on the 916MB box —
see docs/adr/0005-ml-drift-monitoring-scheduling.md.

Tiers:
* ok           — artifact + reference + market data all present; drift computed
* not_ready    — regime_reference.json absent (train hasn't produced one yet)
* unavailable  — market data or the model artifact is down

On an overall drift breach the service emits ONE structured warning + Sentry
message per cache period (the cache is the throttle), and only on the
healthy→(watch|drift) transition, so a stuck-red state can't spam.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Optional

from ..ml import data as ml_data
from ..ml import inference as ml_inference
from ..ml import monitoring as ml_monitoring
from ..ml.features import FEATURE_NAMES, WARMUP_REQUIRED, build_feature_frame

_log = logging.getLogger(__name__)

REFERENCE_PATH = Path(__file__).resolve().parents[1] / "ml" / "artifacts" / "regime_reference.json"

_CACHE_TTL = 600.0  # matches ml_regime's serving cache
_LIVE_WINDOW = 120  # recent trading days compared against the reference
_FETCH_YEARS = 1.75  # same warmup-covering window the regime service uses

_cache: dict[str, Any] = {}


def reset_cache() -> None:
    _cache.clear()


def _load_reference() -> Optional[dict[str, Any]]:
    try:
        if not REFERENCE_PATH.exists():
            return None
        return json.loads(REFERENCE_PATH.read_text())
    except Exception as exc:  # noqa: BLE001 - a bad file is "not ready", not a 500
        _log.warning("ml.health.reference_unreadable err=%s", type(exc).__name__)
        return None


def _base(status: str, note: Optional[str] = None) -> dict[str, Any]:
    meta = ml_inference.model_meta() or {}
    import sklearn

    return {
        "status": status,
        "model_version": meta.get("model_version"),
        "trained_at": meta.get("trained_at"),
        "artifact_loaded": bool(meta),
        "sklearn_runtime": sklearn.__version__,
        "sklearn_trained": meta.get("sklearn_version"),
        "sklearn_match": (meta.get("sklearn_version") == sklearn.__version__) if meta else None,
        "reference": None,
        "features": {},
        "prediction": None,
        "overall_status": None,
        "data_as_of": None,
        "live_window_days": _LIVE_WINDOW,
        "note": note,
        "last_updated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def get_ml_health(*, force_refresh: bool = False, fetcher=ml_data._yf_close) -> dict[str, Any]:
    now = time.time()
    if not force_refresh and _cache.get("at", 0) + _CACHE_TTL > now:
        return _cache["snapshot"]

    reference = _load_reference()
    if reference is None:
        snap = _base(
            "not_ready",
            "regime_reference.json not found — produced by the next training run "
            "(python -m backend.app.ml.train).",
        )
        _cache.update(at=now, snapshot=snap)
        return snap

    model = ml_inference.load_model()
    if model is None:
        snap = _base("unavailable", "model artifact failed to load")
        _cache.update(at=now, snapshot=snap)
        return snap

    try:
        raw = ml_data.fetch_history(years=_FETCH_YEARS, fetcher=fetcher)
        frame = build_feature_frame(raw).dropna(subset=WARMUP_REQUIRED)
        live = frame[FEATURE_NAMES].tail(_LIVE_WINDOW)
        if live.empty:
            raise ValueError("no live feature rows after warmup")
    except Exception as exc:  # noqa: BLE001
        _log.warning("ml.health.data_unavailable err=%s", type(exc).__name__)
        snap = _base("unavailable", "market data unavailable for drift computation")
        _cache.update(at=now, snapshot=snap)
        return snap

    drift = ml_monitoring.evaluate_drift(live, model, reference)
    snap = _base("ok")
    snap.update(
        {
            "reference": {
                "model_version": reference.get("model_version"),
                "rows": reference.get("rows"),
                "features": len(reference.get("features") or {}),
            },
            "features": drift["features"],
            "prediction": drift["prediction"],
            "overall_status": drift["overall_status"],
            "data_as_of": str(live.index[-1].date()),
        }
    )

    _maybe_alert(previous=_cache.get("snapshot"), current=snap)
    _cache.update(at=now, snapshot=snap)
    return snap


def _maybe_alert(*, previous: Optional[dict[str, Any]], current: dict[str, Any]) -> None:
    """Structured log + Sentry, only on the transition INTO watch/drift —
    the cache period is the natural throttle."""
    curr = current.get("overall_status")
    prev = (previous or {}).get("overall_status")
    if curr in ("watch", "drift") and curr != prev:
        worst = [
            name for name, d in (current.get("features") or {}).items() if d.get("status") == curr
        ]
        _log.warning(
            "ml.health.drift_detected status=%s features=%s model=%s",
            curr,
            worst,
            current.get("model_version"),
        )
        try:
            import sentry_sdk

            sentry_sdk.capture_message(
                f"ML drift {curr}: features={worst} model={current.get('model_version')}",
                level="warning",
            )
        except Exception:  # noqa: BLE001 - alerting must never break health
            pass
