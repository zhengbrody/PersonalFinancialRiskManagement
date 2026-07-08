"""Phase 4 — drift monitoring math + /ml/health service tiers (offline).

Covers: PSI monotonically responds to synthetic distribution shifts (and is
~0 for an unshifted sample), KS agrees, insufficient-sample guard, prediction
drift PSI, reference build structure, the service's three tiers (ok /
not_ready / unavailable), the endpoint envelope, and alert-on-transition
throttling.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from backend.app.ml import monitoring as mon
from backend.app.ml.features import FEATURE_NAMES
from backend.app.services import ml_health


@pytest.fixture(autouse=True)
def _fresh_cache():
    ml_health.reset_cache()
    yield
    ml_health.reset_cache()


def _ref_feature(sample: np.ndarray) -> dict:
    return {
        "n": int(len(sample)),
        "quantile_values": [float(v) for v in np.quantile(sample, mon.QUANTILE_GRID)],
    }


# ── PSI / KS math ─────────────────────────────────────────────────────


def test_feature_drift_zero_for_same_distribution():
    rng = np.random.default_rng(1)
    ref = _ref_feature(rng.normal(0, 1, 3000))
    live = pd.Series(rng.normal(0, 1, 300))
    d = mon.feature_drift(live, ref)
    assert d["status"] == "healthy"
    assert d["psi"] < 0.05
    assert d["ks_p"] > 0.01


def test_feature_drift_monotone_under_mean_shift():
    rng = np.random.default_rng(2)
    ref = _ref_feature(rng.normal(0, 1, 3000))
    psis = []
    for shift in (0.0, 0.5, 1.0, 2.0):
        live = pd.Series(rng.normal(shift, 1, 300))
        psis.append(mon.feature_drift(live, ref)["psi"])
    assert psis == sorted(psis)  # bigger shift → bigger PSI
    assert psis[-1] >= mon.PSI_DRIFT  # a 2σ mean shift is unambiguous drift
    d2 = mon.feature_drift(pd.Series(rng.normal(2.0, 1, 300)), ref)
    assert d2["status"] == "drift"
    assert d2["ks_p"] < 1e-6


def test_feature_drift_insufficient_sample_is_not_a_verdict():
    rng = np.random.default_rng(3)
    ref = _ref_feature(rng.normal(0, 1, 3000))
    d = mon.feature_drift(pd.Series(rng.normal(0, 1, 10)), ref)
    assert d["status"] == "insufficient"
    assert d["psi"] is None


def test_psi_from_fractions_identity_and_shift():
    assert mon.psi_from_fractions(np.full(10, 0.1), np.full(10, 0.1)) == 0.0
    skewed = np.array([0.5, 0.5 / 9 * 1, *([0.5 / 9] * 8)])
    assert mon.psi_from_fractions(skewed, np.full(10, 0.1)) > mon.PSI_DRIFT


# ── reference + prediction drift ──────────────────────────────────────


class _StubModel:
    def __init__(self, cls: str = "risk_on"):
        self.cls = cls

    def predict(self, X):
        return np.array([self.cls] * len(X))


def test_build_reference_structure():
    rng = np.random.default_rng(4)
    X = pd.DataFrame(rng.normal(0, 1, (400, len(FEATURE_NAMES))), columns=FEATURE_NAMES)
    ref = mon.build_reference(X, _StubModel(), model_version="regime-vT")
    assert ref["model_version"] == "regime-vT"
    assert ref["rows"] == 400
    assert set(ref["features"]) == set(FEATURE_NAMES)
    for f in ref["features"].values():
        assert len(f["quantile_values"]) == len(mon.QUANTILE_GRID)
    assert ref["predicted_class_fractions"] == {"risk_on": 1.0}


def test_prediction_drift_flags_regime_mix_change():
    rng = np.random.default_rng(5)
    frame = pd.DataFrame(rng.normal(0, 1, (120, len(FEATURE_NAMES))), columns=FEATURE_NAMES)
    same = mon.prediction_drift(frame, _StubModel("risk_on"), {"risk_on": 1.0})
    assert same["psi"] == 0.0 and same["status"] == "healthy"
    flipped = mon.prediction_drift(frame, _StubModel("stress"), {"risk_on": 0.9, "stress": 0.1})
    assert flipped["status"] == "drift"


def test_evaluate_drift_overall_is_worst():
    rng = np.random.default_rng(6)
    base = rng.normal(0, 1, 3000)
    ref = {
        "model_version": "t",
        "rows": 3000,
        "features": {FEATURE_NAMES[0]: _ref_feature(base), FEATURE_NAMES[1]: _ref_feature(base)},
        "predicted_class_fractions": {"risk_on": 1.0},
    }
    frame = pd.DataFrame(
        {
            FEATURE_NAMES[0]: rng.normal(0, 1, 200),  # healthy
            FEATURE_NAMES[1]: rng.normal(3, 1, 200),  # screaming drift
            **{c: rng.normal(0, 1, 200) for c in FEATURE_NAMES[2:]},
        }
    )
    out = mon.evaluate_drift(frame, _StubModel("risk_on"), ref)
    assert out["features"][FEATURE_NAMES[1]]["status"] == "drift"
    assert out["overall_status"] == "drift"


# ── service tiers + endpoint ──────────────────────────────────────────


def test_service_not_ready_without_reference(monkeypatch, tmp_path):
    monkeypatch.setattr(ml_health, "REFERENCE_PATH", tmp_path / "missing.json")
    snap = ml_health.get_ml_health(force_refresh=True)
    assert snap["status"] == "not_ready"
    assert "regime_reference" in (snap["note"] or "")


def test_service_unavailable_when_data_down(monkeypatch, tmp_path):
    ref_path = tmp_path / "ref.json"
    ref_path.write_text(json.dumps({"model_version": "t", "rows": 1, "features": {}}))
    monkeypatch.setattr(ml_health, "REFERENCE_PATH", ref_path)
    monkeypatch.setattr(ml_health.ml_inference, "load_model", lambda: _StubModel())
    snap = ml_health.get_ml_health(force_refresh=True, fetcher=lambda s, st: None)
    assert snap["status"] == "unavailable"


def test_endpoint_envelope(test_client, monkeypatch, tmp_path):
    monkeypatch.setattr(ml_health, "REFERENCE_PATH", tmp_path / "missing.json")
    resp = test_client.get("/api/v1/ml/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["error"] is None
    assert body["data"]["status"] == "not_ready"
    assert "request_id" in body["meta"]


def test_alert_fires_only_on_transition(monkeypatch):
    calls = []
    monkeypatch.setattr(ml_health._log, "warning", lambda *a, **k: calls.append(a))
    drifty = {
        "overall_status": "drift",
        "features": {"vol_21d": {"status": "drift"}},
        "model_version": "t",
    }
    ml_health._maybe_alert(previous={"overall_status": "healthy"}, current=drifty)
    ml_health._maybe_alert(previous=drifty, current=drifty)  # steady state → silent
    assert len(calls) == 1
