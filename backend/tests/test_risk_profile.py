from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.app.services import copilot_preferences, risk_profile


def _user():
    return SimpleNamespace(id="user-a", access_token="token-a")


def test_resolver_prefers_explicit_override(monkeypatch):
    monkeypatch.setattr(
        copilot_preferences,
        "get_confirmed_strict",
        lambda *_: {"risk_tolerance": 2, "confirmed_at": "2026-07-21T00:00:00Z"},
    )
    resolved = risk_profile.resolve_risk_preference(_user(), 5)
    assert (resolved.value, resolved.source) == (5, "request_override")


def test_resolver_uses_only_confirmed_preference(monkeypatch):
    monkeypatch.setattr(
        copilot_preferences,
        "get_confirmed_strict",
        lambda *_: {"risk_tolerance": 2, "confirmed_at": "2026-07-21T00:00:00Z"},
    )
    resolved = risk_profile.resolve_risk_preference(_user())
    assert (resolved.value, resolved.source) == (2, "confirmed")
    assert "2026-07-21" in resolved.cache_key


def test_resolver_falls_back_to_neutral(monkeypatch):
    monkeypatch.setattr(copilot_preferences, "get_confirmed_strict", lambda *_: None)
    resolved = risk_profile.resolve_risk_preference(_user())
    assert (resolved.value, resolved.source) == (3, "neutral_baseline")


def test_resolver_propagates_repository_failure(monkeypatch):
    def fail(*_args):
        raise RuntimeError("repository unavailable")

    monkeypatch.setattr(copilot_preferences, "get_confirmed_strict", fail)
    with pytest.raises(RuntimeError, match="repository unavailable"):
        risk_profile.resolve_risk_preference(_user())


def test_risk_fit_blocks_direction_when_confidence_does(monkeypatch):
    score = SimpleNamespace(
        risk_preference=3,
        metrics=SimpleNamespace(annual_volatility=0.30, beta_to_benchmark=1.4),
    )
    fit = risk_profile.build_risk_fit(score, SimpleNamespace(directional_allowed=False))
    assert fit["status"] == "unavailable"
    assert fit["signed_gap"] is None


def test_risk_fit_uses_preference_target_and_tolerance_band():
    score = SimpleNamespace(
        risk_preference=3,
        metrics=SimpleNamespace(annual_volatility=0.14, beta_to_benchmark=0.80),
    )
    aligned = risk_profile.build_risk_fit(score)
    assert aligned["status"] == "aligned"
    assert aligned["signed_gap"] == 0.0

    score.metrics.annual_volatility = 0.30
    score.metrics.beta_to_benchmark = 1.4
    assert risk_profile.build_risk_fit(score)["status"] == "above"
