"""Model-card service + endpoint — the numbers must come from the committed
artifacts (never hand-typed) so the public page can't drift from validation."""

from __future__ import annotations

import json
from pathlib import Path

from backend.app.ml.config import load_config
from backend.app.services import model_card

_TRAIN_CONFIG = Path(__file__).resolve().parents[1] / "app" / "ml" / "configs" / "risk_today.yaml"


def _committed_artifacts() -> tuple[dict, dict]:
    meta = json.loads(model_card._META_PATH.read_text())
    validation = json.loads(model_card._VALIDATION_PATH.read_text())
    return meta, validation


def test_model_card_numbers_come_from_committed_artifacts():
    meta, validation = _committed_artifacts()
    metrics = meta["metrics"]
    aggregate = validation["aggregate_accuracy"]
    calibration = validation["calibration"]
    card = model_card.get_model_card()
    assert card["available"] is True
    assert card["model_version"] == meta["model_version"]
    # Compare to the committed machine artifacts, not hand-copied values. Weekly
    # retraining legitimately changes the holdout metric and feature ranking.
    assert card["cv_accuracy"] == round(aggregate["model"], 4)
    assert card["persistence_baseline_accuracy"] == round(aggregate["persistence"], 4)
    assert card["holdout_accuracy"] == round(metrics["holdout_accuracy"], 4)
    assert card["elevated_risk_auc"] == round(calibration["elevated_risk_auc"], 4)
    assert card["brier"] == round(calibration["brier"], 4)
    assert card["brier_base_rate"] == round(calibration["brier_base_rate"], 4)
    assert card["holdout_size"] == calibration["holdout_size"]
    assert len(card["calibration_bins"]) == len(calibration["bins"])
    assert card["classes"] == meta["classes"]
    assert len(card["features"]) == len(meta["feature_importances"])
    expected_top_feature = max(meta["feature_importances"], key=meta["feature_importances"].get)
    assert card["features"][0]["name"] == expected_top_feature


def test_committed_model_keeps_the_public_quality_floor():
    """Fail the retraining workflow before it commits a materially bad model."""
    _meta, validation = _committed_artifacts()
    calibration = validation["calibration"]
    assert calibration["holdout_size"] >= 500
    assert calibration["elevated_risk_auc"] >= 0.70
    assert calibration["brier"] < calibration["brier_base_rate"]


def test_headline_is_honest_and_composed_from_numbers():
    _meta, validation = _committed_artifacts()
    aggregate = validation["aggregate_accuracy"]
    card = model_card.get_model_card()
    h = card["headline"].lower()
    assert "probability-ranking signal" in h
    assert "not a price or return forecast" in h
    # The verdict follows the committed numbers (the weekly retrain regenerates
    # validation_report.json), and the numbers are composed in, not hand-typed.
    beats = round(aggregate["model"], 3) > round(aggregate["persistence"], 3)
    verdict = "beats a persistence baseline" if beats else "does not beat a persistence baseline"
    assert verdict in h
    assert f"{aggregate['model']:.3f}" in card["headline"]
    assert f"{aggregate['persistence']:.3f}" in card["headline"]


def _card_with_accuracy(monkeypatch, model: float, persistence: float) -> dict:
    meta, validation = _committed_artifacts()
    validation = json.loads(json.dumps(validation))
    validation["aggregate_accuracy"]["model"] = model
    validation["aggregate_accuracy"]["persistence"] = persistence
    loaded = {model_card._META_PATH: meta, model_card._VALIDATION_PATH: validation}
    monkeypatch.setattr(model_card, "_load", lambda path: loaded[path])
    return model_card.get_model_card()


def test_headline_says_beats_when_model_beats_persistence(monkeypatch):
    card = _card_with_accuracy(monkeypatch, model=0.561, persistence=0.523)
    h = card["headline"].lower()
    assert "beats a persistence baseline" in h
    assert "does not beat" not in h
    assert "0.561" in card["headline"] and "0.523" in card["headline"]
    assert "probability-ranking signal" in h
    # No other surface may keep claiming the opposite.
    for text in [*card["not_for"], *card["limitations"]]:
        assert "does not beat" not in text.lower()
        assert "loses to" not in text.lower()


def test_headline_says_does_not_beat_when_model_trails_persistence(monkeypatch):
    card = _card_with_accuracy(monkeypatch, model=0.490, persistence=0.523)
    h = card["headline"].lower()
    assert "does not beat a persistence baseline" in h
    assert any("does not beat" in lim.lower() for lim in card["limitations"])
    assert any("does not beat" in n.lower() for n in card["not_for"])


def test_a_display_tie_is_not_reported_as_beating(monkeypatch):
    card = _card_with_accuracy(monkeypatch, model=0.5231, persistence=0.5229)
    assert "does not beat a persistence baseline" in card["headline"].lower()


def test_intended_use_and_limitations_present():
    card = model_card.get_model_card()
    assert "probability-ranking" in card["intended_use"].lower()
    assert any("persistence" in lim.lower() for lim in card["limitations"])
    assert card["not_for"]  # explicit "not a forecast / not advice" list
    assert "fear & greed" in card["excluded_signals"].lower()


def test_fail_soft_when_artifacts_missing(monkeypatch):
    monkeypatch.setattr(model_card, "_META_PATH", Path("/nonexistent/regime_meta.json"))
    monkeypatch.setattr(model_card, "_VALIDATION_PATH", Path("/nonexistent/validation.json"))
    card = model_card.get_model_card()
    assert card["available"] is False
    # Prose survives; numbers are null (never a crash).
    assert card["intended_use"]
    assert card["cv_accuracy"] is None


def test_endpoint_envelope(test_client):
    resp = test_client.get("/api/v1/ml/model_card")
    assert resp.status_code == 200
    body = resp.json()
    assert body["error"] is None
    _meta, validation = _committed_artifacts()
    # Pinned to the YAML's semantic version, not the meta: a retrain run without
    # --config stamps the code default ("regime-v1") and must fail here.
    assert body["data"]["model_version"] == load_config(_TRAIN_CONFIG).model_version
    assert body["data"]["persistence_baseline_accuracy"] == round(
        validation["aggregate_accuracy"]["persistence"], 4
    )
    assert body["meta"]["request_id"]
