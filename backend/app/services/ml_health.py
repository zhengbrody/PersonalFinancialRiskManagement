"""ML health + drift status — the serving-side consumer of monitoring.py.

Same contract family as ml_regime.py: in-process 10-minute cache, fail-soft
tiers, never raises into a request. Computation is on demand (a GH cron
curls the endpoint daily); there is no resident scheduler on the 916MB box —
see docs/adr/0005-ml-drift-monitoring-scheduling.md.

Tiers:
* ok           — artifact + reference + market data all present; drift computed
* not_ready    — regime_reference.json absent (train hasn't produced one yet)
* unavailable  — market data or the model artifact is down

Additive provenance fields (never change ``status``/``overall_status``):
* freshness          — model age vs ``MINDMARKET_ML_STALE_DAYS`` (default 21);
                       fresh | stale | unknown. A stale model can be
                       drift-healthy, so it is reported on its own axis.
* approved_artifact  — sha256 of the bytes the serving model was loaded from vs
                       the hash recorded by the delivery pipeline
                       (regime_provenance.json, else meta.artifact_sha256).
                       ``match`` is None when no approved hash was recorded —
                       unknown, never assumed true.
The last TRAINING PIPELINE result is not knowable from the box; only what the
committed provenance record says about the run that produced THIS artifact is
exposed. The scheduled ml-health workflow checks the latest train run itself.

Alerting: ONE structured warning + Sentry message, only when a KNOWN overall
status worsens (healthy→watch|drift, watch→drift), throttled by the cache
period. A process restart or a data blip resets `previous` to unknown — the
next computation then logs at info instead of re-alerting, so deploys and
outages don't re-fire a standing condition.
"""

from __future__ import annotations

import json
import logging
import math
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from ..core.config import get_settings
from ..ml import data as ml_data
from ..ml import inference as ml_inference
from ..ml import monitoring as ml_monitoring
from ..ml.features import FEATURE_NAMES, WARMUP_REQUIRED, build_feature_frame

_log = logging.getLogger(__name__)

REFERENCE_PATH = Path(__file__).resolve().parents[1] / "ml" / "artifacts" / "regime_reference.json"
PROVENANCE_PATH = (
    Path(__file__).resolve().parents[1] / "ml" / "artifacts" / "regime_provenance.json"
)
_MODEL_FILENAME = "regime_model.joblib"
DEFAULT_STALE_DAYS = 21.0

_CACHE_TTL = 600.0  # matches ml_regime's serving cache
# The live window MUST equal the calibration window baked into the reference —
# the slice-PSI percentiles are the null for windows of exactly this length.
_LIVE_WINDOW = ml_monitoring.LIVE_WINDOW
_FETCH_YEARS = ml_data.SERVE_YEARS  # shared with ml_regime → one cached fetch

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


def _stale_threshold_days() -> float:
    try:
        days = float(get_settings().ml_model_stale_days)
    except Exception:  # noqa: BLE001 - a bad knob must not break health
        return DEFAULT_STALE_DAYS
    # Non-positive / non-finite would make every model stale (or none): ignore.
    return days if math.isfinite(days) and days > 0 else DEFAULT_STALE_DAYS


