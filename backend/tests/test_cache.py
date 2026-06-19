"""JSON cache + cache keys: hit / miss / TTL / delete / get_or_set, the Redis
backend path + its fail-soft behavior, the Redis-unavailable in-process
fallback, hit/miss/set/error metrics, and secret-safe namespaced keys."""

from __future__ import annotations

import time

import pytest

from backend.app.services import cache as cachemod
from backend.app.services import cache_keys
from backend.app.services.cache import InProcessBackend, JsonCache, RedisBackend


@pytest.fixture(autouse=True)
def _reset_stats():
    cachemod.reset_stats()
    yield
    cachemod.reset_stats()


@pytest.fixture
def mem_cache():
    return JsonCache(backend=InProcessBackend(), default_ttl=60)


# ── core get / set / delete + metrics ───────────────────────────────────────


def test_set_get_roundtrip_records_hit_and_set(mem_cache):
    mem_cache.set("k", {"a": 1, "b": [2, 3]})
    assert mem_cache.get("k") == {"a": 1, "b": [2, 3]}
    stats = cachemod.get_stats()
    assert stats["set"] == 1 and stats["hit"] == 1 and stats["miss"] == 0


def test_miss_returns_none_and_records_miss(mem_cache):
    assert mem_cache.get("absent") is None
    assert cachemod.get_stats()["miss"] == 1


def test_delete_removes_and_records_delete(mem_cache):
    mem_cache.set("k", 42)
    mem_cache.delete("k")
    assert mem_cache.get("k") is None
    s = cachemod.get_stats()
    assert s["delete"] == 1 and s["miss"] == 1


def test_falsy_non_none_values_round_trip(mem_cache):
    mem_cache.set("zero", 0)
    mem_cache.set("empty", [])
    mem_cache.set("false", False)
    assert mem_cache.get("zero") == 0
    assert mem_cache.get("empty") == []
    assert mem_cache.get("false") is False


# ── TTL expiry ──────────────────────────────────────────────────────────────


def test_ttl_expiry(mem_cache):
    mem_cache.set("k", "v", ttl=0.05)
    assert mem_cache.get("k") == "v"  # fresh
    time.sleep(0.06)
    assert mem_cache.get("k") is None  # expired → miss
    assert cachemod.get_stats()["hit"] == 1 and cachemod.get_stats()["miss"] == 1


# ── get_or_set ──────────────────────────────────────────────────────────────


def test_get_or_set_computes_once_then_caches(mem_cache):
    calls = {"n": 0}

    def producer():
        calls["n"] += 1
        return {"computed": calls["n"]}

    first = mem_cache.get_or_set("k", producer)
    second = mem_cache.get_or_set("k", producer)
    assert first == {"computed": 1} and second == {"computed": 1}
    assert calls["n"] == 1  # producer ran only on the miss


def test_get_or_set_does_not_cache_none(mem_cache):
    calls = {"n": 0}

    def producer():
        calls["n"] += 1
        return None

    mem_cache.get_or_set("k", producer)
    mem_cache.get_or_set("k", producer)
    assert calls["n"] == 2  # None is treated as absent → recomputed


# ── serialization fail-soft ─────────────────────────────────────────────────


def test_unserializable_value_records_error_not_raise(mem_cache):
    circular: dict = {}
    circular["self"] = circular  # circular ref → json.dumps raises even with default=str
    mem_cache.set("k", circular)  # must not raise
    assert mem_cache.get("k") is None  # nothing was cached
    assert cachemod.get_stats()["error"] >= 1


# ── Redis backend path + fail-soft ──────────────────────────────────────────


class _FakeRedis:
    """Minimal redis-py surface: get/set(ex=)/delete/ping over a dict."""

    def __init__(self):
        self.store: dict[str, bytes] = {}

    def get(self, key):
        return self.store.get(key)

    def set(self, key, payload, ex=None):
        self.store[key] = payload.encode() if isinstance(payload, str) else payload

    def delete(self, key):
        self.store.pop(key, None)

    def ping(self):
        return True


def test_redis_backend_roundtrip():
    jc = JsonCache(backend=RedisBackend(_FakeRedis()), default_ttl=30)
    assert jc.backend_name == "redis"
    jc.set("k", {"x": 1})
    assert jc.get("k") == {"x": 1}  # decodes bytes payload from the client


def test_redis_backend_error_is_failsoft():
    class _Boom(_FakeRedis):
        def get(self, key):
            raise RuntimeError("connection reset")

    jc = JsonCache(backend=RedisBackend(_Boom()))
    assert jc.get("k") is None  # swallowed → miss
    assert cachemod.get_stats()["error"] >= 1


# ── Redis-unavailable fallback ──────────────────────────────────────────────


def test_no_url_selects_in_process():
    assert isinstance(cachemod._select_backend(""), InProcessBackend)


def test_unreachable_redis_falls_back_to_in_process(monkeypatch):
    # Simulate the redis lib being present but the server unreachable.
    monkeypatch.setattr(cachemod, "_build_redis_backend", lambda url: None)
    backend = cachemod._select_backend("redis://localhost:6390/0")
    assert isinstance(backend, InProcessBackend)


def test_default_cache_uses_in_process_without_redis(monkeypatch):
    # No REDIS_URL configured → the auto-selected backend is in-process and the
    # cache still works end to end.
    monkeypatch.setattr(cachemod, "_select_backend", lambda url: InProcessBackend())
    cachemod.reset_cache()
    jc = cachemod.get_cache()
    assert jc.backend_name == "memory"
    jc.set("k", "v")
    assert jc.get("k") == "v"
    cachemod.reset_cache()


# ── cache_keys: stable, namespaced, secret-safe ─────────────────────────────


def test_stable_hash_is_deterministic_and_order_independent():
    a = cache_keys.stable_hash("AAPL", {"wacc": 0.09, "tg": 0.025})
    b = cache_keys.stable_hash("AAPL", {"tg": 0.025, "wacc": 0.09})  # dict order flipped
    assert a == b
    assert a != cache_keys.stable_hash("MSFT", {"wacc": 0.09, "tg": 0.025})
    assert len(a) == 16  # default truncation


def test_make_key_is_namespaced_and_hashes_parts():
    key = cache_keys.make_key("research:dcf", "AAPL", {"years": 5})
    assert key.startswith("mm:research:dcf:")
    assert "AAPL" not in key  # the part is hashed, not embedded


def test_make_key_never_leaks_a_secret():
    secret = "sk-ant-supersecret-token-value"
    key = cache_keys.make_key("llm", secret, "prompt")
    assert secret not in key and "supersecret" not in key


def test_make_key_sanitizes_namespace():
    assert cache_keys.make_key("Weird NS!!", "x").startswith("mm:weird-ns:")
