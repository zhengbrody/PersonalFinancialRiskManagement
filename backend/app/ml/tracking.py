"""MLflow experiment tracking — training-side only, always optional.

The backend image never installs mlflow; every entry point here import-guards
it and degrades to a no-op (returns False) so unit tests and the runtime are
unaffected. With mlflow installed (requirements-train.txt), each training run
logs params/metrics/artifacts to a LOCAL FILE STORE (./mlruns, gitignored) and
registers the model under ``regime-risk-today`` with the semantic version from
the config. Inspect with:

    mlflow ui --backend-store-uri mlruns/
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)

EXPERIMENT = "risk-today-regime"
REGISTERED_MODEL = "regime-risk-today"
STORE_DIR = "mlruns"


def _flatten_metrics(metrics: dict[str, Any]) -> dict[str, float]:
    """MLflow metrics must be scalar floats — keep the honest headline set."""
    out: dict[str, float] = {}
    for k in (
        "cv_macro_f1_mean",
        "cv_accuracy_mean",
        "holdout_accuracy",
        "holdout_macro_f1",
        "elevated_risk_auc",
        "baseline_accuracy",
        "holdout_size",
    ):
        v = metrics.get(k)
        if isinstance(v, (int, float)) and v is not None:
            out[k] = float(v)
    return out


def log_run(cfg: Any, meta: dict[str, Any], artifact_paths: list[Path]) -> bool:
    """Log one training run. Returns True when actually logged, False when
    mlflow isn't installed (no-op) — never raises into the training flow."""
    try:
        import mlflow
    except ImportError:
        _log.info("ml.tracking.skipped mlflow not installed (training-side extra)")
        return False
    try:
        mlflow.set_tracking_uri(Path(STORE_DIR).absolute().as_uri())
        mlflow.set_experiment(EXPERIMENT)
        with mlflow.start_run(run_name=meta.get("model_version", "regime")):
            mlflow.log_params(cfg.echo())
            mlflow.log_metrics(_flatten_metrics(meta.get("metrics", {})))
            mlflow.set_tags(
                {
                    "sklearn_version": meta.get("sklearn_version", ""),
                    "git_sha": meta.get("git_sha", ""),
                    "training_rows": str(meta.get("training_window", {}).get("rows", "")),
                }
            )
            for p in artifact_paths:
                if Path(p).exists():
                    mlflow.log_artifact(str(p))
            # Register the joblib as a model VERSION under one registered name;
            # the semantic version travels as a tag (registry versions are
            # sequential integers by design).
            try:
                joblib_path = next((p for p in artifact_paths if str(p).endswith(".joblib")), None)
                if joblib_path is not None:
                    import joblib as _joblib
                    from mlflow import sklearn as mlflow_sklearn

                    model = _joblib.load(joblib_path)
                    mlflow_sklearn.log_model(
                        model,
                        name="model",
                        registered_model_name=REGISTERED_MODEL,
                    )
            except Exception as exc:  # noqa: BLE001 - registry is nice-to-have
                _log.warning("ml.tracking.register_failed err=%s", type(exc).__name__)
        _log.info("ml.tracking.logged experiment=%s store=%s", EXPERIMENT, STORE_DIR)
        return True
    except Exception as exc:  # noqa: BLE001 - tracking must never sink training
        _log.warning("ml.tracking.failed err=%s", type(exc).__name__)
        return False
