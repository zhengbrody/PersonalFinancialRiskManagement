"""Shared pytest fixtures for the FastAPI backend.

The fixtures build a fresh ``TestClient`` per test via
``create_app()`` so we never leak state between tests (the
``Settings`` object is module-cached; tests that need a different
environment use ``reset_settings_cache`` + monkeypatched env vars).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Make the repo root importable so ``from backend.app.main import ...``
# works whether pytest is launched from the repo root or from
# ``backend/``.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


@pytest.fixture
def test_client(monkeypatch):
    """A fresh TestClient backed by a fresh ``create_app()``.

    We force the environment to ``dev`` so the default CORS allow-list
    kicks in and we don't accidentally require an empty production
    origins env var to pass.
    """
    monkeypatch.setenv("MINDMARKET_ENV", "dev")
    monkeypatch.delenv("MINDMARKET_ALLOWED_ORIGINS", raising=False)

    from fastapi.testclient import TestClient

    from backend.app.core.config import reset_settings_cache
    from backend.app.main import create_app

    reset_settings_cache()
    app = create_app()
    with TestClient(app) as client:
        yield client


@pytest.fixture
def jwt_secret(monkeypatch):
    """Set a fixed JWT secret + return it so tests can mint matching
    tokens via PyJWT."""
    secret = "test-secret-please-rotate"
    monkeypatch.setenv("SUPABASE_JWT_SECRET", secret)

    from backend.app.core.config import reset_settings_cache

    reset_settings_cache()
    return secret


@pytest.fixture
def mint_token(jwt_secret):
    """Factory: return a callable that builds a valid Supabase-style
    HS256 JWT signed with the test secret.

    Default claims pass require_user; override per call via kwargs."""
    import time

    import jwt as pyjwt

    def _mint(**overrides) -> str:
        claims = {
            "sub": "user-abc-123",
            "email": "owner@mindmarket.test",
            "aud": "authenticated",
            "exp": int(time.time()) + 600,
            "iat": int(time.time()),
        }
        claims.update(overrides)
        return pyjwt.encode(claims, jwt_secret, algorithm="HS256")

    return _mint


@pytest.fixture(autouse=True)
def _isolate_settings(monkeypatch):
    """Best-effort isolation: clear any in-process Settings cache after
    each test so a test that monkeypatched env vars doesn't poison the
    next one."""
    yield
    from backend.app.core import config as _cfg

    _cfg.reset_settings_cache()
