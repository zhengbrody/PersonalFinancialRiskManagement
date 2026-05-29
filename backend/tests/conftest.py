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


@pytest.fixture
def fake_portfolio_mutations(monkeypatch):
    """Patch the three mutation helpers in ``libs.auth.portfolios``
    used by /api/v1/portfolios POST/PATCH/DELETE.

    Tracks ``calls`` per function so tests can assert exact arguments
    (especially that ``access_token`` is forwarded verbatim — the RLS
    contract). Each stub returns the row passed via ``set_return``."""

    class _MutStub:
        def __init__(self) -> None:
            self.returns: dict | None = None
            self.calls: list[dict] = []
            self.raise_on_call: Exception | None = None

        def set_return(self, row: dict) -> None:
            self.returns = row

        def raise_with(self, exc: Exception) -> None:
            self.raise_on_call = exc

    create = _MutStub()
    update = _MutStub()
    delete = _MutStub()

    def _create(**kwargs):
        create.calls.append(kwargs)
        if create.raise_on_call is not None:
            raise create.raise_on_call
        return dict(create.returns or {})

    def _update(portfolio_id, **kwargs):
        update.calls.append({"portfolio_id": portfolio_id, **kwargs})
        if update.raise_on_call is not None:
            raise update.raise_on_call
        return dict(update.returns or {})

    def _delete(portfolio_id, access_token=None):
        delete.calls.append({"portfolio_id": portfolio_id, "access_token": access_token})
        if delete.raise_on_call is not None:
            raise delete.raise_on_call
        return None

    import libs.auth.portfolios as _portfolios_mod

    monkeypatch.setattr(_portfolios_mod, "create_portfolio", _create)
    monkeypatch.setattr(_portfolios_mod, "update_portfolio", _update)
    monkeypatch.setattr(_portfolios_mod, "delete_portfolio", _delete)
    return {"create": create, "update": update, "delete": delete}


@pytest.fixture
def fake_portfolios(monkeypatch):
    """Patch ``libs.auth.portfolios.list_portfolios`` so route tests
    don't reach the real Supabase project.

    Usage::

        def test_x(test_client, mint_token, fake_portfolios):
            fake_portfolios.set([{"id": "p1", ...}])
            resp = test_client.get(...)
    """

    class _Stub:
        def __init__(self) -> None:
            self.rows: list[dict] = []
            self.calls: list[str | None] = []
            self.raise_on_call: Exception | None = None

        def set(self, rows: list[dict]) -> None:
            self.rows = rows

        def raise_with(self, exc: Exception) -> None:
            self.raise_on_call = exc

        def __call__(self, access_token=None):
            self.calls.append(access_token)
            if self.raise_on_call is not None:
                raise self.raise_on_call
            return list(self.rows)

    stub = _Stub()
    import libs.auth.portfolios as _portfolios_mod

    monkeypatch.setattr(_portfolios_mod, "list_portfolios", stub)
    return stub
