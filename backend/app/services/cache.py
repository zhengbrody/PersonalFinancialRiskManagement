"""JSON cache abstraction — Redis when configured, in-process TTL+LRU fallback.

A small, fail-soft cache that stores JSON-serializable values:

* **Backend** is chosen ONCE at construction. If ``REDIS_URL`` is set, the
  ``redis`` package is installed, AND the server answers a ``ping``, the cache
  uses Redis (shared across workers / survives a deploy). Otherwise it falls
  back to a thread-safe in-process TTL+LRU store — the same trade-off as every
  other ``services/`` cache on the single-worker t3.micro. So Redis is a pure
  upgrade: nothing breaks when it's absent.
* **Fail-soft** — every operation swallows backend/serialization errors (logs +
  records an ``error`` metric) and degrades to a miss/no-op. A cache must never
  take down the request path.
* **Metrics** — hit / miss / set / delete / error counters are exposed via
  :func:`get_stats` (precise + unit-testable) and mirrored into the live
  ``record_provider("cache", …)`` registry so the owner dashboard sees cache
  effectiveness.

No secrets: pair with :mod:`services.cache_keys` so identifying parts are hashed
into the key, and never cache a secret as a value (JSON values are stored as-is
in Redis, which other tooling may inspect).
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from ..core.config import get_settings
from . import metrics

_log = logging.getLogger(__name__)

_DEFAULT_TTL = 300  # 5 minutes
_MAX_ENTRIES = 1024  # in-process LRU bound
_PROVIDER = "cache"  # name under which cache events show in the live dashboard
# A cached value is kept in the backend this many × its logical TTL so it can be
# served STALE when a refresh fails (stale-on-error) — long after it's "expired"
# for freshness purposes but before the backend finally evicts it.
_STALE_FACTOR = 12


def _iso(epoch: Optional[float]) -> Optional[str]:
    """Epoch seconds → ISO8601 UTC string (for cache provenance), or None."""
    if epoch is None:
        return None
    try:
        return datetime.fromtimestamp(float(epoch), tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return None


@dataclass
class CacheResult:
    """The outcome of a :meth:`JsonCache.fetch` — the value plus provenance the
    caller can surface (cache_hit / fetched_at / expires_at / stale)."""

    value: Any
    cache_hit: bool
    fetched_at: Optional[str]
    expires_at: Optional[str]
    stale: bool


# ── metrics (the explicit hit / miss / set / delete / error counters) ───────


class _Stats:
    """Thread-safe event counters, mirrored into the live metrics registry."""

    _MIRROR = {"hit": "cache_hit", "miss": "empty", "set": "ok", "error": "error"}

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._c = {"hit": 0, "miss": 0, "set": 0, "delete": 0, "error": 0}

    def bump(self, event: str) -> None:
        with self._lock:
            if event in self._c:
                self._c[event] += 1
        outcome = self._MIRROR.get(event)
        if outcome:
            try:
                metrics.record_provider(_PROVIDER, outcome)
            except Exception:  # noqa: BLE001 - metrics must never raise into a caller
                pass

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return dict(self._c)

    def reset(self) -> None:
        with self._lock:
            for k in self._c:
                self._c[k] = 0


_stats = _Stats()


def get_stats() -> dict[str, int]:
    """Current hit / miss / set / delete / error counts (process-wide)."""
    return _stats.snapshot()


def reset_stats() -> None:
    """Test hook — zero the counters."""
    _stats.reset()


# ── backends (store opaque string payloads; the cache owns JSON (de)coding) ──


class InProcessBackend:
    """Thread-safe TTL + LRU string store (mirrors ``ai_cache``)."""

    name = "memory"

    def __init__(self, max_entries: int = _MAX_ENTRIES) -> None:
        self._lock = threading.Lock()
        self._max = int(max_entries)
        self._d: OrderedDict[str, tuple[float, str]] = OrderedDict()

    def get(self, key: str) -> Optional[str]:
        now = time.monotonic()
        with self._lock:
            entry = self._d.get(key)
            if entry is None:
                return None
            expires_at, payload = entry
            if now >= expires_at:
                del self._d[key]
                return None
            self._d.move_to_end(key)
            return payload

    def set(self, key: str, payload: str, ttl: float) -> None:
        with self._lock:
            self._d[key] = (time.monotonic() + max(0.0, float(ttl)), payload)
            self._d.move_to_end(key)
            while len(self._d) > self._max:
                self._d.popitem(last=False)

    def delete(self, key: str) -> None:
        with self._lock:
            self._d.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._d.clear()


class RedisBackend:
    """Thin wrapper over a redis client. ``ttl`` is whole seconds (SET EX)."""

    name = "redis"

    def __init__(self, client: Any) -> None:
        self._r = client

    def get(self, key: str) -> Optional[str]:
        v = self._r.get(key)
        if v is None:
            return None
        return v.decode("utf-8") if isinstance(v, (bytes, bytearray)) else str(v)

    def set(self, key: str, payload: str, ttl: float) -> None:
        seconds = int(ttl)
        if seconds > 0:
            self._r.set(key, payload, ex=seconds)
        else:
            self._r.set(key, payload)

    def delete(self, key: str) -> None:
        self._r.delete(key)


def _build_redis_backend(url: str) -> Optional[RedisBackend]:
    """Try to connect to Redis. Returns None (→ in-process fallback) when the
    ``redis`` package is missing or the server can't be reached."""
    try:
        import redis  # optional dependency
    except ImportError:
        _log.info("cache.redis_unavailable reason=not_installed")
        return None
    try:
        client = redis.Redis.from_url(url, socket_connect_timeout=1.0, socket_timeout=1.0)
        client.ping()
        _log.info("cache.redis_connected")
        return RedisBackend(client)
    except Exception as exc:  # noqa: BLE001 - any connect failure → fallback
        _log.warning("cache.redis_unavailable reason=%s", type(exc).__name__)
        return None