def _parse_ts(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value:
        return None
    try:
        ts = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def freshness(trained_at: Any, *, now: Optional[datetime] = None) -> dict[str, Any]:
    """Model age vs the staleness threshold. Missing/unparseable trained_at or
    a trained_at in the future is ``unknown`` — never silently fresh."""
    threshold = _stale_threshold_days()
    out: dict[str, Any] = {
        "status": "unknown",
        "age_days": None,
        "threshold_days": threshold,
        "trained_at": trained_at if isinstance(trained_at, str) else None,
    }
    ts = _parse_ts(trained_at)
    if ts is None:
        return out
    age = ((now or datetime.now(timezone.utc)) - ts).total_seconds() / 86400.0
    if age < 0:
        return out
    out["age_days"] = round(age, 2)
    out["status"] = "stale" if age > threshold else "fresh"
    return out


def _load_provenance() -> Optional[dict[str, Any]]:
    try:
        if not PROVENANCE_PATH.exists():
            return None
        data = json.loads(PROVENANCE_PATH.read_text())
        return data if isinstance(data, dict) else None
    except Exception as exc:  # noqa: BLE001 - unreadable record = no record
        _log.warning("ml.health.provenance_unreadable err=%s", type(exc).__name__)
        return None


def approved_artifact(
    meta: dict[str, Any],
    loaded_sha256: Optional[str],
    provenance: Optional[dict[str, Any]],
) -> dict[str, Any]:
    """Serving-model identity vs the approved hash. The pipeline's provenance
    record wins over meta (it is written AFTER every gate passed); meta's own
    artifact_sha256 is the fallback for artifacts trained before provenance
    existed. No recorded hash → match None (unknown), never True."""
    approved: Optional[str] = None
    source: Optional[str] = None
    prov_hash = ((provenance or {}).get("artifacts") or {}).get(_MODEL_FILENAME)
    meta_hash = (meta.get("artifact_sha256") or {}).get("model")
    if isinstance(prov_hash, str) and prov_hash:
        approved, source = prov_hash, "provenance"
    elif isinstance(meta_hash, str) and meta_hash:
        approved, source = meta_hash, "meta"
    match = None if (approved is None or loaded_sha256 is None) else loaded_sha256 == approved

    record = None
    if provenance:
        gates = provenance.get("gates") or {}
        record = {
            "source_commit": provenance.get("source_commit"),
            "run_id": provenance.get("run_id"),
            "run_url": provenance.get("run_url"),
            "recorded_at": provenance.get("recorded_at"),
            "gates_passed": gates.get("passed") if isinstance(gates, dict) else None,
            "gates": (gates.get("checks") or {}) if isinstance(gates, dict) else {},
            # The record must describe THIS model, not a previous retrain.
            "matches_meta": (
                (
                    provenance.get("trained_at") == meta.get("trained_at")
                    and provenance.get("model_version") == meta.get("model_version")
                )
                if meta
                else None
            ),
        }
    return {
        "loaded_sha256": loaded_sha256,
        "approved_sha256": approved,
        "approved_source": source,
        "match": match,
        "provenance": record,
    }


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
        "freshness": freshness(meta.get("trained_at")),
        "approved_artifact": approved_artifact(
            meta, ml_inference.loaded_model_sha256() if meta else None, _load_provenance()
        ),
    }


def get_ml_health(*, force_refresh: bool = False, fetcher=None) -> dict[str, Any]:
    # Wall-clock, NOT monotonic: the empty-cache guard relies on the `at`
    # default (0) being far in the past, which holds for time.time() (~1.7e9)
    # but not for monotonic() (small on a fresh process → would falsely report
    # a hit and KeyError on the absent "snapshot").
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
        # Shared with ml_regime via the process-wide serve cache — one yfinance
        # burst covers both services within the TTL.
        raw = ml_data.fetch_history_cached(years=_FETCH_YEARS, fetcher=fetcher)
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
    snap = _base(
        "ok",
        (
            None
            if drift["overall_status"] is not None
            else "live data insufficient for any drift verdict"
        ),
    )
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


_RANK = {s: i for i, s in enumerate(ml_monitoring.STATUS_ORDER)}  # one source of the ordering


def _maybe_alert(*, previous: Optional[dict[str, Any]], current: dict[str, Any]) -> None:
    """Structured log + Sentry, only when a KNOWN status worsens — the cache
    period is the natural throttle. An unknown `previous` (process restart,
    prior tier not ok) logs info instead of alerting: a deploy or a transient
    data outage must not re-fire a standing condition."""
    curr = current.get("overall_status")
    prev = (previous or {}).get("overall_status")
    if curr not in _RANK:
        return
    if prev not in _RANK:
        if curr != "healthy":
            _log.info("ml.health.status_on_first_computation status=%s", curr)
        return
    if _RANK[curr] <= _RANK[prev]:
        return
    worst = [name for name, d in (current.get("features") or {}).items() if d.get("status") == curr]
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
