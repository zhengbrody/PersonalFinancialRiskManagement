"""Model freshness + approved-artifact identity on /api/v1/ml/health, and the
release gate / provenance record the retrain pipeline writes.

Both health fields are ADDITIVE: they must never move ``status`` or the drift
``overall_status`` (a stale model can be drift-healthy, and vice versa).
"""

from __future__ import annotations

import hashlib
import json
import pickle
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from backend.app.ml import inference as ml_inference
from backend.app.ml import provenance as prov
from backend.app.services import ml_health

NOW = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)


def _iso(days_ago: float) -> str:
    return (NOW - timedelta(days=days_ago)).isoformat()


@pytest.fixture
def stale_days(monkeypatch):
    def _set(value):
        monkeypatch.setattr(
            ml_health, "get_settings", lambda: SimpleNamespace(ml_model_stale_days=value)
        )

    _set(21.0)
    return _set


# ── freshness ─────────────────────────────────────────────────────────


def test_fresh_within_threshold(stale_days):
    out = ml_health.freshness(_iso(20), now=NOW)
    assert out["status"] == "fresh"
    assert out["age_days"] == 20.0
    assert out["threshold_days"] == 21.0


def test_stale_past_threshold(stale_days):
    out = ml_health.freshness(_iso(33), now=NOW)  # 2026-09-07 → 2026-10-10
    assert out["status"] == "stale"
    assert out["age_days"] == 33.0


def test_threshold_is_configurable(stale_days):
    stale_days(40.0)
    assert ml_health.freshness(_iso(33), now=NOW)["status"] == "fresh"
    stale_days(7.0)
    assert ml_health.freshness(_iso(8), now=NOW)["status"] == "stale"


@pytest.mark.parametrize("bad", [0.0, -5.0, float("nan"), float("inf")])
def test_nonsense_threshold_falls_back_to_default(stale_days, bad):
    stale_days(bad)
    out = ml_health.freshness(_iso(22), now=NOW)
    assert out["threshold_days"] == ml_health.DEFAULT_STALE_DAYS
    assert out["status"] == "stale"


@pytest.mark.parametrize("trained_at", [None, "", "not-a-date", 12345])
def test_missing_or_unparseable_trained_at_is_unknown(stale_days, trained_at):
    out = ml_health.freshness(trained_at, now=NOW)
    assert out["status"] == "unknown"
    assert out["age_days"] is None


def test_future_trained_at_is_unknown_not_fresh(stale_days):
    assert ml_health.freshness(_iso(-2), now=NOW)["status"] == "unknown"


def test_naive_and_z_suffixed_timestamps_parse_as_utc(stale_days):
    assert ml_health.freshness("2026-10-01T12:00:00Z", now=NOW)["age_days"] == 9.0
    assert ml_health.freshness("2026-10-01T12:00:00", now=NOW)["age_days"] == 9.0


# ── approved artifact identity ────────────────────────────────────────

META = {"model_version": "regime-v1.1.0", "trained_at": "2026-09-07T11:17:59+00:00"}


def _prov(model_hash: str, **over):
    base = {
        "model_version": META["model_version"],
        "trained_at": META["trained_at"],
        "source_commit": "a" * 40,
        "run_id": "123",
        "run_url": "https://example/run/123",
        "recorded_at": "2026-09-07T11:30:00+00:00",
        "gates": {"passed": True, "checks": {"elevated_risk_auc >= 0.7": True}},
        "artifacts": {"regime_model.joblib": model_hash},
    }
    base.update(over)
    return base


def test_match_when_loaded_bytes_equal_provenance_hash():
    out = ml_health.approved_artifact(META, "abc", _prov("abc"))
    assert out["match"] is True
    assert out["approved_source"] == "provenance"
    assert out["provenance"]["source_commit"] == "a" * 40
    assert out["provenance"]["gates_passed"] is True
    assert out["provenance"]["matches_meta"] is True


def test_mismatch_when_serving_bytes_differ():
    out = ml_health.approved_artifact(META, "abc", _prov("def"))
    assert out["match"] is False


def test_provenance_wins_over_meta_hash():
    meta = {**META, "artifact_sha256": {"model": "abc"}}
    out = ml_health.approved_artifact(meta, "abc", _prov("def"))
    assert out["approved_source"] == "provenance"
    assert out["match"] is False


def test_meta_hash_is_the_fallback_without_provenance():
    meta = {**META, "artifact_sha256": {"model": "abc"}}
    out = ml_health.approved_artifact(meta, "abc", None)
    assert out["approved_source"] == "meta"
    assert out["match"] is True
    assert out["provenance"] is None


def test_no_recorded_hash_is_unknown_never_true():
    out = ml_health.approved_artifact(META, "abc", None)
    assert out["approved_sha256"] is None
    assert out["match"] is None


def test_unloaded_model_is_unknown_not_mismatch():
    assert ml_health.approved_artifact(META, None, _prov("abc"))["match"] is None


def test_provenance_from_a_different_run_is_flagged():
    stale_record = _prov("abc", trained_at="2026-08-31T12:00:00+00:00")
    out = ml_health.approved_artifact(META, "abc", stale_record)
    assert out["provenance"]["matches_meta"] is False


