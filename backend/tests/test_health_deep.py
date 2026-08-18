"""Deep readiness probe (`GET /api/v1/health?deep=1`) — contract tests.

Covers the full failure matrix the runbook cares about: success, Supabase
timeout, 401/403 (reachable), 5xx (unreachable), missing config — plus the
guarantees that the SHALLOW path is byte-compatible with its old contract and
that no secret value can leak into a health body.
"""

from __future__ import annotations

import urllib.error

import pytest
from fastapi.testclient import TestClient

from backend.app.api.v1 import health as hmod
from backend.app.main import create_app


class _Resp:
    def __init__(self, status: int = 200):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("MINDMARKET_ENV", "dev")
    monkeypatch.delenv("MINDMARKET_ALLOWED_ORIGINS", raising=False)
    from backend.app.core.config import reset_settings_cache

    reset_settings_cache()
    yield TestClient(create_app())
    reset_settings_cache()


@pytest.fixture()
def full_config(monkeypatch):
    """Everything the deep probe treats as REQUIRED config."""
    monkeypatch.setenv("SUPABASE_URL", "https://unit-test.supabase.co")
    monkeypatch.setenv("SUPABASE_JWT_SECRET", "unit-test-secret")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "sb_secret_test_value_never_shown")
    from backend.app.core.config import reset_settings_cache

    reset_settings_cache()


# keep the old fixture name used below
@pytest.fixture()
def service_key(full_config):
    return None


# ── shallow path: original contract untouched ──────────────────────


