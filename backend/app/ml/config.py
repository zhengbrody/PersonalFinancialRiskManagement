"""Training configuration for the regime pipeline.

One frozen dataclass, three sources in priority order: YAML file (when a path
is given AND pyyaml is installed) → built-in defaults (== the module constants
the pipeline has always used). The backend runtime NEVER needs pyyaml — it is
a training-side dependency (``requirements-train.txt``); ``load_config(None)``
returns pure defaults with zero imports beyond stdlib.

Guardrail: the label thresholds/horizon in a config MUST match
``labels.py``'s module constants. The serving heuristic fallback buckets
current realized vol with those constants — training a model on different
label boundaries while serving buckets with the old ones would silently split
the vocabulary's meaning. Changing thresholds is allowed, but only by editing
``labels.py`` AND the config together (the validator points at both).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Optional

from . import labels as ml_labels


@dataclass(frozen=True)
class TrainConfig:
    model_version: str = "regime-v1.1.0"
    seed: int = 42
    years: float = 15.0
    cv_splits: int = 5
    holdout_fraction: float = 0.2
    # HistGradientBoostingClassifier hyperparameters (shallow + regularized —
    # financial tabular data overfits fast).
    max_iter: int = 250
    learning_rate: float = 0.05
    max_depth: int = 3
    l2_regularization: float = 1.0
    early_stopping: bool = True
    validation_fraction: float = 0.15
    # Label definition — must mirror labels.py (validated below).
    label_horizon: int = ml_labels.HORIZON
    risk_on_vol: float = ml_labels.RISK_ON_VOL
    neutral_vol: float = ml_labels.NEUTRAL_VOL
    volatile_vol: float = ml_labels.VOLATILE_VOL

    def echo(self) -> dict[str, Any]:
        """JSON-safe copy for meta/MLflow provenance."""
        return asdict(self)


def _validate(cfg: TrainConfig) -> TrainConfig:
    if cfg.seed < 0:
        raise ValueError("seed must be >= 0")
    if not 2 <= cfg.cv_splits <= 20:
        raise ValueError("cv_splits must be in [2, 20]")
    if not 0.05 <= cfg.holdout_fraction <= 0.5:
        raise ValueError("holdout_fraction must be in [0.05, 0.5]")
    if cfg.years < 3:
        raise ValueError("years must be >= 3 (need enough regimes to learn)")
    mismatches = {
        "label_horizon": (cfg.label_horizon, ml_labels.HORIZON),
        "risk_on_vol": (cfg.risk_on_vol, ml_labels.RISK_ON_VOL),
        "neutral_vol": (cfg.neutral_vol, ml_labels.NEUTRAL_VOL),
        "volatile_vol": (cfg.volatile_vol, ml_labels.VOLATILE_VOL),
    }
    bad = {k: v for k, v in mismatches.items() if v[0] != v[1]}
    if bad:
        raise ValueError(
            "config label definition diverges from labels.py — the serving "
            "heuristic fallback buckets with labels.py constants, so training "
            "on different boundaries would silently change what the classes "
            f"mean. Update backend/app/ml/labels.py together with the config. "
            f"Mismatches (config, labels.py): {bad}"
        )
    return cfg


def load_config(path: Optional[str | Path] = None) -> TrainConfig:
    """Defaults when ``path`` is None; else parse the YAML (training envs
    install pyyaml via requirements-train.txt — a clear error otherwise)."""
    if path is None:
        return _validate(TrainConfig())
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - environment-specific
        raise RuntimeError(
            "--config requires pyyaml (training-side dep): "
            "pip install -r backend/app/ml/requirements-train.txt"
        ) from exc
    raw = yaml.safe_load(Path(path).read_text()) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"config must be a YAML mapping, got {type(raw).__name__}")
    known = {f for f in TrainConfig.__dataclass_fields__}
    unknown = sorted(set(raw) - known)
    if unknown:
        raise ValueError(f"unknown config keys: {unknown} (allowed: {sorted(known)})")
    return _validate(TrainConfig(**raw))
