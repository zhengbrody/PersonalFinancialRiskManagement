"""Drift monitoring math for the regime pipeline — pure functions, no I/O.

DESIGN (v2 — the naive version was red-by-construction and never shipped):
comparing a contiguous, autocorrelated 120-day live window against the
15-year MIXTURE distribution flags "drift" for essentially every normal
regime window (a measured 100% in-sample false-alarm rate). The fix is a
SELF-CALIBRATED null: at training time we compute, for every feature, the
PSI of every historical 120-day training slice against the full-sample
reference — that is the distribution of "how unusual does a normal window
look". Live status then compares the live window's PSI against ITS OWN
feature's historical percentiles:

    psi ≤ p90 of training slices   → healthy
    psi ≤ p99                      → watch
    psi >  p99                     → drift  (more extreme than ~99% of all
                                             windows the model trained across)

Prediction drift (recent predicted-class mix) is calibrated the same way.

PSI mechanics: bins are the reference deciles with DUPLICATE edges merged
(discrete features carry atoms — e.g. drawdown has a mass point at 0), and
the expected mass per merged bin comes from the reference CDF, not a flat
0.10 — so a zero-width bin can never manufacture fake PSI.

KS: we report the KS STATISTIC as descriptive context only. An i.i.d.
p-value would be invalid — these windows are heavily autocorrelated
(effective sample size is a small fraction of 120) — so no p-value is
published and KS never affects status.

PSI saturation + the out-of-band channel: once a window concentrates in a
single reference decile, PSI hits its epsilon-clipped ceiling (~12.43) and
stops discriminating — for persistently trending features (yield_slope,
vol_63d) the calibrated p99 can EQUAL that ceiling, making drift unreachable
via PSI alone. The independent out-of-band rule restores out-of-support
detection: `oob_frac` = fraction of live points outside the training
[min, max]; it is exactly 0 for every in-sample window by construction (no
calibration needed), and > OOB_DRIFT_FRAC forces drift regardless of PSI.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import numpy as np
import pandas as pd

from .features import FEATURE_NAMES

_log = logging.getLogger(__name__)

QUANTILE_GRID = np.round(np.linspace(0.0, 1.0, 201), 4)  # 0.5% steps
LIVE_WINDOW = 120  # trading days compared against the reference
CALIBRATION_STRIDE = 5  # slice stride when building the null distribution
HEALTHY_PCT = 90.0  # ≤ p90 of training-slice PSIs
WATCH_PCT = 99.0  # ≤ p99 → watch; beyond → drift
MIN_LIVE_OBS = 30  # fewer live points than this → "insufficient", not a verdict
# Absolute fallback bands — ONLY for an uncalibrated (pre-v2) reference.
PSI_WATCH_ABS = 0.10
PSI_DRIFT_ABS = 0.25
# Out-of-band: > this fraction of live points outside the training [min, max]
# → drift regardless of PSI (which saturates and can't see beyond the support).
OOB_DRIFT_FRAC = 0.25
_EPS = 1e-6

# Severity lattice — the single source of the status ordering. Every "take the
# worst signal" site (per-feature OOB fold-in, per-window aggregation, the
# health service's alert edge) derives from this one tuple.
STATUS_ORDER = ("healthy", "watch", "drift")
_STATUS_RANK = {s: i for i, s in enumerate(STATUS_ORDER)}


def worst_status(statuses) -> Optional[str]:
    """Highest-severity status among the inputs; None if none rank (all
    ``insufficient`` / empty — "measured nothing" must not read healthy)."""
    ranked = [_STATUS_RANK[s] for s in statuses if s in _STATUS_RANK]
    return STATUS_ORDER[max(ranked)] if ranked else None


# ── PSI vs a reference quantile grid ──────────────────────────────────


def _ref_cdf_factory(quantile_values: np.ndarray):
    """Left-limit CDF P(X < x) from the quantile grid. Tie runs (atoms — e.g.
    drawdown's mass point at 0) resolve to the FIRST grid fraction, so an
    atom's expected mass lands in the [atom, ·) bin — matching np.histogram's
    left-closed bins. np.interp on the raw grid would resolve ties to the
    LAST fraction and manufacture fake PSI at every atom."""
    q_mono = np.maximum.accumulate(np.asarray(quantile_values, dtype=float))
    q_unique, first_idx = np.unique(q_mono, return_index=True)
    grid_at_first = QUANTILE_GRID[first_idx]

    def cdf(x):
        return np.interp(x, q_unique, grid_at_first, left=0.0, right=1.0)

    return cdf


def _reference_bins(quantile_values: list[float] | np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """The reference-side of PSI — merged decile ``edges`` + ``expected`` mass
    per bin — which depends ONLY on the reference, not the live sample. Hoist
    this out of any per-slice loop: the training calibration scores ~700
    windows against the SAME reference, so building this once per feature
    (not once per (feature, window)) removes ~10k redundant CDF rebuilds."""
    q = np.asarray(quantile_values, dtype=float)
    cdf = _ref_cdf_factory(q)
    inner = np.unique(q[::20][1:-1])  # decile edges, duplicates collapsed
    edges = np.concatenate(([-np.inf], inner, [np.inf]))
    upper = np.concatenate((cdf(inner), [1.0]))
    lower = np.concatenate(([0.0], cdf(inner)))
    expected = np.clip(upper - lower, 0.0, 1.0)
    return edges, expected


def _psi_with_bins(vals: np.ndarray, edges: np.ndarray, expected: np.ndarray) -> float:
    """PSI of a live sample given precomputed reference ``edges``/``expected``."""
    counts = np.histogram(vals, bins=edges)[0]
    observed = counts / max(1, len(vals))
    return psi_from_fractions(observed, expected)


def psi_vs_reference(vals: np.ndarray, quantile_values: list[float] | np.ndarray) -> float:
    """PSI of a sample against the reference distribution described by its
    201-point quantile grid. Decile edges with duplicates merged; expected
    mass per merged bin from the reference CDF (atom-safe). Thin wrapper over
    ``_reference_bins`` + ``_psi_with_bins`` for one-off / serving calls."""
    return _psi_with_bins(vals, *_reference_bins(quantile_values))


def psi_from_fractions(observed: np.ndarray, expected: np.ndarray) -> float:
    """PSI = Σ (obs−exp)·ln(obs/exp), epsilon-guarded."""
    obs = np.clip(np.asarray(observed, dtype=float), _EPS, None)
    exp = np.clip(np.asarray(expected, dtype=float), _EPS, None)
    obs = obs / obs.sum()
    exp = exp / exp.sum()
    return round(float(np.sum((obs - exp) * np.log(obs / exp))), 4)


def ks_statistic(vals: np.ndarray, quantile_values: list[float] | np.ndarray) -> Optional[float]:
    """KS distance to the reference CDF — DESCRIPTIVE only (no p-value; the
    i.i.d. assumption is violated by autocorrelated windows)."""
    try:
        cdf = _ref_cdf_factory(np.asarray(quantile_values, dtype=float))
        x = np.sort(np.asarray(vals, dtype=float))
        n = len(x)
        if n == 0:
            return None
        emp_hi = np.arange(1, n + 1) / n
        emp_lo = np.arange(0, n) / n
        theo = cdf(x)
        return round(float(np.max(np.maximum(np.abs(emp_hi - theo), np.abs(theo - emp_lo)))), 4)
    except Exception as exc:  # noqa: BLE001 - a metric must never sink health
        _log.warning("ml.monitoring.ks_failed err=%s", type(exc).__name__)
        return None


# ── reference construction (train side) ───────────────────────────────


def _slice_percentiles(psis: list[float]) -> dict[str, Any]:
    arr = np.asarray(psis, dtype=float)
    return {
        "n_slices": int(len(arr)),
        "window": LIVE_WINDOW,
        "stride": CALIBRATION_STRIDE,
        "p50": round(float(np.percentile(arr, 50)), 4),
        "p90": round(float(np.percentile(arr, HEALTHY_PCT)), 4),
        "p99": round(float(np.percentile(arr, WATCH_PCT)), 4),
        "max": round(float(arr.max()), 4),
    }


def build_reference(X: pd.DataFrame, model: Any, *, model_version: str) -> dict[str, Any]:
    """Training-distribution snapshot + the SELF-CALIBRATION null: per-feature
    percentiles of historical 120d-slice PSIs (see module docstring)."""
    feats: dict[str, Any] = {}
    quantiles: dict[str, np.ndarray] = {}
    for name in FEATURE_NAMES:
        col = X[name].dropna()
        if len(col) < 50:
            continue  # a mostly-NaN optional feature can't anchor a reference
        qv = np.quantile(col, QUANTILE_GRID)
        quantiles[name] = qv
        feats[name] = {
            "n": int(len(col)),
            "quantile_values": [round(float(v), 8) for v in qv],
        }

    # Null distribution: PSI of every historical live-window slice. The
    # reference bins are constant per feature — build them ONCE, not per slice.
    bins = {name: _reference_bins(quantiles[name]) for name in feats}
    slice_psis: dict[str, list[float]] = {name: [] for name in feats}
    all_pred = np.asarray(model.predict(X[FEATURE_NAMES]))
    classes = sorted(set(all_pred.astype(str)))
    full_frac = pd.Series(all_pred).value_counts(normalize=True)
    pred_slice_psis: list[float] = []
    starts = range(0, max(1, len(X) - LIVE_WINDOW + 1), CALIBRATION_STRIDE)
    for s in starts:
        window = X.iloc[s : s + LIVE_WINDOW]
        if len(window) < LIVE_WINDOW:
            continue
        for name in feats:
            vals = window[name].dropna().to_numpy(dtype=float)
            if len(vals) >= MIN_LIVE_OBS:
                slice_psis[name].append(_psi_with_bins(vals, *bins[name]))
        wpred = pd.Series(all_pred[s : s + LIVE_WINDOW]).value_counts(normalize=True)
        obs = np.array([float(wpred.get(c, 0.0)) for c in classes])
        exp = np.array([float(full_frac.get(c, 0.0)) for c in classes])
        pred_slice_psis.append(psi_from_fractions(obs, exp))

    for name in feats:
        if slice_psis[name]:
            feats[name]["slice_psi"] = _slice_percentiles(slice_psis[name])

    return {
        "model_version": model_version,
        "rows": int(len(X)),
        "calibration": {"window": LIVE_WINDOW, "stride": CALIBRATION_STRIDE},
        "features": feats,
        "predicted_class_fractions": {str(k): round(float(v), 6) for k, v in full_frac.items()},
        "prediction_slice_psi": _slice_percentiles(pred_slice_psis) if pred_slice_psis else None,
    }


# ── live drift evaluation ─────────────────────────────────────────────


def _status_calibrated(psi: float, slice_psi: Optional[dict[str, Any]]) -> tuple[str, bool]:
    """(status, calibrated?) — percentile thresholds when the reference
    carries them, absolute fallback bands otherwise."""
    if slice_psi and slice_psi.get("p99") is not None:
        if psi > slice_psi["p99"]:
            return "drift", True
        if psi > slice_psi["p90"]:
            return "watch", True
        return "healthy", True
    if psi >= PSI_DRIFT_ABS:
        return "drift", False
    if psi >= PSI_WATCH_ABS:
        return "watch", False
    return "healthy", False


def feature_drift(live: pd.Series, ref: dict[str, Any]) -> dict[str, Any]:
    """One feature's verdict: calibrated PSI + the out-of-band override."""
    vals = live.dropna().to_numpy(dtype=float)
    if len(vals) < MIN_LIVE_OBS:
        return {
            "psi": None,
            "psi_p90": None,
            "psi_p99": None,
            "ks_stat": None,
            "oob_frac": None,
            "n": int(len(vals)),
            "status": "insufficient",
            "calibrated": False,
        }
    q = ref["quantile_values"]
    psi = psi_vs_reference(vals, q)
    slice_psi = ref.get("slice_psi")
    psi_status, calibrated = _status_calibrated(psi, slice_psi)
    # Out-of-band is an INDEPENDENT detector for what PSI can't see: once a
    # window exceeds the training support, PSI saturates. Fold it in as a
    # contributed verdict (worst-of), same idiom as the window aggregation.
    oob = float(np.mean((vals < q[0]) | (vals > q[-1])))
    status = worst_status([psi_status, "drift" if oob > OOB_DRIFT_FRAC else "healthy"])
    return {
        "psi": psi,
        "psi_p90": (slice_psi or {}).get("p90"),
        "psi_p99": (slice_psi or {}).get("p99"),
        "ks_stat": ks_statistic(vals, q),
        "oob_frac": round(oob, 4),
        "n": int(len(vals)),
        "status": status,
        "calibrated": calibrated,
    }


def prediction_drift(
    frame: pd.DataFrame, model: Any, reference: dict[str, Any]
) -> Optional[dict[str, Any]]:
    """Calibrated PSI of the recent predicted-class mix vs the training mix."""
    try:
        ref_fractions = reference.get("predicted_class_fractions") or {}
        usable = frame.dropna(how="all")
        if len(usable) < MIN_LIVE_OBS or not ref_fractions:
            return None
        pred = pd.Series(model.predict(usable[FEATURE_NAMES]))
        live_frac = pred.value_counts(normalize=True)
        classes = sorted(set(ref_fractions) | set(live_frac.index.astype(str)))
        obs = np.array([float(live_frac.get(c, 0.0)) for c in classes])
        exp = np.array([float(ref_fractions.get(c, 0.0)) for c in classes])
        psi = psi_from_fractions(obs, exp)
        status, calibrated = _status_calibrated(psi, reference.get("prediction_slice_psi"))
        return {
            "psi": psi,
            "status": status,
            "calibrated": calibrated,
            "n": int(len(pred)),
            "live_fractions": {c: round(float(live_frac.get(c, 0.0)), 4) for c in classes},
        }
    except Exception as exc:  # noqa: BLE001
        _log.warning("ml.monitoring.prediction_drift_failed err=%s", type(exc).__name__)
        return None


def evaluate_drift(frame: pd.DataFrame, model: Any, reference: dict[str, Any]) -> dict[str, Any]:
    """Full drift assessment of a recent feature window vs the reference.

    ``overall_status`` is the WORST feature/prediction verdict. Insufficient
    features never count against it, and if NO channel produced a verdict at
    all the overall is None — "we measured nothing" must not read healthy."""
    features_out: dict[str, Any] = {}
    for name, ref in (reference.get("features") or {}).items():
        if name not in frame.columns:
            continue
        features_out[name] = feature_drift(frame[name], ref)

    pred = prediction_drift(frame, model, reference)
    statuses = [d["status"] for d in features_out.values()]
    if pred is not None:
        statuses.append(pred["status"])
    return {
        "features": features_out,
        "prediction": pred,
        "overall_status": worst_status(statuses),
    }
