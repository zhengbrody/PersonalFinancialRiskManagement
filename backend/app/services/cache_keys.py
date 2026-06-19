"""Stable, namespaced cache keys — no secret ever lands in a key.

A key is ``{PREFIX}:{namespace}:{digest}`` where ``digest`` is a stable hash of
the identifying parts. Hashing the parts has two payoffs:

* **No leakage** — a raw value passed as a part (a token, an email, PII) never
  embeds in the key, only its irreversible digest. So keys are safe to log and
  safe to store in Redis (which other tooling may inspect).
* **Stable** — the same logical inputs always map to the same key regardless of
  dict ordering or float formatting (canonical JSON with sorted keys).

This module is storage-agnostic — pair it with ``services.cache``:
``cache.get(make_key("research:dcf", ticker, overrides))``.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Optional

# App-wide prefix so every MindMarket key is greppable and namespaced away from
# anything else that might share the Redis instance.
PREFIX = "mm"

_NS_RE = re.compile(r"[^a-z0-9_.:\-]+")


def stable_hash(*parts: object, length: int = 16) -> str:
    """Deterministic hex digest of arbitrary JSON-serializable parts.

    Canonical JSON (sorted keys, compact separators) makes the digest
    independent of dict ordering; non-JSON values fall back to ``str``. The
    sha256 hex is truncated to ``length`` (16 hex = 64 bits — ample collision
    resistance for a cache key); ``length<=0`` returns the full 64-char digest.
    """
    canonical = json.dumps(
        parts, sort_keys=True, separators=(",", ":"), default=str, ensure_ascii=False
    )
    digest = hashlib.sha256(canonical.encode("utf-8", "ignore")).hexdigest()
    return digest[:length] if length and length > 0 else digest


def _sanitize_namespace(namespace: str) -> str:
    """Lower-case, keep only ``[a-z0-9_.:-]`` (a readable, log-safe segment)."""
    ns = _NS_RE.sub("-", str(namespace).strip().lower()).strip("-")
    return ns or "default"


def make_key(namespace: str, *parts: object) -> str:
    """A namespaced cache key. The namespace stays human-readable (sanitized);
    the identifying ``parts`` are HASHED, so no raw value (or secret) lands in
    the key.

    ``make_key("research:dcf", "AAPL", {"wacc": 0.09})`` →
    ``"mm:research:dcf:9f8e1c0b2d3a4f56"``.
    """
    return f"{PREFIX}:{_sanitize_namespace(namespace)}:{stable_hash(*parts)}"


# ── domain-specific stable hashes (cache invalidation primitives) ───────────


def _round(v: object) -> Optional[float]:
    """Coerce a numeric to a float rounded to 6dp (so 10 vs 10.0 vs 9.9999998
    hash equal), or None. Keeps the hash stable against float-repr noise."""
    try:
        if v is None or v == "":
            return None
        return round(float(v), 6)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def portfolio_hash(holdings: object) -> str:
    """Stable hash of a portfolio's holdings — changes **iff** a holding changes
    (ticker added/removed, share count, avg cost, asset type, or option terms)
    and is invariant to dict ordering and cosmetic fields. It's a digest, so it
    never embeds raw holdings — safe to put in a cache key, log, or share across
    identical portfolios. This is THE cache-invalidation primitive: a different
    book ⇒ a different key ⇒ a recompute.
    """
    if isinstance(holdings, dict):
        items = list(holdings.items())
    elif isinstance(holdings, (list, tuple)):
        items = [(h.get("ticker") if isinstance(h, dict) else h, h) for h in holdings]
    else:
        items = []
    norm = []
    for tk, h in items:
        h = h if isinstance(h, dict) else {}
        norm.append(
            {
                "t": str(tk or "").upper(),
                "shares": _round(h.get("shares")),
                "cost": _round(h.get("avg_cost")),
                "type": str(h.get("asset_type") or "").lower(),
                # Option terms that change the CONTRACT identity (so a roll or a
                # different strike/expiry/side busts the cache).
                "opt": str(h.get("option_type") or "") or None,
                "strike": _round(h.get("strike")),
                "expiry": str(h.get("expiry") or "") or None,
                "side": str(h.get("option_side") or "") or None,
            }
        )
    norm.sort(key=lambda d: d["t"])
    return stable_hash("portfolio", norm, length=24)


def market_data_hash(prices: object) -> str:
    """Stable hash of the market-data SNAPSHOT a computation ran on. Accepts a
    ``{ticker: price}`` map or a pandas-like price frame (duck-typed — uses its
    last non-empty row + the as-of date). Two runs on the same snapshot hash
    equal; a price or as-of change busts the cache (so a stale score recomputes).
    """
    # Pandas-like frame (has ``.columns``) — hash the latest close per column +
    # the as-of date. Duck-typed so this module stays pandas-free.
    if hasattr(prices, "columns") and hasattr(prices, "iloc"):
        try:
            frame = prices.dropna(how="all")
            if len(frame.index) == 0:
                return stable_hash("market", "empty", length=20)
            last = frame.iloc[-1]
            snap = {str(c): _round(last[c]) for c in prices.columns}
            as_of = str(frame.index[-1])[:10]
            return stable_hash("market", as_of, snap, length=20)
        except Exception:  # noqa: BLE001 - never let hashing break a request
            return stable_hash("market", "unhashable", length=20)
    if isinstance(prices, dict):
        snap = {str(k): _round(v) for k, v in prices.items()}
        return stable_hash("market", snap, length=20)
    return stable_hash("market", str(prices), length=20)