def _select_backend(redis_url: str) -> Any:
    """Redis when configured + reachable, else a fresh in-process store."""
    if redis_url:
        backend = _build_redis_backend(redis_url)
        if backend is not None:
            return backend
    return InProcessBackend()


# ── the cache ───────────────────────────────────────────────────────────────


class JsonCache:
    """A JSON value cache over a pluggable string backend. Construct without a
    backend to auto-select from settings (``REDIS_URL`` → Redis, else memory);
    pass ``backend=`` to inject one (tests, or a custom store)."""

    def __init__(self, *, backend: Any = None, default_ttl: float = _DEFAULT_TTL) -> None:
        self._backend = (
            backend if backend is not None else _select_backend(get_settings().redis_url)
        )
        self._default_ttl = float(default_ttl)

    @property
    def backend_name(self) -> str:
        return getattr(self._backend, "name", "unknown")

    def get(self, key: str) -> Any:
        """Return the cached JSON value, or ``None`` on a miss / any failure."""
        try:
            raw = self._backend.get(key)
        except Exception as exc:  # noqa: BLE001 - fail-soft → miss
            _log.warning("cache.get_failed key=%s err=%s", key, type(exc).__name__)
            _stats.bump("error")
            return None
        if raw is None:
            _stats.bump("miss")
            return None
        try:
            value = json.loads(raw)
        except (ValueError, TypeError):
            _log.warning("cache.decode_failed key=%s", key)
            _stats.bump("error")
            try:  # drop the poisoned entry so it can't keep failing
                self._backend.delete(key)
            except Exception:  # noqa: BLE001
                pass
            return None
        _stats.bump("hit")
        return value

    def set(self, key: str, value: Any, ttl: Optional[float] = None) -> None:
        """Cache ``value`` (must be JSON-serializable) under ``key`` with a TTL
        in seconds (default 5 min). Fail-soft: a non-serializable value or a
        backend error records an ``error`` and is otherwise a no-op."""
        try:
            payload = json.dumps(value, separators=(",", ":"), default=str)
        except (TypeError, ValueError) as exc:
            _log.warning("cache.encode_failed key=%s err=%s", key, type(exc).__name__)
            _stats.bump("error")
            return
        try:
            self._backend.set(key, payload, self._default_ttl if ttl is None else float(ttl))
            _stats.bump("set")
        except Exception as exc:  # noqa: BLE001 - fail-soft → no-op
            _log.warning("cache.set_failed key=%s err=%s", key, type(exc).__name__)
            _stats.bump("error")

    def delete(self, key: str) -> None:
        try:
            self._backend.delete(key)
            _stats.bump("delete")
        except Exception as exc:  # noqa: BLE001
            _log.warning("cache.delete_failed key=%s err=%s", key, type(exc).__name__)
            _stats.bump("error")

    def get_or_set(self, key: str, producer: Callable[[], Any], ttl: Optional[float] = None) -> Any:
        """Return the cached value, or compute it via ``producer()``, cache it,
        and return it. ``producer`` runs only on a miss; its exceptions
        propagate (a failed computation is never cached). A ``None`` result is
        treated as absent — returned but not cached (mirrors ``get`` semantics)."""
        cached = self.get(key)
        if cached is not None:
            return cached
        value = producer()
        if value is not None:
            self.set(key, value, ttl)
        return value

    def fetch(
        self,
        key: str,
        producer: Callable[[], Any],
        ttl: Optional[float] = None,
        *,
        stale_ttl: Optional[float] = None,
    ) -> CacheResult:
        """Read-through cache with **stale-on-error** + provenance.

        * Fresh hit (cached and within ``ttl``) → return it; ``producer`` is NOT
          called. ``cache_hit=True, stale=False``.
        * Stale/miss → call ``producer`` to refresh; on success cache + return it
          (``cache_hit=False``). If ``producer`` RAISES and a previously-cached
          value still exists, that value is returned marked ``stale=True`` rather
          than propagating the failure — so a provider blip degrades to slightly
          old data, not an error. With no prior value, the exception propagates.

        The value is held in the backend for ``stale_ttl`` (default
        ``ttl × _STALE_FACTOR``) so it survives well past its logical freshness to
        serve as the stale fallback.
        """
        ttl = self._default_ttl if ttl is None else float(ttl)
        backend_ttl = (
            float(stale_ttl) if stale_ttl is not None else max(ttl * _STALE_FACTOR, ttl + 3600)
        )
        now = time.time()

        env = self.get(key)
        has_env = isinstance(env, dict) and "v" in env and "expires_at" in env
        if has_env and now < float(env["expires_at"]):
            return CacheResult(
                env["v"], True, _iso(env.get("fetched_at")), _iso(env.get("expires_at")), False
            )

        try:
            value = producer()
        except Exception:
            if has_env:  # serve the stale copy rather than fail
                return CacheResult(
                    env["v"], True, _iso(env.get("fetched_at")), _iso(env.get("expires_at")), True
                )
            raise

        fetched_at, expires_at = now, now + ttl
        self.set(
            key, {"v": value, "fetched_at": fetched_at, "expires_at": expires_at}, ttl=backend_ttl
        )
        return CacheResult(value, False, _iso(fetched_at), _iso(expires_at), False)


# ── module-level default instance ────────────────────────────────────────────

_default: Optional[JsonCache] = None


def get_cache() -> JsonCache:
    """The process-wide default cache (backend auto-selected from settings)."""
    global _default
    if _default is None:
        _default = JsonCache()
    return _default


def reset_cache() -> None:
    """Test hook — drop the singleton (so the backend is re-selected) + stats."""
    global _default
    _default = None
    reset_stats()
