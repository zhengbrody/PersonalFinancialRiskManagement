"""Phase 4 — drift monitoring math + /ml/health service tiers (offline).

The load-bearing test here is the FALSE-ALARM regression: v1 of the monitor
compared a contiguous live window against the 15y mixture reference and read
"drift" on 100% of in-sample training slices (caught in review, never
shipped). The self-calibrated design must judge an ordinary training-era
window as NOT drift even when its raw PSI is large, while still flagging a
window that sits outside anything the model trained across.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from backend.app.ml import data as ml_data
from backend.app.ml import monitoring as mon
from backend.app.ml.features import FEATURE_NAMES
from backend.app.services import ml_health


@pytest.fixture(autouse=True)
def _fresh_caches():
    ml_health.reset_cache()
    ml_data.reset_serve_cache()
    yield
    ml_health.reset_cache()
    ml_data.reset_serve_cache()


def _ref_feature(sample: np.ndarray) -> dict:
    return {
        "n": int(len(sample)),
        "quantile_values": [float(v) for v in np.quantile(sample, mon.QUANTILE_GRID)],
    }


class _StubModel:
    def __init__(self, cls: str = "risk_on"):
        self.cls = cls

    def predict(self, X):
        return np.array([self.cls] * len(X))


def _ar1_frame(n: int, seed: int, phi: float = 0.95) -> pd.DataFrame:
    """Autocorrelated (AR-1) synthetic features — the geometry live windows
    actually have, unlike i.i.d. draws."""
    rng = np.random.default_rng(seed)
    cols = {}
    for name in FEATURE_NAMES:
        eps = rng.normal(0, 1, n)
        x = np.empty(n)
        x[0] = eps[0]
        for i in range(1, n):
            x[i] = phi * x[i - 1] + eps[i]
        cols[name] = x
    return pd.DataFrame(cols)


# ── PSI / KS math (uncalibrated fallback path) ────────────────────────


def test_feature_drift_zero_for_same_distribution():
    rng = np.random.default_rng(1)
    ref = _ref_feature(rng.normal(0, 1, 3000))
    d = mon.feature_drift(pd.Series(rng.normal(0, 1, 300)), ref)
    assert d["status"] == "healthy"
    assert d["calibrated"] is False  # no slice_psi in ref → absolute bands
    assert d["psi"] < 0.05
    assert d["ks_stat"] < 0.1


def test_feature_drift_monotone_under_mean_shift():
    rng = np.random.default_rng(2)
    ref = _ref_feature(rng.normal(0, 1, 3000))
    psis = []
    for shift in (0.0, 0.5, 1.0, 2.0):
        live = pd.Series(rng.normal(shift, 1, 300))
        psis.append(mon.feature_drift(live, ref)["psi"])
    assert psis == sorted(psis)  # bigger shift → bigger PSI
    assert psis[-1] >= mon.PSI_DRIFT_ABS  # a 2σ mean shift is unambiguous drift
    d2 = mon.feature_drift(pd.Series(rng.normal(2.0, 1, 300)), ref)
    assert d2["status"] == "drift"
    assert d2["ks_stat"] > 0.5


def test_feature_drift_insufficient_sample_is_not_a_verdict():
    rng = np.random.default_rng(3)
    ref = _ref_feature(rng.normal(0, 1, 3000))
    d = mon.feature_drift(pd.Series(rng.normal(0, 1, 10)), ref)
    assert d["status"] == "insufficient"
    assert d["psi"] is None


def test_psi_from_fractions_identity_and_shift():
    assert mon.psi_from_fractions(np.full(10, 0.1), np.full(10, 0.1)) == 0.0
    skewed = np.array([0.5, 0.5 / 9 * 1, *([0.5 / 9] * 8)])
    assert mon.psi_from_fractions(skewed, np.full(10, 0.1)) > mon.PSI_DRIFT_ABS


def test_atom_heavy_feature_produces_no_fake_psi():
    """A feature with a mass point (drawdown sits at exactly 0.0 in calm
    markets ~15% of days) creates DUPLICATE decile edges. The CDF-mass PSI
    must not manufacture drift out of the resulting degenerate bins."""
    rng = np.random.default_rng(9)

    def draw(n: int) -> np.ndarray:
        vals = -np.abs(rng.normal(0, 0.1, n))
        vals[rng.random(n) < 0.4] = 0.0  # 40% atom at the max value
        return vals

    ref = _ref_feature(draw(3000))
    assert len(np.unique(np.asarray(ref["quantile_values"])[::20])) < 11  # ties exist
    d = mon.feature_drift(pd.Series(draw(300)), ref)
    assert d["psi"] < 0.05
    assert d["status"] == "healthy"


# ── the calibrated null (review regression) ───────────────────────────


def test_in_sample_window_is_not_drift_even_when_raw_psi_is_large():
    """THE review finding: contiguous autocorrelated windows vs the mixture
    reference have LARGE raw PSI by construction (v1 read 163/163 in-sample
    slices as 'drift'). The calibrated verdict must know that's normal."""
    X = _ar1_frame(1200, seed=7)
    ref = mon.build_reference(X, _StubModel(), model_version="t")

    tail = X.tail(mon.LIVE_WINDOW)
    raw_psi = mon.psi_vs_reference(
        tail[FEATURE_NAMES[0]].to_numpy(),
        ref["features"][FEATURE_NAMES[0]]["quantile_values"],
    )
    assert raw_psi > mon.PSI_DRIFT_ABS  # v1 would have flagged this window

    for window in (tail, X.iloc[500 : 500 + mon.LIVE_WINDOW]):
        out = mon.evaluate_drift(window, _StubModel(), ref)
        assert out["overall_status"] != "drift"
        assert all(f["calibrated"] for f in out["features"].values())


