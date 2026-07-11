"""Public model-card data — read straight from the committed ML artifacts.

Sources (both git-tracked AND shipped inside the backend image — the machine
JSON was relocated out of docs/ for exactly this reason):
  * backend/app/ml/artifacts/regime_meta.json       — provenance + hold-out metrics
  * backend/app/ml/artifacts/validation_report.json — walk-forward metrics
                                                       (persistence baseline, Brier,
                                                       calibration bins)

No LLM, no recomputation — just read + round, so the numbers on the page can
never drift from what actually validated the model. Prose (intended use,
limitations) are stable constants that mirror docs/ml/risk_today_model_card.md.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_ARTIFACTS = Path(__file__).resolve().parents[1] / "ml" / "artifacts"
_META_PATH = _ARTIFACTS / "regime_meta.json"
_VALIDATION_PATH = _ARTIFACTS / "validation_report.json"

# Display labels for the 4 ordinal classes (lockstep with regime_summary._LABELS).
_LABELS = {
    "risk_on": "Calm",
    "neutral": "Normal",
    "volatile": "Elevated",
    "stress": "Stressed",
}

_INTENDED_USE = (
    "An experimental, probability-ranking signal for how much elevated-risk "
    "pressure is building in US equities over roughly the next two weeks. It is "
    "context for the market pages — never a trading signal, and it never changes "
    "your Health Score, VaR, or any deterministic risk number."
)

_NOT_FOR = [
    "Predicting prices, returns, or market direction.",
    "A buy / sell / hold recommendation or any investment advice.",
    "A precise 4-class verdict — on that task it does not beat a naive baseline.",
]

_LIMITATIONS = [
    "US large-cap equity view only (built from SPY/QQQ/VIX/Treasury history) — it "
    "cannot see your specific holdings, sectors, or non-US assets.",
    "On 4-class regime accuracy it loses to a persistence baseline; the value is "
    "the calibrated elevated-risk probability, not the class label.",
    "The 'stress' class is rare in the training data, so its individual calls are "
    "the least reliable.",
    "Fixed volatility thresholds and a fixed ~2-week horizon; regimes near a "
    "threshold can flip on small moves.",
    "Overlapping forward windows mean the effective sample is smaller than the raw "
    "row count, so treat the metrics as indicative, not precise.",
]

_EXCLUDED_SIGNALS = (
    "CNN Fear & Greed is deliberately excluded from the model: no reliable "
    "point-in-time history exists for it, so training on a reconstructed series "
    "would risk silent look-ahead. It appears in the UI as live context only, "
    "never as a model input."
)


def _load(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def _round(v: Any, places: int) -> Any:
    try:
        return round(float(v), places)
    except (TypeError, ValueError):
        return None


def _class_definitions(meta: dict) -> list[dict]:
    th = meta.get("label_thresholds") or {}
    ro = th.get("risk_on_vol")
    ne = th.get("neutral_vol")
    vo = th.get("volatile_vol")
    horizon = th.get("horizon", 10)

    def pct(x: Any) -> str:
        return f"{round(float(x) * 100)}%" if x is not None else "—"

    defs = [
        ("risk_on", f"forward {horizon}-day realized volatility below {pct(ro)} (annualized)"),
        ("neutral", f"between {pct(ro)} and {pct(ne)}"),
        ("volatile", f"between {pct(ne)} and {pct(vo)}"),
        ("stress", f"at or above {pct(vo)}"),
    ]
    return [{"key": k, "label": _LABELS.get(k, k.title()), "definition": d} for k, d in defs]


def _headline(agg: dict, cal: dict, metrics: dict) -> str:
    """Composed from the artifact numbers (no hand-typed values → no drift)."""
    model = agg.get("model")
    persistence = agg.get("persistence")
    brier = cal.get("brier")
    base = cal.get("brier_base_rate")
    auc = cal.get("elevated_risk_auc") or metrics.get("elevated_risk_auc")
    if None in (model, persistence, brier, base, auc):
        return (
            "An experimental probability-ranking signal for elevated-risk pressure — "
            "not a price or return forecast. See the validated metrics below."
        )
    return (
        f"On 4-class regime accuracy the model ({model:.3f}) does not beat a persistence "
        f"baseline ({persistence:.3f}) — classification is weak. Its validated value is "
        f"ranking elevated-risk probability: Brier {brier:.4f} vs a {base:.4f} base-rate "
        f"reference, hold-out ROC-AUC {auc:.3f}. It is a probability-ranking signal, not a "
        "classifier, and not a price or return forecast."
    )


def get_model_card() -> dict:
    """Assemble the model card from the committed artifacts. Fail-soft: a missing
    artifact yields available=False with the prose intact (never raises)."""
    meta = _load(_META_PATH)
    val = _load(_VALIDATION_PATH)
    metrics = meta.get("metrics") or {}
    agg = val.get("aggregate_accuracy") or {}
    cal = val.get("calibration") or {}
    importances = meta.get("feature_importances") or {}

    features = [
        {"name": name, "importance": _round(imp, 4)}
        for name, imp in sorted(importances.items(), key=lambda kv: kv[1], reverse=True)
    ]
    bins = [
        {
            "bin": b.get("bin", ""),
            "n": int(b.get("n", 0)),
            "mean_predicted": _round(b.get("mean_predicted"), 4),
            "observed_frequency": _round(b.get("observed_frequency"), 4),
        }
        for b in (cal.get("bins") or [])
    ]

    return {
        "available": bool(meta),
        "model_version": meta.get("model_version"),
        "trained_at": meta.get("trained_at"),
        "sklearn_version": meta.get("sklearn_version"),
        "estimator": meta.get("estimator"),
        "headline": _headline(agg, cal, metrics),
        "intended_use": _INTENDED_USE,
        "not_for": _NOT_FOR,
        "limitations": _LIMITATIONS,
        "excluded_signals": _EXCLUDED_SIGNALS,
        "classes": meta.get("classes") or [],
        "class_definitions": _class_definitions(meta),
        "features": features,
        "training_window": meta.get("training_window") or {},
        "class_distribution": meta.get("class_distribution") or {},
        # ── honest metrics (all read from the committed JSONs) ──
        "cv_accuracy": _round(agg.get("model"), 4),
        "persistence_baseline_accuracy": _round(agg.get("persistence"), 4),
        "majority_baseline_cv_accuracy": _round(agg.get("majority"), 4),
        "logistic_baseline_cv_accuracy": _round(agg.get("logistic"), 4),
        "holdout_accuracy": _round(metrics.get("holdout_accuracy"), 4),
        "holdout_majority_baseline_accuracy": _round(metrics.get("baseline_accuracy"), 4),
        "elevated_risk_auc": _round(
            cal.get("elevated_risk_auc") or metrics.get("elevated_risk_auc"), 4
        ),
        "brier": _round(cal.get("brier"), 4),
        "brier_base_rate": _round(cal.get("brier_base_rate"), 4),
        "elevated_base_rate": _round(cal.get("elevated_base_rate"), 4),
        "holdout_size": cal.get("holdout_size"),
        "calibration_bins": bins,
    }
