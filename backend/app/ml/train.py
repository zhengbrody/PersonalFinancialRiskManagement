"""Offline training for the regime classifier. Run: ``python -m backend.app.ml.train``.

NEVER runs in the request path or on the box -- only locally / in the
train-regime CI job, which commits the produced artifact (it ships in the
backend image via ``COPY . /app``). Emits a tiny joblib model + a metadata JSON
with full provenance: training window, sklearn version, feature names, label
thresholds, walk-forward + held-out metrics, baselines, and feature importances.

The eval is the point: chronological (no-shuffle) split + walk-forward CV so the
reported numbers are honest, and the model is compared to a majority-class
baseline so "is this better than guessing?" is explicit.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.inspection import permutation_importance
from sklearn.metrics import classification_report, confusion_matrix, f1_score, roc_auc_score
from sklearn.model_selection import TimeSeriesSplit

from . import data as ml_data
from . import labels as ml_labels
from .features import FEATURE_NAMES, build_feature_frame

_log = logging.getLogger(__name__)

ARTIFACT_DIR = Path(__file__).parent / "artifacts"
MODEL_PATH = ARTIFACT_DIR / "regime_model.joblib"
META_PATH = ARTIFACT_DIR / "regime_meta.json"
MODEL_VERSION = "regime-v1"
RANDOM_STATE = 42


def _make_model() -> HistGradientBoostingClassifier:
    # HistGBM: handles NaN natively (so a missing free source doesn't break a
    # row), fast, small, sklearn-native. Shallow + regularized to resist the
    # overfitting that plagues financial models.
    return HistGradientBoostingClassifier(
        max_iter=250,
        learning_rate=0.05,
        max_depth=3,
        l2_regularization=1.0,
        early_stopping=True,
        validation_fraction=0.15,
        random_state=RANDOM_STATE,
    )


def build_dataset(raw: dict[str, pd.Series]) -> tuple[pd.DataFrame, pd.Series]:
    """Aligned (X, y): no-lookahead features vs forward labels, warmup + the last
    `horizon` (unlabelable) rows dropped. Rows with NaN OPTIONAL features are
    KEPT (the model handles NaN); only NaN core/label rows are dropped."""
    X = build_feature_frame(raw)
    y = ml_labels.build_labels(raw["spy"])
    df = X.join(y.rename("label"))
    df = df.dropna(subset=["label", "trend_sma200", "vol_ratio", "drawdown"])
    return df[FEATURE_NAMES], df["label"].astype(str)


def evaluate(X: pd.DataFrame, y: pd.Series) -> dict:
    """Honest temporal eval: walk-forward CV (expanding window) + a final
    chronological hold-out, both compared to the majority-class baseline."""
    # Walk-forward CV (time-ordered; never trains on the future).
    tscv = TimeSeriesSplit(n_splits=5)
    cv_f1, cv_acc = [], []
    for tr, te in tscv.split(X):
        m = _make_model().fit(X.iloc[tr], y.iloc[tr])
        pred = m.predict(X.iloc[te])
        cv_f1.append(float(f1_score(y.iloc[te], pred, average="macro", zero_division=0)))
        cv_acc.append(float((pred == y.iloc[te]).mean()))

    # Final chronological hold-out (last 20%).
    cut = int(len(X) * 0.8)
    m = _make_model().fit(X.iloc[:cut], y.iloc[:cut])
    pred = m.predict(X.iloc[cut:])
    proba = m.predict_proba(X.iloc[cut:])
    y_te = y.iloc[cut:]
    majority = y.iloc[:cut].value_counts().idxmax()
    baseline_acc = float((y_te == majority).mean())
    report = classification_report(
        y_te, pred, output_dict=True, zero_division=0, labels=ml_labels.CLASSES
    )
    cm = confusion_matrix(y_te, pred, labels=ml_labels.CLASSES).tolist()

    # Headline binary signal: "is elevated risk (volatile|stress) coming?" — the
    # genuinely learnable part (vol clusters). ROC-AUC of P(elevated) vs truth,
    # which is threshold-free and not fooled by the calm-class majority.
    classes = list(m.classes_)
    elevated_idx = [i for i, c in enumerate(classes) if c in ("volatile", "stress")]
    p_elev = proba[:, elevated_idx].sum(axis=1)
    y_elev = y_te.isin(["volatile", "stress"]).astype(int).to_numpy()
    elevated_auc = (
        round(float(roc_auc_score(y_elev, p_elev)), 4) if y_elev.min() != y_elev.max() else None
    )

    return {
        "cv_macro_f1_mean": round(float(np.mean(cv_f1)), 4),
        "cv_accuracy_mean": round(float(np.mean(cv_acc)), 4),
        "holdout_accuracy": round(float((pred == y_te).mean()), 4),
        "holdout_macro_f1": round(float(f1_score(y_te, pred, average="macro", zero_division=0)), 4),
        "elevated_risk_auc": elevated_auc,
        "baseline_majority_class": str(majority),
        "baseline_accuracy": round(baseline_acc, 4),
        "per_class": {
            c: {k: round(float(report[c][k]), 3) for k in ("precision", "recall", "f1-score")}
            for c in ml_labels.CLASSES
            if c in report
        },
        "confusion_matrix": cm,
        "confusion_labels": ml_labels.CLASSES,
        "holdout_size": int(len(y_te)),
    }


def _feature_importances(model, X: pd.DataFrame, y: pd.Series) -> dict:
    """Permutation importance (HistGBM has no native feature_importances_)."""
    try:
        r = permutation_importance(
            model, X, y, n_repeats=5, random_state=RANDOM_STATE, scoring="f1_macro"
        )
        imps = {
            FEATURE_NAMES[i]: round(float(r.importances_mean[i]), 5)
            for i in range(len(FEATURE_NAMES))
        }
        return dict(sorted(imps.items(), key=lambda kv: kv[1], reverse=True))
    except Exception as exc:  # noqa: BLE001
        _log.warning("ml.train.perm_importance_failed err=%s", type(exc).__name__)
        return {}


def train_and_save(*, years: float = 15.0, fetcher=ml_data._yf_close) -> dict:
    raw = ml_data.fetch_history(years=years, fetcher=fetcher)
    X, y = build_dataset(raw)
    if len(X) < 500:
        raise ValueError(f"too little labelled data to train: {len(X)} rows")

    metrics = evaluate(X, y)

    # Production model: fit on ALL labelled data; store the per-feature training
    # median so inference can describe a current value as above/below normal.
    model = _make_model().fit(X, y)
    importances = _feature_importances(model, X, y)
    medians = {c: round(float(X[c].median()), 6) for c in FEATURE_NAMES}

    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, MODEL_PATH)
    meta = {
        "model_version": MODEL_VERSION,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "sklearn_version": sklearn.__version__,
        "estimator": "HistGradientBoostingClassifier",
        "feature_names": FEATURE_NAMES,
        "classes": ml_labels.CLASSES,
        "label_thresholds": ml_labels.label_thresholds(),
        "training_window": {
            "start": str(X.index[0].date()),
            "end": str(X.index[-1].date()),
            "rows": int(len(X)),
        },
        "class_distribution": {k: int(v) for k, v in y.value_counts().items()},
        "metrics": metrics,
        "feature_importances": importances,
        "feature_medians": medians,
        "data_coverage": ml_data.data_coverage(raw),
    }
    META_PATH.write_text(json.dumps(meta, indent=2))
    return meta


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    meta = train_and_save()
    m = meta["metrics"]
    print(
        f"\n=== {meta['model_version']} trained ({meta['training_window']['rows']} rows, "
        f"{meta['training_window']['start']}..{meta['training_window']['end']}) ==="
    )
    print(f"  walk-forward CV: macro-F1 {m['cv_macro_f1_mean']}  acc {m['cv_accuracy_mean']}")
    print(f"  hold-out:        acc {m['holdout_accuracy']}  macro-F1 {m['holdout_macro_f1']}")
    print(f"  elevated-risk:   ROC-AUC {m['elevated_risk_auc']}  (binary volatile|stress)")
    print(
        f"  vs baseline:     majority '{m['baseline_majority_class']}' acc {m['baseline_accuracy']}"
    )
    print(f"  class dist:      {meta['class_distribution']}")
    top = list(meta["feature_importances"].items())[:5]
    print(f"  top features:    {top}")


if __name__ == "__main__":
    main()
