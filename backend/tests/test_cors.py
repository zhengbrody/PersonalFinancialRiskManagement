"""CORS allow-list contract.

Pinned because the dev → prod path is a common foot-gun: someone
adds ``allow_origins=["*"]`` for a quick local hack and it leaks
into production. The tests below mean any such change has to also
delete a test that says "don't do that".
"""

from __future__ import annotations

from fastapi.testclient import TestClient


def _preflight(client: TestClient, origin: str) -> dict[str, str]:
    """Issue an OPTIONS preflight and return the response headers
    dict so tests can read ``access-control-allow-origin``."""
    resp = client.options(
        "/api/v1/health",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "Authorization",
        },
    )
    return {k.lower(): v for k, v in resp.headers.items()}


def test_dev_allows_localhost_3000(test_client):
    headers = _preflight(test_client, "http://localhost:3000")
    assert headers.get("access-control-allow-origin") == "http://localhost:3000"


def test_dev_allows_127_0_0_1_3000(test_client):
    headers = _preflight(test_client, "http://127.0.0.1:3000")
    assert headers.get("access-control-allow-origin") == "http://127.0.0.1:3000"


def test_random_origin_is_not_allowed(test_client):
    """An untrusted origin must NOT get an allow-origin header back."""
    headers = _preflight(test_client, "https://evil.example.com")
    assert headers.get("access-control-allow-origin") != "https://evil.example.com"
    # Wildcard is never set either — the explicit list is the contract.
    assert headers.get("access-control-allow-origin") not in ("*", "https://evil.example.com")


def test_production_uses_explicit_allow_list(monkeypatch):
    """In prod the allow-list comes from ``MINDMARKET_ALLOWED_ORIGINS``
    only. No localhost fallback."""
    monkeypatch.setenv("MINDMARKET_ENV", "production")
    monkeypatch.setenv(
        "MINDMARKET_ALLOWED_ORIGINS",
        "https://mindmarket.app,https://www.mindmarket.app",
    )
    from backend.app.core.config import reset_settings_cache
    from backend.app.main import create_app

    reset_settings_cache()
    app = create_app()
    client = TestClient(app)

    # mindmarket.app is allowed
    h_ok = _preflight(client, "https://mindmarket.app")
    assert h_ok.get("access-control-allow-origin") == "https://mindmarket.app"

    # localhost in production is NOT allowed
    h_dev = _preflight(client, "http://localhost:3000")
    assert h_dev.get("access-control-allow-origin") != "http://localhost:3000"


def test_production_without_explicit_list_blocks_all(monkeypatch):
    """An empty allow-list in production is by design — better fail-
    closed than wildcard a misconfigured deploy."""
    monkeypatch.setenv("MINDMARKET_ENV", "production")
    monkeypatch.delenv("MINDMARKET_ALLOWED_ORIGINS", raising=False)
    from backend.app.core.config import reset_settings_cache
    from backend.app.main import create_app

    reset_settings_cache()
    client = TestClient(create_app())

    h = _preflight(client, "https://mindmarket.app")
    assert h.get("access-control-allow-origin") != "https://mindmarket.app"
