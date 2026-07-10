"""Per-IP token-bucket rate limiting for PUBLIC endpoints.

In-process by design: the backend runs a single uvicorn worker on a small
box, so a shared store would be dead weight. Buckets prune themselves so an
address scan can't grow memory unboundedly.

Client identity: `CF-Connecting-IP` is used ONLY when the deployment asserts
Cloudflare-only ingress (settings.trust_cf_connecting_ip — prod's security
group admits only Cloudflare ranges, so the header cannot be forged there).
Anywhere else the header is attacker-controlled and is IGNORED in favor of
the direct peer / reverse-proxy address.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field


def client_ip(request, settings) -> str:
    """Best trustworthy client address for rate-limit keying."""
    if settings.trust_cf_connecting_ip:
        cf = (request.headers.get("cf-connecting-ip") or "").strip()
        if cf:
            return cf
    # Behind our own Caddy the peer is the proxy; X-Forwarded-For's FIRST hop
    # was appended by Caddy itself (client-supplied entries precede it, so
    # take the LAST — the only hop our own proxy vouches for).
    xff = (request.headers.get("x-forwarded-for") or "").strip()
    if xff:
        return xff.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"


@dataclass
class TokenBucket:
    """Classic token bucket per key. ``capacity`` = burst, ``refill_per_sec``
    = sustained rate. Thread-safe; prunes stale keys past ``max_keys``."""

    capacity: float = 5.0
    refill_per_sec: float = 1.0 / 20.0  # sustained: 3/min
    max_keys: int = 10_000
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _state: dict = field(default_factory=dict, repr=False)  # key -> [tokens, last_ts]

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            tokens, last = self._state.get(key, (self.capacity, now))
            tokens = min(self.capacity, tokens + (now - last) * self.refill_per_sec)
            if tokens < 1.0:
                self._state[key] = (tokens, now)
                return False
            self._state[key] = (tokens - 1.0, now)
            if len(self._state) > self.max_keys:
                self._prune(now)
            return True

    def _prune(self, now: float) -> None:
        """Drop the stalest half — an address-scan defence, not an LRU."""
        items = sorted(self._state.items(), key=lambda kv: kv[1][1])
        for key, _ in items[: len(items) // 2]:
            del self._state[key]

    def reset(self) -> None:
        with self._lock:
            self._state.clear()