def test_shallow_health_contract_unchanged(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["status"] == "ok"
    assert d["modules_importable"] is True
    assert "checks" not in d  # deep view is opt-in only
    assert "deep" not in d


def test_head_still_answers_200_bodyless(client):
    r = client.head("/api/v1/health")
    assert r.status_code == 200
    assert r.content == b""


def test_shallow_health_never_degrades_on_supabase_outage(client, monkeypatch):
    """The Docker healthcheck consumes the SHALLOW path — a Supabase blip must
    not flip the container unhealthy (restart-looping can't fix an upstream)."""

    def _boom(*a, **k):
        raise TimeoutError("blackhole")

    monkeypatch.setattr(hmod.urllib.request, "urlopen", _boom)
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "ok"


# ── deep path ──────────────────────────────────────────────────────


def test_deep_success_returns_ok_with_categorized_checks(client, monkeypatch, service_key):
    monkeypatch.setattr(hmod.urllib.request, "urlopen", lambda url, timeout: _Resp(200))
    r = client.get("/api/v1/health?deep=1")
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["deep"] is True
    assert d["status"] == "ok"
    by = {c["name"]: c for c in d["checks"]}
    assert by["supabase_rest"]["ok"] is True
    assert by["supabase_rest"]["category"] == "dependency"
    assert by["supabase_rest"]["latency_ms"] >= 0
    assert by["auth_config"]["ok"] is True
    assert by["service_role_config"]["ok"] is True
    assert by["core_modules"]["category"] == "runtime"


def test_deep_timeout_degrades_to_503(client, monkeypatch, service_key):
    def _timeout(url, timeout):
        assert timeout == pytest.approx(2.0)  # the probe is timeboxed
        raise TimeoutError("no route")

    monkeypatch.setattr(hmod.urllib.request, "urlopen", _timeout)
    r = client.get("/api/v1/health?deep=1")
    assert r.status_code == 503
    d = r.json()["data"]
    assert d["status"] == "degraded"
    probe = next(c for c in d["checks"] if c["name"] == "supabase_rest")
    assert probe["ok"] is False
    assert probe["reason"] == "TimeoutError"  # class name only — no raw text


@pytest.mark.parametrize("code", [401, 403])
def test_deep_auth_status_still_proves_reachability(client, monkeypatch, service_key, code):
    def _httperr(url, timeout):
        raise urllib.error.HTTPError(url, code, "denied", None, None)

    monkeypatch.setattr(hmod.urllib.request, "urlopen", _httperr)
    r = client.get("/api/v1/health?deep=1")
    assert r.status_code == 200  # 401/403 = Supabase is UP and routing
    probe = next(c for c in r.json()["data"]["checks"] if c["name"] == "supabase_rest")
    assert probe["ok"] is True
    assert probe["status_class"] == "4xx"


def test_deep_5xx_from_supabase_degrades_to_503(client, monkeypatch, service_key):
    def _httperr(url, timeout):
        raise urllib.error.HTTPError(url, 502, "bad gateway", None, None)

    monkeypatch.setattr(hmod.urllib.request, "urlopen", _httperr)
    r = client.get("/api/v1/health?deep=1")
    assert r.status_code == 503
    probe = next(c for c in r.json()["data"]["checks"] if c["name"] == "supabase_rest")
    assert probe["ok"] is False
    assert probe["status_class"] == "5xx"


def test_deep_missing_service_role_config_degrades(client, monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://unit-test.supabase.co")
    monkeypatch.setenv("SUPABASE_JWT_SECRET", "unit-test-secret")
    monkeypatch.delenv("SUPABASE_SERVICE_KEY", raising=False)
    from backend.app.core.config import reset_settings_cache

    reset_settings_cache()
    monkeypatch.setattr(hmod.urllib.request, "urlopen", lambda url, timeout: _Resp(200))
    r = client.get("/api/v1/health?deep=1")
    assert r.status_code == 503
    by = {c["name"]: c for c in r.json()["data"]["checks"]}
    assert by["service_role_config"]["ok"] is False
    # the OTHER required checks pass — the degradation is attributable
    assert by["auth_config"]["ok"] is True


def test_deep_optional_config_missing_does_not_degrade(client, monkeypatch, service_key):
    monkeypatch.delenv("MASSIVE_API_KEY", raising=False)
    monkeypatch.setattr(hmod.urllib.request, "urlopen", lambda url, timeout: _Resp(200))
    r = client.get("/api/v1/health?deep=1")
    assert r.status_code == 200  # optional rows inform, never degrade
    by = {c["name"]: c for c in r.json()["data"]["checks"]}
    assert by["market_data_config"]["required"] is False


def test_deep_body_never_leaks_secret_values(client, monkeypatch, service_key):
    monkeypatch.setattr(hmod.urllib.request, "urlopen", lambda url, timeout: _Resp(200))
    body = client.get("/api/v1/health?deep=1").text
    assert "sb_secret_test_value_never_shown" not in body
    # No raw URLs either (the JWKS url embeds the project ref).
    assert ".well-known" not in body


# ── llm_model: presence is not readiness ───────────────────────────


def test_deep_reports_a_retired_llm_model_without_flipping_readiness(
    client, monkeypatch, service_key
):
    """On 2026-07-25 the provider retired the model name we send. The key
    stayed valid, so `llm_config` was green while every AI surface fell back to
    templates — nobody noticed for three weeks.

    The row must therefore be visibly NOT ok, and readiness must stay 200:
    degrading to deterministic templates is documented product behaviour, so an
    LLM problem is not an outage.
    """
    monkeypatch.setattr(hmod.urllib.request, "urlopen", lambda url, timeout: _Resp(200))
    monkeypatch.setenv("DEEPSEEK_API_KEY", "unit-test-key")
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-chat")
    from backend.app.core.config import reset_settings_cache
    from backend.app.services import llm_readiness

    reset_settings_cache()
    llm_readiness.reset_cache()
    monkeypatch.setattr(
        llm_readiness, "_deepseek_model_ids", lambda _s: ["deepseek-v4-flash", "deepseek-v4-pro"]
    )
    monkeypatch.setattr(llm_readiness, "_deepseek_answers", lambda _s, _m: (False, "HTTPError"))

    r = client.get("/api/v1/health?deep=1")
    assert r.status_code == 200, r.json()
    d = r.json()["data"]
    assert d["status"] == "ok"  # informational: AI degradation is not an outage
    row = {c["name"]: c for c in d["checks"]}["llm_model"]
    assert row["ok"] is False
    assert row["state"] == "model_retired"
    assert row["action_required"] is True
    assert row["required"] is False
    assert "deepseek-v4-flash" in row["detail"]
    llm_readiness.reset_cache()


def test_deep_omits_the_llm_row_when_no_provider_key_is_set(client, monkeypatch, service_key):
    """`llm_config` already reports the missing key; a second row saying the
    same thing is noise."""
    monkeypatch.setattr(hmod.urllib.request, "urlopen", lambda url, timeout: _Resp(200))
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    from backend.app.core.config import reset_settings_cache

    reset_settings_cache()

    r = client.get("/api/v1/health?deep=1")
    assert r.status_code == 200
    names = [c["name"] for c in r.json()["data"]["checks"]]
    assert "llm_model" not in names
    assert "llm_config" in names
