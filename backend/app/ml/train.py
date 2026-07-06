"""Offline training for the regime classifier.

    python -m backend.app.ml.train [--config backend/app/ml/configs/risk_today.yaml]
                                   [--cache-dir .cache/ml] [--years 15]

NEVER runs in the request path or on the box -- only locally / in the
train-regime CI job, which commits the produced artifact (it ships in the
backend image via ``COPY . /app``). Emits a tiny joblib model + a metadata JSON
with full provenance: training window, sklearn version, git sha, the full
config echo, feature names, label thresholds, walk-forward + held-out metrics,
baselines, and feature importances. With mlflow installed (training-side
extra), the run also lands in the local MLflow file store (see tracking.py).

Reproducibility: fixed seed (config) + ``--cache-dir`` (pickled raw-data
snapshot) → rerunning against the same snapshot reproduces metrics
bit-for-bit. Without a snapshot, live yfinance data moves daily and metrics
drift accordingly — that's data, not nondeterminism.

The eval is the point: chronological (no-shuffle) split + walk-forward CV so the
reported numbers are honest, and the model is compared to a majority-class
baseline so "is this better than guessing?" is explicit.
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

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
from . import tracking
from .config import TrainConfig, load_config
from .features import FEATURE_NAMES, WARMUP_REQUIRED, build_feature_frame

_log = logging.getLogger(__name__)

ARTIFACT_DIR = Path(__file__).parent / "artifacts"
MODEL_PATH = ARTIFACT_DIR / "regime_model.joblib"
META_PATH = ARTIFACT_DIR / "regime_meta.json"
# Kept as the no-config fallback identity; the config supersedes it.
MODEL_VERSION = "regime-v1"
RANDOM_STATE = 42


def _make_model(cfg: Optional[TrainConfig] = None) -> HistGradientBoostingClassifier:
    # HistGBM: handles NaN natively (so a missing free source doesn't break a
    # row), fast, small, sklearn-native. Shallow + regularized to resist the
    # overfitting that plagues financial models.
    c = cfg or TrainConfig()
    return HistGradientBoostingClassifier(
        max_iter=c.max_iter,
        learning_rate=c.learning_rate,
        max_depth=c.max_depth,
        l2_regularization=c.l2_regularization,
        early_stopping=c.early_stopping,
        validation_fraction=c.validation_fraction,
        random_state=c.seed,
    )


def _git_sha() -> Optional[str]:
    """Provenance only — never fails a training run."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=Path(__file__).parent,
        )
        sha = out.stdout.strip()
        return sha if out.returncode == 0 and sha else None
    except Exception:  # noqa: BLE001
        return None


def build_dataset(raw: dict[str, pd.Series]) -> tuple[pd.DataFrame, pd.Series]:
    """Aligned (X, y): no-lookahead features vs forward labels, warmup + the last
    `horizon` (unlabelable) rows dropped. Rows with NaN OPTIONAL features are
    KEPT (the model handles NaN); only NaN core/label rows are dropped."""
    X = build_feature_frame(raw)
    y = ml_labels.build_labels(raw["spy"])
    df = X.join(y.rename("label"))
    df = df.dropna(subset=["label", *WARMUP_REQUIRED])
    return df[FEATURE_NAMES], df["label"].astype(str)


def evaluate(X: pd.DataFrame, y: pd.Series, cfg: Optional[TrainConfig] = None) -> dict:
    """Honest temporal eval: walk-forward CV (expanding window) + a final
    chronological hold-out, both compared to the majority-class baseline."""
    c = cfg or TrainConfig()
    # Walk-forward CV (time-ordered; never trains on the future).
    tscv = TimeSeriesSplit(n_splits=c.cv_splits)
    cv_f1, cv_acc = [], []
    for tr, te in tscv.split(X):
        m = _make_model(c).fit(X.iloc[tr], y.iloc[tr])
        pred = m.predict(X.iloc[te])
        cv_f1.append(float(f1_score(y.iloc[te], pred, average="macro", zero_division=0)))
        cv_acc.append(float((pred == y.iloc[te]).mean()))

    # Final chronological hold-out (last holdout_fraction).
    cut = int(len(X) * (1.0 - c.holdout_fraction))
    m = _make_model(c).fit(X.iloc[:cut], y.iloc[:cut])
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


def _feature_importances(
    model, X: pd.DataFrame, y: pd.Series, cfg: Optional[TrainConfig] = None
) -> dict:
    """Permutation importance (HistGBM has no native feature_importances_)."""
    try:
        r = permutation_importance(
            model,
            X,
            y,
            n_repeats=5,
            random_state=(cfg or TrainConfig()).seed,
            scoring="f1_macro",
        )
        imps = {
            FEATURE_NAMES[i]: round(float(r.importances_mean[i]), 5)
            for i in range(len(FEATURE_NAMES))
        }
        return dict(sorted(imps.items(), key=lambda kv: kv[1], reverse=True))
    except Exception as exc:  # noqa: BLE001
        _log.warning("ml.train.perm_importance_failed err=%s", type(exc).__name__)
        return {}


def train_and_save(
    *,
    years: Optional[float] = None,
    fetcher=ml_data._yf_close,
    cfg: Optional[TrainConfig] = None,
    cache_dir: Optional[str] = None,
    track: bool = True,
) -> dict:
    c = cfg or TrainConfig()
    effective_years = years if years is not None else c.years
    raw = ml_data.fetch_history(years=effective_years, fetcher=fetcher, cache_dir=cache_dir)
    X, y = build_dataset(raw)
    if len(X) < 500:
        raise ValueError(f"too little labelled data to train: {len(X)} rows")

    metrics = evaluate(X, y, c)

    # Production model: fit on ALL labelled data; store the per-feature training
    # median so inference can describe a current value as above/below normal.
    model = _make_model(c).fit(X, y)
    importances = _feature_importances(model, X, y, c)
    medians = {col: round(float(X[col].median()), 6) for col in FEATURE_NAMES}

    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, MODEL_PATH)
    meta = {
        "model_version": c.model_version if cfg is not None else MODEL_VERSION,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "sklearn_version": sklearn.__version__,
        "git_sha": _git_sha(),
        "estimator": "HistGradientBoostingClassifier",
        "config": c.echo(),
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
    if track:
        tracking.log_run(c, meta, [MODEL_PATH, META_PATH])
    return meta


def main(argv: Optional[list[str]] = None) -> None:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="Train the Risk-Today regime classifier.")
    parser.add_argument("--config", default=None, help="YAML config (see ml/configs/)")
    parser.add_argument(
        "--cache-dir",
        default=None,
        help="pickled raw-data snapshot dir — reruns against the same snapshot "
        "reproduce metrics bit-for-bit",
    )
    parser.add_argument("--years", type=float, default=None, help="override config years")
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    meta = train_and_save(
        years=args.years,
        cfg=cfg if args.config is not None else None,
        cache_dir=args.cache_dir,
    )
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
