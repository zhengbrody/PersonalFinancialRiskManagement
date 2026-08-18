"""The check that would have caught the 2026-07-25 silent AI outage.

Every other integration check asks "is a key present?" — which was TRUE
throughout that incident, because the key was fine and the model name had been
retired. These cases pin the distinction.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.app.services import llm_readiness


@pytest.fixture(autouse=True)
def _clean_cache():
    llm_readiness.reset_cache()
    yield
    llm_readiness.reset_cache()


def _fake_settings(monkeypatch, **over):
    """Settings is a frozen dataclass, so unit tests swap the module's
    ``get_settings`` (the convention in test_copilot_tools.py)."""
    base = dict(
        llm_provider="deepseek",
        deepseek_model="deepseek-chat",
        deepseek_api_key="k",
        deepseek_base_url="https://api.deepseek.example/v1",
        anthropic_api_key="",
    )
    base.update(over)
    monkeypatch.setattr(llm_readiness, "get_settings", lambda: SimpleNamespace(**base))


def test_configured_model_that_is_offered_is_ok(monkeypatch):
    _fake_settings(monkeypatch)
    monkeypatch.setattr(
        llm_readiness, "_deepseek_model_ids", lambda _s: ["deepseek-chat", "deepseek-v4-pro"]
    )
    r = llm_readiness.check()
    assert r.ok and r.state == "ok"
    assert "deepseek-chat" in r.detail


def test_unlisted_but_still_serving_is_deprecated_not_an_outage(monkeypatch):
    """The state DeepSeek is actually in (verified live 2026-08-17):
    `deepseek-chat` is gone from the model list but still answers. Calling that
    an outage would be a false alarm, and a check that cries wolf gets ignored
    — the exact failure mode this exists to prevent."""
    _fake_settings(monkeypatch)
    monkeypatch.setattr(
        llm_readiness, "_deepseek_model_ids", lambda _s: ["deepseek-v4-flash", "deepseek-v4-pro"]
    )
    monkeypatch.setattr(llm_readiness, "_deepseek_answers", lambda _s, _m: (True, ""))
    r = llm_readiness.check()
    assert r.state == "deprecated"
    assert r.ok, "it still serves — readiness must not go red for a whole migration"
    assert r.action_required, "but the migration is on the provider's clock"
    assert "deepseek-v4-flash" in r.detail


def test_unlisted_and_rejected_is_the_real_outage(monkeypatch):
    """The 2026-07-25 incident proper: a working key, a model the provider now
    refuses. The detail must NAME the replacements so the fix is obvious."""
    _fake_settings(monkeypatch)
    monkeypatch.setattr(
        llm_readiness, "_deepseek_model_ids", lambda _s: ["deepseek-v4-flash", "deepseek-v4-pro"]
    )
    monkeypatch.setattr(llm_readiness, "_deepseek_answers", lambda _s, _m: (False, "HTTPError"))
    r = llm_readiness.check()
    assert r.state == "model_retired"
    assert not r.ok and r.action_required
    assert "deepseek-v4-flash" in r.detail and "deepseek-v4-pro" in r.detail


def test_provider_outage_is_unknown_not_a_retirement(monkeypatch):
    """A network blip must not be reported as a retired model — and must not
    read as healthy either, because an unknown that looks green is exactly how
    the original failure hid."""
    _fake_settings(monkeypatch)

    def _boom(_s):
        raise TimeoutError("connection timed out")

    monkeypatch.setattr(llm_readiness, "_deepseek_model_ids", _boom)
    r = llm_readiness.check()
    assert r.state == "unreachable"
    assert not r.ok
    assert not r.action_required, "unknown is not a to-do; it's a retry"
    assert "TimeoutError" in r.detail


def test_no_key_is_not_configured_and_never_calls_out(monkeypatch):
    _fake_settings(monkeypatch, deepseek_api_key="")
    calls: list[int] = []
    monkeypatch.setattr(llm_readiness, "_deepseek_model_ids", lambda _s: calls.append(1) or ["x"])
    r = llm_readiness.check()
    assert r.state == "not_configured"
    assert calls == []


def test_result_is_cached_so_probes_are_free(monkeypatch):
    _fake_settings(monkeypatch)
    calls: list[int] = []

    def _once(_s):
        calls.append(1)
        return ["deepseek-chat"]

    monkeypatch.setattr(llm_readiness, "_deepseek_model_ids", _once)
    llm_readiness.check()
    llm_readiness.check()
    assert calls == [1], "second call must be served from cache"
    llm_readiness.check(force=True)
    assert calls == [1, 1], "force must bypass the cache"


def test_admin_status_lists_the_default_provider():
    """DeepSeek serves every AI request but was absent from the owner's system
    status, while the secondary provider was listed."""
    from backend.app.services import admin_status

    names = [row["name"] for row in admin_status.system_status(live=False)["integrations"]]
    assert "DeepSeek" in names
    assert "DeepSeek" in admin_status._LIVE_CHECKS
