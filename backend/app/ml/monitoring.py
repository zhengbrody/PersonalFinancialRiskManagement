"""Drift monitoring math for the regime pipeline — pure functions, no I/O.

Reference = the TRAINING distribution, persisted by train.py as
``artifacts/regime_reference.json``: per feature a 201-point quantile grid
(0.5% steps), plus the class fractions the trained model predicted over its
own training window. Live = the serving feature frame's recent window.

Two complementary detectors per feature:

* **PSI** (population stability index) over the reference DECILE bins — the
  industry drift staple. Because bin edges ARE reference deciles, the
  expected fraction is exactly 0.10 per bin. Bands: <0.10 healthy,
  0.10–0.25 watch, ≥0.25 drift.
* **One-sample KS** against the reference CDF (interpolated from the
  quantile grid, treated as fixed — standard monitoring practice; the
  p-value is approximate to the extent the grid discretizes the CDF).

Prediction drift: PSI of the recent predicted-class mix vs the training-time
predicted mix (4 categories, expected = reference fractions).
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import numpy as np
import pandas as pd
from scipy.stats import kstest

from .features import FEATURE_NAMES

_log = logging.getLogger(__name__)

QUANTILE_GRID = np.round(np.linspace(0.0, 1.0, 201), 4)  # 0.5% steps
PSI_WATCH = 0.10
PSI_DRIFT = 0.25
MIN_LIVE_OBS = 30  # fewer live points than this → "insufficient", not a verdict
_EPS = 1e-6


# ── reference construction (train side) ───────────────────────────────


def build_reference(X: pd.DataFrame, model: Any, *, model_version: str) -> dict[str, Any]:
    """Training-distribution snapshot for later drift comparison."""
    feats: dict[str, Any] = {}
    for name in FEATURE_NAMES:
        col = X[name].dropna()
        if len(col) < 50:
            continue  # a mostly-NaN optional feature can't anchor a reference
        feats[name] = {
            "n": int(len(col)),
            "quantile_values": [round(float(v), 8) for v in np.quantile(col, QUANTILE_GRID)],
        }
    pred = pd.Series(model.predict(X)).value_counts(normalize=True)
    return {
        "model_version": model_version,
        "rows": int(len(X)),
        "features": feats,
        "predicted_class_fractions": {str(k): round(float(v), 6) for k, v in pred.items()},
    }


# ── drift metrics ─────────────────────────────────────────────────────


def psi_from_fractions(observed: np.ndarray, expected: np.ndarray) -> float:
    """PSI = Σ (obs−exp)·ln(obs/exp), epsilon-guarded."""
    obs = np.clip(np.asarray(observed, dtype=float), _EPS, None)
    exp = np.clip(np.asarray(expected, dtype=float), _EPS, None)
    obs = obs / obs.sum()
    exp = exp / exp.sum()
    return round(float(np.sum((obs - exp) * np.log(obs / exp))), 4)


def _status_for_psi(psi: float) -> str:
    if psi >= PSI_DRIFT:
        return "drift"
    if psi >= PSI_WATCH:
        return "watch"
    return "healthy"


def feature_drift(live: pd.Series, ref: dict[str, Any]) -> dict[str, Any]:
    """One feature's verdict vs its reference quantile grid."""
    vals = live.dropna().to_numpy(dtype=float)
    q = np.asarray(ref["quantile_values"], dtype=float)
    if len(vals) < MIN_LIVE_OBS:
        return {
            "psi": None,
            "ks_stat": None,
            "ks_p": None,
            "n": int(len(vals)),
            "status": "insufficient",
        }

    # PSI over reference deciles (expected = exactly 0.10 per bin).
    decile_edges = q[::20]  # 0, .1, …, 1.0 of the 201-point grid
    inner = decile_edges[1:-1]
    counts = np.histogram(vals, bins=np.concatenate(([-np.inf], inner, [np.inf])))[0]
    psi = psi_from_fractions(counts / len(vals), np.full(10, 0.1))

    # One-sample KS vs the reference CDF (monotone interp over the grid).
    q_mono = np.maximum.accumulate(q)

    def ref_cdf(x: np.ndarray) -> np.ndarray:
        return np.interp(x, q_mono, QUANTILE_GRID, left=0.0, right=1.0)

    try:
        ks = kstest(vals, ref_cdf)
        ks_stat, ks_p = round(float(ks.statistic), 4), round(float(ks.pvalue), 6)
    except Exception as exc:  # noqa: BLE001 - a metric must never sink health
        _log.warning("ml.monitoring.ks_failed err=%s", type(exc).__name__)
        ks_stat, ks_p = None, None

    return {
        "psi": psi,
        "ks_stat": ks_stat,
        "ks_p": ks_p,
        "n": int(len(vals)),
        "status": _status_for_psi(psi),
    }


def prediction_drift(
    frame: pd.DataFrame, model: Any, ref_fractions: dict[str, float]
) -> Optional[dict[str, Any]]:
    """PSI of the recent predicted-class mix vs the training-time mix."""
    try:
        usable = frame.dropna(how="all")
        if len(usable) < MIN_LIVE_OBS or not ref_fractions:
            return None
        pred = pd.Series(model.predict(usable[FEATURE_NAMES]))
        live_frac = pred.value_counts(normalize=True)
        classes = sorted(set(ref_fractions) | set(live_frac.index.astype(str)))
        obs = np.array([float(live_frac.get(c, 0.0)) for c in classes])
        exp = np.array([float(ref_fractions.get(c, 0.0)) for c in classes])
        psi = psi_from_fractions(obs, exp)
        return {
            "psi": psi,
            "status": _status_for_psi(psi),
            "n": int(len(pred)),
            "live_fractions": {c: round(float(live_frac.get(c, 0.0)), 4) for c in classes},
        }
    except Exception as exc:  # noqa: BLE001
        _log.warning("ml.monitoring.prediction_drift_failed err=%s", type(exc).__name__)
        return None


def evaluate_drift(frame: pd.DataFrame, model: Any, reference: dict[str, Any]) -> dict[str, Any]:
    """Full drift assessment of a recent feature window vs the reference.

    ``overall_status`` is the WORST feature/prediction status (insufficient
    features don't count against it — absence of evidence, stated as such)."""
    features_out: dict[str, Any] = {}
    worst = "healthy"
    rank = {"healthy": 0, "watch": 1, "drift": 2}
    for name, ref in (reference.get("features") or {}).items():
        if name not in frame.columns:
            continue
        d = feature_drift(frame[name], ref)
        features_out[name] = d
        if d["status"] in rank and rank[d["status"]] > rank[worst]:
            worst = d["status"]

    pred = prediction_drift(frame, model, reference.get("predicted_class_fractions") or {})
    if pred is not None and rank.get(pred["status"], 0) > rank[worst]:
        worst = pred["status"]

    return {"features": features_out, "prediction": pred, "overall_status": worst}
