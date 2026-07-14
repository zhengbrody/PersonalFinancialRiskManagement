"""In-process TTL cache for AI responses, keyed by input hash.

Identical AI requests within the TTL window return the stored response
instead of re-hitting the LLM — the inputs (a FactPack, a metrics payload,
a chat message) fully determine the answer, so a repeat call buys nothing
but cost and latency. Used by ``/research/verdict``, ``/risk/explain`` and
``/copilot/ask``.

Design notes:
* In-proc only (single uvicorn worker on the t3.micro) — same trade-off as
  every other TTL cache in ``services/``. Entries die on deploy; that's fine
  for a 30–45 min response cache.
* Hits/misses are recorded in the live metrics registry (``record_provider``
  with name ``ai_cache``) so the owner dashboard shows cache effectiveness.
* A cache hit must never be billed: callers check the cache BEFORE the
  credit gate and skip cost recording on a hit.
* Only real AI output should be cached — deterministic/data-only fallbacks
  are cheap to recompute and caching them would mask a recovered LLM key.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from typing import Any

from . import metrics

_MAX_ENTRIES = 256


class AiResponseCache:
    """Thread-safe TTL + LRU-evicting cache for serialized AI responses."""

    def __init__(self, ttl_seconds: float, max_entries: int = _MAX_ENTRIES) -> None:
        self._ttl = float(ttl_seconds)
        self._max = int(max_entries)
        self._lock = threading.Lock()
        self._entries: OrderedDict[str, tuple[float, Any]] = OrderedDict()

    def get(self, key: str) -> Any | None:
        # Only hits and stores are recorded ("calls" = hits + stores), so the
        # admin table reads as a hit ratio rather than double-counting misses.
        now = time.time()
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            expires_at, value = entry
            if now >= expires_at:
                del self._entries[key]
                return None
            self._entries.move_to_end(key)
        metrics.record_provider("ai_cache", "cache_hit")
        return value

    def put(self, key: str, value: Any) -> None:
        with self._lock:
            self._entries[key] = (time.time() + self._ttl, value)
            self._entries.move_to_end(key)
            while len(self._entries) > self._max:
                self._entries.popitem(last=False)
        metrics.record_provider("ai_cache", "ok")

    def reset(self) -> None:
        with self._lock:
            self._entries.clear()


# Per-endpoint instances. TTLs follow the product rule "cache AI summaries by
# input hash for 30–60 minutes": research verdicts and risk diagnoses are
# stable for the trading session; chat answers fold in fresher evidence.
verdict_cache = AiResponseCache(ttl_seconds=45 * 60)
explain_cache = AiResponseCache(ttl_seconds=45 * 60)
ask_cache = AiResponseCache(ttl_seconds=30 * 60)


# ── per-user cache generation ────────────────────────────────────────────────
# The /ask key is an input HASH, so a user's entries can't be enumerated for
# targeted eviction. Instead, per-user keys fold in a monotonic generation
# counter; bumping it makes every previously-cached key for that user
# unreachable — exact O(1) invalidation. Used when the user changes/clears
# confirmed Copilot preferences (the cached answer folded the OLD preference
# evidence in and would contradict the new state for up to the TTL).
# In-proc like the caches themselves: both reset together on deploy/restart,
# and one int per preference-changing user per process is negligible.

_user_gen: dict[str, int] = {}
_gen_lock = threading.Lock()


def user_generation(user_id: str) -> int:
    return _user_gen.get(user_id or "", 0)


def bump_user_generation(user_id: str) -> None:
    """Invalidate every generation-keyed cache entry for this user."""
    if not user_id:
        return
    with _gen_lock:
        _user_gen[user_id] = _user_gen.get(user_id, 0) + 1


def reset_all() -> None:
    """Test hook."""
    for cache in (verdict_cache, explain_cache, ask_cache):
        cache.reset()
    with _gen_lock:
        _user_gen.clear()
