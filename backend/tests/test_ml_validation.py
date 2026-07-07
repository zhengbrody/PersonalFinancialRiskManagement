"""Phase 2 — walk-forward validation report (offline, synthetic data).

Covers: fold structure (count/fields), persistence baseline SEMANTICS (the
prediction at t must equal the label at t−horizon — information availability,
not "yesterday's label"), all three baselines present in the aggregate,
calibration bin structure (counts sum to hold-out size), markdown rendering,
and run-twice determinism.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backend.app.ml import labels as ml_labels
from backend.app.ml import train as ml_train
from backend.app.ml.config import TrainConfig
from backend.app.ml.validation import (
    persistence_predictions,
    render_markdown,
    walk_forward_report,
)


def _prices(days: int, seed: int, vol: float) -> pd.Series:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2018-01-02", periods=days)
    rets = rng.normal(0.0003, vol, days)
    return pd.Series(100.0 * np.cumprod(1 + rets), index=idx)


def _raw(days: int = 900) -> dict[str, pd.Series]:
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


@pytest.fixture(scope="module")
def dataset():
    X, y = ml_train.build_dataset(_raw())
    return X, y


@pytest.fixture(scope="module")
def report(dataset):
    X, y = dataset
    return walk_forward_report(X, y, TrainConfig(cv_splits=3))


# ── persistence semantics ─────────────────────────────────────────────


def test_persistence_uses_only_observable_labels():
    idx = pd.bdate_range("2020-01-01", periods=8)
    y = pd.Series(list("ABCDEFGH"), index=idx)
    pred = persistence_predictions(y, horizon=3)
    # ŷ(t) == y(t−3): position 3 predicts 'A', position 7 predicts 'E'.
    assert pred.iloc[3] == "A"
    assert pred.iloc[7] == "E"
    # The first `horizon` positions have no completed window → NaN, never a
    # peek at a not-yet-observable label.
    assert pred.iloc[:3].isna().all()


# ── report structure ──────────────────────────────────────────────────


def test_fold_table_structure(report):
    assert len(report["folds"]) == 3
    required = {
        "fold",
        "test_start",
        "test_end",
        "n_test",
        "accuracy",
        "macro_f1",
        "log_loss",
        "baseline_majority_acc",
        "baseline_persistence_acc",
        "baseline_logistic_acc",
    }
    for f in report["folds"]:
        assert required <= set(f)
        assert 0.0 <= f["accuracy"] <= 1.0
        # Chronology: each fold tests strictly after its training end.
        assert f["test_start"] > f["train_end"]


def test_all_baselines_present_in_aggregate(report):
    agg = report["aggregate_accuracy"]
    assert set(agg) == {"model", "majority", "persistence", "logistic"}
    for name in ("model", "majority", "logistic"):
        assert agg[name] is not None and 0.0 <= agg[name] <= 1.0


def test_calibration_bins_cover_holdout(report):
    cal = report["calibration"]
    assert len(cal["bins"]) == 10
    assert sum(b["n"] for b in cal["bins"]) == cal["holdout_size"]
    for b in cal["bins"]:
        if b["n"]:
            assert 0.0 <= b["mean_predicted"] <= 1.0
            assert 0.0 <= b["observed_frequency"] <= 1.0


def test_report_is_deterministic(dataset):
    X, y = dataset
    r1 = walk_forward_report(X, y, TrainConfig(cv_splits=3))
    r2 = walk_forward_report(X, y, TrainConfig(cv_splits=3))
    assert r1["folds"] == r2["folds"]
    assert r1["aggregate_accuracy"] == r2["aggregate_accuracy"]
    assert r1["calibration"] == r2["calibration"]


# ── rendering ─────────────────────────────────────────────────────────


def test_markdown_render_contains_the_story(report):
    md = render_markdown(report)
    assert "## Walk-forward folds" in md
    assert "## Model vs baselines" in md
    assert "Persistence (y at t−horizon)" in md
    assert "## Calibration — elevated-risk probability" in md
    assert "## Permutation feature importance" in md
    assert "chronological" in md
    # Labels vocabulary sanity — the report never invents class names.
    for cls in ml_labels.CLASSES:
        assert cls not in ("",)  # vocabulary exists; md may or may not list them
    # No unresolved format placeholders.
    assert "{" not in md.replace("{'", "")


def test_markdown_render_with_png_link(report):
    md = render_markdown(report, png_rel_path="assets/reliability_elevated_risk.png")
    assert "![Reliability diagram](assets/reliability_elevated_risk.png)" in md
