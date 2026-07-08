"""Lightweight regime inference: load the committed artifact, predict on the
SAME features used in training (no train/serve skew), derive confidence + top
drivers. Loaded once (singleton); inference is sub-ms. Fail-soft is the caller's
job (services/ml_regime.py falls back to the deterministic heuristic).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from .features import FEATURE_NAMES

_log = logging.getLogger(__name__)

_ARTIFACT_DIR = Path(__file__).parent / "artifacts"
_MODEL_PATH = _ARTIFACT_DIR / "regime_model.joblib"
_META_PATH = _ARTIFACT_DIR / "regime_meta.json"

# Human labels for the top-driver explanation (context, not advice).
_FEATURE_LABELS = {
    "trend_sma200": "S&P 500 vs its 200-day average",
    "trend_sma50": "S&P 500 vs its 50-day average",
    "golden_cross": "50-day vs 200-day average",
    "mom_20d": "1-month momentum",
    "mom_60d": "3-month momentum",
    "vol_21d": "1-month realized volatility",
    "vol_63d": "3-month realized volatility",
    "vol_ratio": "short-vs-long volatility ratio",
    "drawdown": "drawdown from the 1-year peak",
    "vix_level": "VIX level",
    "vix_change_5d": "5-day VIX change",
    "vix_term": "VIX term structure (VIX/VIX3M)",
    "qqq_trend": "Nasdaq-100 trend",
    "qqq_spy_spread": "tech-vs-market momentum spread",
    "yield_slope": "10y–3m Treasury slope",
}

_model: Any = None
_meta: Optional[dict] = None
_load_failed = False


def _load() -> bool:
    """Lazy-load the artifact + metadata once. Returns False if unavailable
    (the model wasn't trained/committed) — caller then falls back."""
    global _model, _meta, _load_failed
    if _model is not None:
        return True
    if _load_failed:
        return False
    try:
        import joblib
        import sklearn

        _meta = json.loads(_META_PATH.read_text())
        _model = joblib.load(_MODEL_PATH)
        trained_with = str((_meta or {}).get("sklearn_version") or "")
        if trained_with and trained_with != sklearn.__version__:
            # Pickled sklearn models aren't guaranteed to load across minor
            # versions — surface the skew rather than trust a silent mismatch.
            _log.warning(
                "ml.inference.sklearn_version_skew trained=%s runtime=%s",
                trained_with,
                sklearn.__version__,
            )
        return True
    except Exception as exc:  # noqa: BLE001 - model is optional; fall back
        _log.warning("ml.inference.load_failed err=%s", type(exc).__name__)
        _load_failed = True
        return False


def reset() -> None:
    """Test hook — drop the cached model/meta."""
    global _model, _meta, _load_failed
    _model, _meta, _load_failed = None, None, False


def is_available() -> bool:
    return _load()


def load_model():
    """The fitted estimator, or None when the artifact can't load (health/
    drift consumers; the request path keeps using predict())."""
    return _model if _load() else None


def model_meta() -> Optional[dict]:
    """The artifact's provenance dict, or None."""
    return dict(_meta) if _load() and _meta else None


def _top_drivers(row: pd.Series, k: int = 4) -> list[dict]:
    """The most globally-important features + this day's value vs the training
    median (above/below normal). Context, NOT a per-prediction attribution."""
    if not _meta:
        return []
    importances = _meta.get("feature_importances") or {}
    medians = _meta.get("feature_medians") or {}
    out: list[dict] = []
    for feat in list(importances.keys())[:k]:
        val = row.get(feat)
        if val is None or pd.isna(val):
            continue
        med = medians.get(feat)
        direction = "above normal" if (med is not None and val > med) else "below normal"
        out.append(
            {
                "feature": feat,
                "label": _FEATURE_LABELS.get(feat, feat),
                "value": round(float(val), 4),
                "vs_normal": direction,
                "importance": importances.get(feat),
            }
        )
    return out


def predict(feature_row: pd.DataFrame) -> dict:
    """Predict the risk-state for a single warmed feature row (1xN). Raises if
    the model is unavailable — the service layer handles the fallback."""
    if not _load():
        raise RuntimeError("regime model unavailable")
    X = feature_row.reindex(columns=FEATURE_NAMES)  # enforce the trained order
    classes = list(_model.classes_)
    proba = _model.predict_proba(X)[0]
    idx = int(proba.argmax())
    return {
        "regime": str(classes[idx]),
        "confidence": round(float(proba[idx]), 4),
        "class_probabilities": {
            str(classes[i]): round(float(proba[i]), 4) for i in range(len(classes))
        },
        "top_drivers": _top_drivers(X.iloc[0]),
        "model_version": (_meta or {}).get("model_version"),
        "trained_at": (_meta or {}).get("trained_at"),
        "training_window": (_meta or {}).get("training_window"),
    }
