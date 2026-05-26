"""Tests for libs/auth/saved_insights.py.

We don't have a real Supabase in CI, so we mock the client's
``.table().insert().execute()`` chain and verify:
  - payload sanitisation (required fields, length caps, numeric clamps)
  - error surfacing on insert failure
  - empty-state fallback for anonymous users on list_insights
  - delete is idempotent and routes through the authed client
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from libs.auth import saved_insights as si
from libs.auth.client import AuthError


def _stub_client(insert_payload_holder: dict | None = None):
    """Build a fake Supabase client whose insert captures the payload.

    Returns (client, last_payload_holder) where last_payload_holder
    is a dict that gets {"payload": ..., "table": ...} written into
    it on every insert/delete/select call.
    """
    holder = insert_payload_holder if insert_payload_holder is not None else {}

    class _Query:
        def __init__(self, table: str):
            self._table = table
            self._action: str | None = None
            self._payload = None
            self._filters: list[tuple[str, str]] = []
            self._limit: int | None = None
            self._order = None

        def insert(self, payload):
            self._action = "insert"
            self._payload = payload
            return self

        def select(self, *_a, **_kw):
            self._action = "select"
            return self

        def delete(self):
            self._action = "delete"
            return self

        def eq(self, col, val):
            self._filters.append((col, val))
            return self

        def order(self, *_a, **_kw):
            return self

        def limit(self, n):
            self._limit = n
            return self

        def execute(self):
            holder["table"] = self._table
            holder["action"] = self._action
            holder["payload"] = self._payload
            holder["filters"] = list(self._filters)
            if self._action == "insert":
                # Echo back with a synthetic id so the caller's "no row"
                # branch isn't tripped.
                return SimpleNamespace(data=[{"id": "test-id", **(self._payload or {})}])
            if self._action == "select":
                return SimpleNamespace(data=[])
            return SimpleNamespace(data=[])

    client = MagicMock()
    client.table.side_effect = lambda name: _Query(name)
    return client, holder


# ── save_insight ────────────────────────────────────────────────────


def test_save_insight_requires_non_empty_title(monkeypatch):
    client, _ = _stub_client()
    monkeypatch.setattr(si, "_authed_client", lambda: client)
    with pytest.raises(ValueError, match="title"):
        si.save_insight(page="overview", title="   ", content="body")


def test_save_insight_requires_non_empty_content(monkeypatch):
    client, _ = _stub_client()
    monkeypatch.setattr(si, "_authed_client", lambda: client)
    with pytest.raises(ValueError, match="content"):
        si.save_insight(page="overview", title="t", content="")


def test_save_insight_sanitises_numeric_inputs(monkeypatch):
    client, holder = _stub_client()
    monkeypatch.setattr(si, "_authed_client", lambda: client)
    si.save_insight(
        page="overview",
        title="Risk Digest",
        content="body",
        provider="anthropic",
        model="claude-sonnet-4-5",
        tokens_in=-10,
        tokens_out=42,
        cost_usd=float("nan"),
        metadata={"k": "v"},
    )
    payload = holder["payload"]
    assert payload["tokens_in"] == 0  # negative clamped
    assert payload["tokens_out"] == 42
    assert payload["cost_usd"] == 0.0  # NaN scrubbed
    assert payload["metadata"] == {"k": "v"}


def test_save_insight_caps_text_lengths(monkeypatch):
    client, holder = _stub_client()
    monkeypatch.setattr(si, "_authed_client", lambda: client)
    si.save_insight(
        page="x" * 200,
        title="t" * 500,
        content="c" * 30_000,
    )
    p = holder["payload"]
    assert len(p["page"]) == 60
    assert len(p["title"]) == 200
    assert len(p["content"]) == 20_000


def test_save_insight_wraps_db_error_in_autherror(monkeypatch):
    """An explicit user action must surface failure, not swallow it."""
    client = MagicMock()
    client.table.return_value.insert.return_value.execute.side_effect = RuntimeError("boom")
    monkeypatch.setattr(si, "_authed_client", lambda: client)
    with pytest.raises(AuthError, match="Could not save"):
        si.save_insight(page="overview", title="t", content="c")


# ── list_insights / delete_insight ──────────────────────────────────


def test_list_insights_returns_empty_for_anon_user(monkeypatch):
    def _raise():
        raise AuthError("anon")

    monkeypatch.setattr(si, "_authed_client", _raise)
    assert si.list_insights() == []


def test_list_insights_returns_empty_on_db_error(monkeypatch, caplog):
    client = MagicMock()
    client.table.side_effect = RuntimeError("relation does not exist")
    monkeypatch.setattr(si, "_authed_client", lambda: client)
    assert si.list_insights() == []


def test_list_insights_limit_zero_short_circuits(monkeypatch):
    called: list[bool] = []
    monkeypatch.setattr(
        si, "_authed_client", lambda: called.append(True) or MagicMock()  # noqa: E501
    )
    assert si.list_insights(limit=0) == []
    assert called == []


def test_delete_insight_requires_id(monkeypatch):
    monkeypatch.setattr(si, "_authed_client", lambda: MagicMock())
    with pytest.raises(ValueError, match="insight_id"):
        si.delete_insight("")


def test_delete_insight_returns_true_on_success(monkeypatch):
    client, holder = _stub_client()
    monkeypatch.setattr(si, "_authed_client", lambda: client)
    assert si.delete_insight("abc-123") is True
    assert holder["action"] == "delete"
    assert ("id", "abc-123") in holder["filters"]


def test_delete_insight_returns_false_on_db_error(monkeypatch):
    client = MagicMock()
    client.table.return_value.delete.return_value.eq.return_value.execute.side_effect = (
        RuntimeError("boom")
    )
    monkeypatch.setattr(si, "_authed_client", lambda: client)
    assert si.delete_insight("abc-123") is False
