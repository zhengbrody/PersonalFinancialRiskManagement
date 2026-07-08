"""Regime ML pipeline tests — offline + deterministic (no network, no LLM).

Covers the user's explicit list: feature generation, no-lookahead leakage, label
construction, inference schema, missing-data fallback, and train/serve feature
parity. The committed artifact (backend/app/ml/artifacts/) is used when present;
the fallback paths are exercised by forcing the model unavailable.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backend.app.ml import inference as ml_inference
from backend.app.ml import labels as ml_labels
from backend.app.ml.features import FEATURE_NAMES, build_feature_frame, latest_feature_row
from backend.app.services import ml_regime


def _prices(n: int, *, seed: int, daily_std: float = 0.008, drift: float = 0.0003) -> pd.Series:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2015-01-02", periods=n)
    rets = rng.normal(drift, daily_std, n)
    return pd.Series(100.0 * np.exp(np.cumsum(rets)), index=idx)


def _raw(n: int = 700, seed: int = 1) -> dict[str, pd.Series]:
    spy = _prices(n, seed=seed)
    idx = spy.index
    rng = np.random.default_rng(seed + 9)
    return {
        "spy": spy,
        "qqq": _prices(n, seed=seed + 1, daily_std=0.011),
        "vix": pd.Series(np.abs(rng.normal(17, 4, n)) + 8, index=idx),
        "vix3m": pd.Series(np.abs(rng.normal(19, 3, n)) + 9, index=idx),
        "tnx": pd.Series(np.abs(rng.normal(3.5, 0.4, n)), index=idx),
        "irx": pd.Series(np.abs(rng.normal(2.5, 0.4, n)), index=idx),
    }


def _fetcher_from(raw: dict):
    sym_to_key = {
        "SPY": "spy",
        "QQQ": "qqq",
        "^VIX": "vix",
        "^VIX3M": "vix3m",
        "^TNX": "tnx",
        "^IRX": "irx",
    }

    def fetch(symbol, start):
        return raw.get(sym_to_key.get(symbol))

    return fetch


# ── features ────────────────────────────────────────────────────────────────


def test_features_shape_and_determinism():
    raw = _raw()
    f1 = build_feature_frame(raw)
    f2 = build_feature_frame(raw)
    assert list(f1.columns) == FEATURE_NAMES
    assert len(f1) == len(raw["spy"])
    pd.testing.assert_frame_equal(f1, f2)  # deterministic


def test_features_require_spy():
    with pytest.raises(ValueError):
        build_feature_frame({"vix": _raw()["vix"]})


def test_missing_optional_source_yields_nan_not_error():
    raw = _raw()
    raw.pop("vix3m")  # optional gone
    f = build_feature_frame(raw)
    assert f["vix_term"].isna().all()  # degraded, not crashed
    assert f["vix_level"].notna().any()  # core VIX still there


def test_no_lookahead_leakage():
    """A feature row at day t must NOT change when FUTURE bars are appended —
    proof that every feature uses only data <= t."""
    raw = _raw(n=600, seed=4)
    short = build_feature_frame(raw)
    # Append 60 future bars to every series.
    raw_long = {k: pd.concat([v, _prices(60, seed=hash(k) % 999)]) for k, v in raw.items()}
    long = build_feature_frame(raw_long)
    t = short.index[400]
    pd.testing.assert_series_equal(short.loc[t], long.loc[t], check_names=False)


# ── labels ──────────────────────────────────────────────────────────────────


def test_label_construction_from_known_forward_vol():
    """Calm-then-volatile series: a day whose forward window is calm -> risk_on;
    a day whose forward window sits in the high-vol stretch -> stress."""
    rng = np.random.default_rng(7)
    calm = rng.normal(0, 0.003, 300)  # ~5% annualized -> risk_on (<12%)
    storm = rng.normal(0, 0.05, 120)  # ~79% annualized -> clearly stress (>28%)
    rets = np.concatenate([calm, storm])
    idx = pd.bdate_range("2015-01-02", periods=len(rets))
    prices = pd.Series(100.0 * np.exp(np.cumsum(rets)), index=idx)

    y = ml_labels.build_labels(prices, horizon=10)
    assert y.iloc[280] == "risk_on"  # forward window 281..290 still calm
    assert y.iloc[305] == "stress"  # forward window fully inside the storm
    # The unlabelable tail (no future) is NaN.
    assert pd.isna(y.iloc[-1])


def test_label_classes_are_the_declared_vocab():
    y = ml_labels.build_labels(_raw()["spy"]).dropna()
    assert set(y.unique()) <= set(ml_labels.CLASSES)


# ── inference + train/serve parity ───────────────────────────────────────────


def test_train_serve_feature_parity():
    """latest_feature_row must equal the last warmed row of build_feature_frame
    (same function both sides — no train/serve skew)."""
    raw = _raw()
    full = build_feature_frame(raw).dropna(subset=["trend_sma200", "vol_ratio", "drawdown"])
    latest = latest_feature_row(raw)
    pd.testing.assert_frame_equal(latest, full.iloc[[-1]])


@pytest.mark.skipif(not ml_inference.is_available(), reason="model artifact not present")
def test_inference_schema_with_artifact():
    ml_inference.reset()
    row = latest_feature_row(_raw())
    out = ml_inference.predict(row)
    assert out["regime"] in ml_labels.CLASSES
    assert 0.0 <= out["confidence"] <= 1.0
    # probs are rounded to 4dp each — four roundings can drift the sum by ±2e-4
    assert abs(sum(out["class_probabilities"].values()) - 1.0) < 5e-4
    assert out["model_version"]
    assert all({"feature", "label", "value", "vs_normal"} <= set(d) for d in out["top_drivers"])


# ── service: fail-soft tiers ──────────────────────────────────────────────────


def test_service_heuristic_fallback_when_model_unavailable(monkeypatch):
    """Model/artifact down -> deterministic current-vol bucket, same vocab, no raise."""
    ml_regime.reset_cache()
    monkeypatch.setattr(
        ml_inference, "predict", lambda row: (_ for _ in ()).throw(RuntimeError("no model"))
    )
    out = ml_regime.get_regime(force_refresh=True, fetcher=_fetcher_from(_raw()))
    assert out["source"] == "heuristic_fallback"
    assert out["regime"] in ml_labels.CLASSES
    assert out["current_realized_vol"] is not None


def test_service_unavailable_when_data_down():
    """Even market data down -> source 'unavailable', never raises."""
    ml_regime.reset_cache()
    out = ml_regime.get_regime(force_refresh=True, fetcher=lambda symbol, start: None)
    assert out["source"] == "unavailable"
    assert out["regime"] is None


def test_endpoint_returns_envelope(test_client, monkeypatch):
    """GET /api/v1/ml/regime — public, 200, well-formed envelope (network mocked)."""
    canned = {
        "regime": "neutral",
        "confidence": 0.7,
        "class_probabilities": {"neutral": 0.7, "risk_on": 0.3},
        "top_drivers": [],
        "model_version": "regime-v1",
        "trained_at": "2026-06-22T00:00:00Z",
        "training_window": {"rows": 3500},
        "source": "model",
        "last_updated": "2026-06-22",
        "data_coverage": {"sources_present": ["spy", "vix"]},
    }
    monkeypatch.setattr(ml_regime, "get_regime", lambda **k: canned)
    resp = test_client.get("/api/v1/ml/regime")
    assert resp.status_code == 200
    body = resp.json()
    assert body["error"] is None
    assert body["data"]["regime"] == "neutral"
    assert body["data"]["source"] == "model"