def test_loaded_hash_is_the_hash_of_the_bytes_actually_loaded(monkeypatch, tmp_path):
    model_path = tmp_path / "m.joblib"
    meta_path = tmp_path / "m.json"
    import joblib

    joblib.dump({"stub": 1}, model_path)
    meta_path.write_text(json.dumps(META))
    monkeypatch.setattr(ml_inference, "_MODEL_PATH", model_path)
    monkeypatch.setattr(ml_inference, "_META_PATH", meta_path)
    ml_inference.reset()
    try:
        assert ml_inference.loaded_model_sha256() == (
            hashlib.sha256(model_path.read_bytes()).hexdigest()
        )
        assert ml_inference.load_model() == {"stub": 1}
    finally:
        ml_inference.reset()


# ── health snapshot integration ───────────────────────────────────────


def test_new_fields_do_not_change_status_or_drift_verdict(monkeypatch, tmp_path, stale_days):
    monkeypatch.setattr(ml_health, "REFERENCE_PATH", tmp_path / "missing.json")
    monkeypatch.setattr(ml_health, "PROVENANCE_PATH", tmp_path / "missing-prov.json")
    old = {**META, "trained_at": "2020-01-01T00:00:00+00:00"}
    monkeypatch.setattr(ml_health.ml_inference, "model_meta", lambda: dict(old))
    monkeypatch.setattr(ml_health.ml_inference, "loaded_model_sha256", lambda: "abc")
    snap = ml_health.get_ml_health(force_refresh=True)
    assert snap["freshness"]["status"] == "stale"
    assert snap["status"] == "not_ready"  # service tier unchanged
    assert snap["overall_status"] is None  # drift verdict untouched
    assert snap["approved_artifact"]["loaded_sha256"] == "abc"
    assert snap["approved_artifact"]["match"] is None


def test_endpoint_exposes_the_additive_fields(test_client, monkeypatch, tmp_path):
    monkeypatch.setattr(ml_health, "REFERENCE_PATH", tmp_path / "missing.json")
    monkeypatch.setattr(ml_health, "PROVENANCE_PATH", tmp_path / "missing-prov.json")
    monkeypatch.setattr(ml_health.ml_inference, "model_meta", lambda: dict(META))
    monkeypatch.setattr(ml_health.ml_inference, "loaded_model_sha256", lambda: "abc")
    ml_health.reset_cache()
    data = test_client.get("/api/v1/ml/health").json()["data"]
    assert data["freshness"]["status"] in {"fresh", "stale"}
    assert data["approved_artifact"]["loaded_sha256"] == "abc"


def test_unreadable_provenance_is_no_record(monkeypatch, tmp_path):
    bad = tmp_path / "p.json"
    bad.write_text("{not json")
    monkeypatch.setattr(ml_health, "PROVENANCE_PATH", bad)
    assert ml_health._load_provenance() is None


# ── release gate + provenance record ──────────────────────────────────


def _meta_with(auc, size):
    return {"metrics": {"elevated_risk_auc": auc, "holdout_size": size}}


def test_gate_passes_at_the_floor():
    assert prov.quality_gate(_meta_with(0.70, 500))["passed"] is True


@pytest.mark.parametrize("auc,size", [(0.699, 706), (0.76, 499), (None, 706), (0.76, None)])
def test_gate_fails_below_floor_or_on_missing_metrics(auc, size):
    assert prov.quality_gate(_meta_with(auc, size))["passed"] is False


def test_gate_ignores_baseline_accuracy():
    meta = _meta_with(0.76, 706)
    meta["metrics"].update(holdout_accuracy=0.40, baseline_accuracy=0.52)
    assert prov.quality_gate(meta)["passed"] is True


def _artifacts(tmp_path):
    model = tmp_path / "regime_model.joblib"
    meta = tmp_path / "regime_meta.json"
    ref = tmp_path / "regime_reference.json"
    model.write_bytes(pickle.dumps({"m": 1}))
    meta.write_text(json.dumps(META))
    ref.write_text("{}")
    return model, meta, ref


def test_provenance_binds_commit_gates_and_artifact_hashes(tmp_path):
    model, meta, ref = _artifacts(tmp_path)
    record = prov.build_provenance(
        gates=prov.quality_gate(_meta_with(0.76, 706)),
        source_commit="b" * 40,
        run_id="9",
        run_url="u",
        extra_gates={"test_model_card": True},
        model_path=model,
        meta_path=meta,
        reference_path=ref,
    )
    assert record["source_commit"] == "b" * 40
    assert record["trained_at"] == META["trained_at"]
    assert record["gates"]["passed"] is True
    assert record["gates"]["checks"]["test_model_card"] is True
    assert (
        record["artifacts"]["regime_model.joblib"] == hashlib.sha256(model.read_bytes()).hexdigest()
    )
    assert set(record["artifacts"]) == {
        "regime_model.joblib",
        "regime_meta.json",
        "regime_reference.json",
    }


def test_a_failed_extra_gate_fails_the_record(tmp_path):
    model, meta, ref = _artifacts(tmp_path)
    record = prov.build_provenance(
        gates=prov.quality_gate(_meta_with(0.76, 706)),
        source_commit="c" * 40,
        run_id=None,
        run_url=None,
        extra_gates={"test_model_card": False},
        model_path=model,
        meta_path=meta,
        reference_path=ref,
    )
    assert record["gates"]["passed"] is False


def test_gate_cli_exit_code(monkeypatch, tmp_path):
    meta = tmp_path / "meta.json"
    monkeypatch.setattr(prov, "META_PATH", meta)
    meta.write_text(json.dumps(_meta_with(0.60, 706)))
    assert prov.main(["gate", "--out", str(tmp_path / "g.json")]) == 1
    meta.write_text(json.dumps(_meta_with(0.76, 706)))
    assert prov.main(["gate", "--out", str(tmp_path / "g.json")]) == 0
