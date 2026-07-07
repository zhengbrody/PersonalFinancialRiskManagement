"""Phase 1 — reproducible training pipeline.

Offline + deterministic: synthetic price series via the injectable fetcher
(same recipe as test_ml_regime.py), artifacts redirected to tmp_path so the
committed production artifact is never touched. Covers: config defaults ==
module constants, YAML override + unknown-key/threshold-divergence errors,
bit-for-bit seed determinism (train twice → identical metrics), the
--cache-dir snapshot round-trip (second run never calls the fetcher), and
tracking's no-mlflow no-op path.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from backend.app.ml import data as ml_data
from backend.app.ml import labels as ml_labels
from backend.app.ml import tracking
from backend.app.ml import train as ml_train
from backend.app.ml.config import TrainConfig, load_config

# ── synthetic market (deterministic, offline) ─────────────────────────


def _prices(days: int, seed: int, vol: float) -> pd.Series:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2018-01-02", periods=days)
    rets = rng.normal(0.0003, vol, days)
    return pd.Series(100.0 * np.cumprod(1 + rets), index=idx)


def _raw(days: int = 900) -> dict[str, pd.Series]:
    # Two vol phases so all four label classes appear.
    calm = _prices(days // 2, 1, 0.006)
    storm_rets = np.random.default_rng(2).normal(-0.001, 0.03, days - days // 2)
    storm = pd.Series(
        calm.iloc[-1] * np.cumprod(1 + storm_rets),
        index=pd.bdate_range(calm.index[-1] + pd.Timedelta(days=1), periods=days - days // 2),
    )
    spy = pd.concat([calm, storm])
    idx = spy.index
    rng = np.random.default_rng(3)
    return {
        "spy": spy,
        "qqq": spy * (1 + rng.normal(0, 0.002, len(idx))).cumprod(),
        "vix": pd.Series(
            np.clip(15 + rng.normal(0, 3, len(idx)).cumsum() * 0.05, 9, 80), index=idx
        ),
        "vix3m": pd.Series(
            np.clip(17 + rng.normal(0, 2, len(idx)).cumsum() * 0.04, 10, 70), index=idx
        ),
        "tnx": pd.Series(3.0 + rng.normal(0, 0.02, len(idx)).cumsum() * 0.1, index=idx),
        "irx": pd.Series(2.5 + rng.normal(0, 0.02, len(idx)).cumsum() * 0.1, index=idx),
    }


@pytest.fixture
def tmp_artifacts(monkeypatch, tmp_path):
    """Redirect the artifact paths so tests never overwrite the committed model."""
    art = tmp_path / "artifacts"
    monkeypatch.setattr(ml_train, "ARTIFACT_DIR", art)
    monkeypatch.setattr(ml_train, "MODEL_PATH", art / "regime_model.joblib")
    monkeypatch.setattr(ml_train, "META_PATH", art / "regime_meta.json")
    return art


def _fetcher_from(raw: dict[str, pd.Series]):
    by_symbol = {ml_data.SYMBOLS[k]: v for k, v in raw.items()}

    def fetch(symbol: str, start: str):
        return by_symbol.get(symbol)

    return fetch


# ── config ────────────────────────────────────────────────────────────


def test_config_defaults_match_module_constants():
    cfg = load_config(None)
    assert cfg.seed == ml_train.RANDOM_STATE
    assert cfg.label_horizon == ml_labels.HORIZON
    assert cfg.risk_on_vol == ml_labels.RISK_ON_VOL
    assert cfg.neutral_vol == ml_labels.NEUTRAL_VOL
    assert cfg.volatile_vol == ml_labels.VOLATILE_VOL
    # And the checked-in YAML mirrors the defaults field-by-field except the
    # semantic model_version (YAML carries the bumped v1.1.0 identity).
    repo_yaml = Path(ml_train.__file__).parent / "configs" / "risk_today.yaml"
    assert repo_yaml.exists()
    yaml = pytest.importorskip("yaml", reason="pyyaml is a training-side extra")
    raw = yaml.safe_load(repo_yaml.read_text())
    defaults = TrainConfig()
    for key, value in raw.items():
        if key == "model_version":
            assert value == "regime-v1.1.0"
            continue
        assert value == getattr(defaults, key), f"YAML drifted from defaults: {key}"


def test_config_yaml_override_and_guards(tmp_path):
    yaml = pytest.importorskip("yaml", reason="pyyaml is a training-side extra")
    p = tmp_path / "cfg.yaml"
    p.write_text(yaml.safe_dump({"model_version": "regime-v9.9.9", "cv_splits": 3}))
    cfg = load_config(p)
    assert cfg.model_version == "regime-v9.9.9"
    assert cfg.cv_splits == 3
    assert cfg.seed == 42  # untouched default

    p.write_text(yaml.safe_dump({"unknown_key": 1}))
    with pytest.raises(ValueError, match="unknown config keys"):
        load_config(p)

    # Diverging label thresholds must be rejected (serving fallback buckets
    # with labels.py constants — silent divergence would split the vocab).
    p.write_text(yaml.safe_dump({"risk_on_vol": 0.10}))
    with pytest.raises(ValueError, match="labels.py"):
        load_config(p)


def test_config_bounds():
    from backend.app.ml.config import _validate

    with pytest.raises(ValueError, match="cv_splits"):
        _validate(TrainConfig(cv_splits=1))
    with pytest.raises(ValueError, match="holdout_fraction"):
        _validate(TrainConfig(holdout_fraction=0.9))


# ── reproducibility ───────────────────────────────────────────────────


def test_training_is_bit_for_bit_deterministic(tmp_artifacts):
    raw = _raw()
    fetch = _fetcher_from(raw)
    m1 = ml_train.train_and_save(fetcher=fetch, track=False)
    m2 = ml_train.train_and_save(fetcher=fetch, track=False)
    assert m1["metrics"] == m2["metrics"]  # identical dicts, not approx
    assert m1["feature_importances"] == m2["feature_importances"]
    assert m1["class_distribution"] == m2["class_distribution"]


def test_meta_carries_provenance(tmp_artifacts):
    cfg = TrainConfig(model_version="regime-v1.1.0")
    meta = ml_train.train_and_save(fetcher=_fetcher_from(_raw()), cfg=cfg, track=False)
    assert meta["model_version"] == "regime-v1.1.0"
    assert meta["config"]["seed"] == 42
    assert meta["config"]["model_version"] == "regime-v1.1.0"
    # git sha is best-effort (None outside a repo) but the key must exist.
    assert "git_sha" in meta
    on_disk = json.loads((tmp_artifacts / "regime_meta.json").read_text())
    assert on_disk["config"] == meta["config"]


def test_cache_dir_round_trip_skips_fetcher(tmp_artifacts, tmp_path):
    raw = _raw()
    calls = {"n": 0}
    inner = _fetcher_from(raw)

    def counting(symbol: str, start: str):
        calls["n"] += 1
        return inner(symbol, start)

    cache = str(tmp_path / "cache")
    m1 = ml_train.train_and_save(fetcher=counting, cache_dir=cache, track=False)
    first_calls = calls["n"]
    assert first_calls > 0

    m2 = ml_train.train_and_save(fetcher=counting, cache_dir=cache, track=False)
    assert calls["n"] == first_calls  # snapshot hit — fetcher untouched
    assert m1["metrics"] == m2["metrics"]  # bit-for-bit off the snapshot
    assert m1["data_coverage"] == m2["data_coverage"]


# ── tracking no-op safety ─────────────────────────────────────────────


def test_tracking_noop_without_mlflow(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def block_mlflow(name, *a, **k):
        if name == "mlflow" or name.startswith("mlflow."):
            raise ImportError("mlflow blocked for test")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", block_mlflow)
    ok = tracking.log_run(TrainConfig(), {"metrics": {}}, [])
    assert ok is False  # graceful no-op, no raise
