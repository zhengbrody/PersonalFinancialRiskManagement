"""Deliberate 500s must reach Sentry; 4xx/503 must not.

Registering an exception handler for APIError means the exception never reaches
Sentry's ASGI middleware. Its "auto-captures unhandled 500s" therefore only
covered genuine crashes, while the 50 deliberate `raise server_error(...)`
sites returned a 500 to the user and left no Sentry event -- which is why the
two production bugs found in the 2026-09 sweep were dug out of container logs.
"""

import pytest

from backend.app.core import responses
from backend.app.core.responses import (
    APIError,
    server_error,
    service_unavailable,
    unprocessable,
)


class _FakeScope:
    def __init__(self):
        self.tags = {}

    def set_tag(self, k, v):
        self.tags[k] = v


class _FakeSentry:
    """Stands in for the sentry_sdk module."""

    def __init__(self, explode=False):
        self.captured = []
        self.scopes = []
        self._explode = explode

    def push_scope(self):
        if self._explode:
            raise RuntimeError("sentry is down")
        scope = _FakeScope()
        self.scopes.append(scope)

        class _Ctx:
            def __enter__(_self):
                return scope

            def __exit__(_self, *a):
                return False

        return _Ctx()

    def capture_exception(self, exc):
        if self._explode:
            raise RuntimeError("sentry is down")
        self.captured.append(exc)


@pytest.fixture
def fake_sentry(monkeypatch):
    fake = _FakeSentry()
    monkeypatch.setitem(__import__("sys").modules, "sentry_sdk", fake)
    return fake


def test_a_deliberate_500_is_reported(fake_sentry):
    exc = server_error("Market data fetch failed.")
    responses._report_if_our_bug(exc)
    assert fake_sentry.captured == [exc]
    assert fake_sentry.scopes[0].tags == {"error_code": "server_error"}


@pytest.mark.parametrize(
    "exc",
    [
        service_unavailable("Treasury unreachable."),
        unprocessable("Add a holding first."),
        APIError(429, "analysis_busy", "Another analysis is running."),
        APIError(401, "unauthorized", "Sign in."),
        APIError(404, "not_found", "No such portfolio."),
    ],
    ids=["503", "422", "429", "401", "404"],
)
def test_everything_that_is_not_our_bug_is_silent(fake_sentry, exc):
    responses._report_if_our_bug(exc)
    assert fake_sentry.captured == [], f"{exc.status} must not page"


def test_a_broken_reporter_never_breaks_the_response(monkeypatch):
    monkeypatch.setitem(__import__("sys").modules, "sentry_sdk", _FakeSentry(explode=True))
    responses._report_if_our_bug(server_error("boom"))  # must not raise


def test_missing_sentry_sdk_is_not_an_error(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def _no_sentry(name, *a, **k):
        if name == "sentry_sdk":
            raise ImportError("no sentry_sdk")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", _no_sentry)
    responses._report_if_our_bug(server_error("boom"))  # must not raise


def test_the_handler_reports_and_still_returns_the_envelope(fake_sentry):
    """End to end: a 500 through the real app is both reported and well-shaped."""
    import asyncio

    from starlette.requests import Request

    exc = server_error("Market data fetch failed.")
    scope = {"type": "http", "method": "GET", "path": "/x", "headers": []}
    resp = asyncio.run(responses.api_error_handler(Request(scope), exc))

    assert resp.status_code == 500
    assert fake_sentry.captured == [exc]


def test_a_dependency_raised_500_is_reported_too(fake_sentry):
    """HTTPException goes through a different handler; it must report as well."""
    import asyncio

    from fastapi import HTTPException
    from starlette.requests import Request

    scope = {"type": "http", "method": "GET", "path": "/x", "headers": []}
    resp = asyncio.run(responses.http_exception_handler(Request(scope), HTTPException(500, "boom")))
    assert resp.status_code == 500
    assert len(fake_sentry.captured) == 1


def test_a_dependency_raised_401_stays_silent(fake_sentry):
    import asyncio

    from fastapi import HTTPException
    from starlette.requests import Request

    scope = {"type": "http", "method": "GET", "path": "/x", "headers": []}
    asyncio.run(responses.http_exception_handler(Request(scope), HTTPException(401, "nope")))
    assert fake_sentry.captured == []