def test_out_of_support_window_is_still_drift():
    """Calibration must not blind the monitor: a window OUTSIDE anything in
    training (level shift ≫ the process scale) must exceed the p99 null."""
    X = _ar1_frame(1200, seed=8)
    ref = mon.build_reference(X, _StubModel(), model_version="t")
    shifted = X.tail(mon.LIVE_WINDOW).copy()
    span = float(X[FEATURE_NAMES[0]].max() - X[FEATURE_NAMES[0]].min())
    shifted[FEATURE_NAMES[0]] = shifted[FEATURE_NAMES[0]] + 3 * span
    out = mon.evaluate_drift(shifted, _StubModel(), ref)
    assert out["features"][FEATURE_NAMES[0]]["status"] == "drift"
    assert out["overall_status"] == "drift"


# ── reference + prediction drift ──────────────────────────────────────


def test_build_reference_structure_and_calibration():
    X = _ar1_frame(400, seed=4)
    ref = mon.build_reference(X, _StubModel(), model_version="regime-vT")
    assert ref["model_version"] == "regime-vT"
    assert ref["rows"] == 400
    assert set(ref["features"]) == set(FEATURE_NAMES)
    for f in ref["features"].values():
        assert len(f["quantile_values"]) == len(mon.QUANTILE_GRID)
        assert f["slice_psi"]["n_slices"] > 0
        assert f["slice_psi"]["p50"] <= f["slice_psi"]["p90"] <= f["slice_psi"]["p99"]
    assert ref["predicted_class_fractions"] == {"risk_on": 1.0}
    assert ref["prediction_slice_psi"]["n_slices"] > 0


def test_prediction_drift_flags_regime_mix_change():
    rng = np.random.default_rng(5)
    frame = pd.DataFrame(rng.normal(0, 1, (120, len(FEATURE_NAMES))), columns=FEATURE_NAMES)
    same = mon.prediction_drift(
        frame, _StubModel("risk_on"), {"predicted_class_fractions": {"risk_on": 1.0}}
    )
    assert same["psi"] == 0.0 and same["status"] == "healthy"
    flipped = mon.prediction_drift(
        frame,
        _StubModel("stress"),
        {"predicted_class_fractions": {"risk_on": 0.9, "stress": 0.1}},
    )
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


def test_serve_cache_shares_one_fetch(monkeypatch):
    calls = []

    def counting(symbol, start):
        calls.append(symbol)
        idx = pd.bdate_range(end="2026-06-30", periods=500)
        return pd.Series(np.linspace(100, 120, 500), index=idx)

    monkeypatch.setattr(ml_data, "_yf_close", counting)
    first = ml_data.fetch_history_cached(years=1.75)
    n_after_first = len(calls)
    second = ml_data.fetch_history_cached(years=1.75)
    assert len(calls) == n_after_first  # second consumer hit the shared cache
    assert first is second


# ── alerting semantics ────────────────────────────────────────────────


def test_alert_fires_only_on_known_worsening(monkeypatch):
    warns, infos = [], []
    monkeypatch.setattr(ml_health._log, "warning", lambda *a, **k: warns.append(a))
    monkeypatch.setattr(ml_health._log, "info", lambda *a, **k: infos.append(a))
    drifty = {
        "overall_status": "drift",
        "features": {"vol_21d": {"status": "drift"}},
        "model_version": "t",
    }
    # restart / prior-tier-unknown → info, never an alert
    ml_health._maybe_alert(previous=None, current=drifty)
    ml_health._maybe_alert(previous={"overall_status": None}, current=drifty)
    assert warns == [] and len(infos) == 2
    # known worsening → exactly one alert per transition
    ml_health._maybe_alert(previous={"overall_status": "healthy"}, current=drifty)
    ml_health._maybe_alert(previous={"overall_status": "watch"}, current=drifty)
    assert len(warns) == 2
    # steady state / recovery → silent
    ml_health._maybe_alert(previous=drifty, current=drifty)
    ml_health._maybe_alert(previous=drifty, current={"overall_status": "healthy"})
    assert len(warns) == 2
