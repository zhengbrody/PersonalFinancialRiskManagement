"""Sentry wiring guardrails.

Production should capture real backend 500s, but local pytest/TestClient runs
must never emit to the production Sentry project, even when a developer shell
has production env vars loaded.
"""

from __future__ import annotations

import sys
import types


def test_sentry_init_is_disabled_under_pytest(monkeypatch):
    from backend.app.core.config import Settings
    from backend.app.main import _maybe_init_sentry

    calls: list[dict] = []

    fake_sentry = types.SimpleNamespace(init=lambda **kwargs: calls.append(kwargs))
    monkeypatch.setitem(sys.modules, "sentry_sdk", fake_sentry)
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "test_sentry_guard")

    _maybe_init_sentry(
        Settings(
            environment="production",
            sentry_dsn="https://public@example.ingest.sentry.io/1",
        )
    )

    assert calls == []


def test_yfinance_logger_is_quieted():
    import logging

    from backend.app.main import _quiet_expected_provider_noise

    _quiet_expected_provider_noise()

    assert logging.getLogger("yfinance").getEffectiveLevel() >= logging.CRITICAL
