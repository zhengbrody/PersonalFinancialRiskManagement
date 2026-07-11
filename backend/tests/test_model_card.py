"""Model-card service + endpoint — the numbers must come from the committed
artifacts (never hand-typed) so the public page can't drift from validation."""

from __future__ import annotations

from pathlib import Path

from backend.app.services import model_card


def test_model_card_numbers_come_from_committed_artifacts():
    card = model_card.get_model_card()
    assert card["available"] is True
    assert card["model_version"] == "regime-v1.1.0"
    # The honest, load-bearing numbers (from validation_report.json + regime_meta.json).
    assert card["cv_accuracy"] == 0.4896
    assert card["persistence_baseline_accuracy"] == 0.523  # the baseline it LOSES to
    assert card["holdout_accuracy"] == 0.5142
    assert card["elevated_risk_auc"] == 0.7701  # the signal that survives
    assert card["brier"] == 0.1042
    assert card["brier_base_rate"] == 0.1133
    assert card["holdout_size"] == 706
    assert len(card["calibration_bins"]) == 10
    assert card["classes"] == ["risk_on", "neutral", "volatile", "stress"]
    assert len(card["features"]) == 15  # sorted by importance
    assert card["features"][0]["name"] == "vol_63d"  # most important


def test_headline_is_honest_and_composed_from_numbers():
    card = model_card.get_model_card()
    h = card["headline"].lower()
    assert "does not beat a persistence baseline" in h
    assert "probability-ranking signal" in h
    assert "not a price or return forecast" in h
    # and it names the actual numbers (composed, not hand-typed).
    assert "0.490" in card["headline"] and "0.523" in card["headline"]


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
    assert body["data"]["model_version"] == "regime-v1.1.0"
    assert body["data"]["persistence_baseline_accuracy"] == 0.523
    assert body["meta"]["request_id"]
