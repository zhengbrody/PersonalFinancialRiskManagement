"""In-process, real-time API usage metrics for the owner dashboard.

Monotonic counters held in memory — **zero DB writes**, so recording a call
costs a dict update under a lock and never adds a Supabase round-trip to the
hot path (the box is a RAM-bound t3.micro). The owner ``/admin/metrics``
endpoint returns a cheap snapshot; the dashboard polls it every few seconds and
diffs consecutive snapshots to render live rates.

Scope of what's tracked:
* **HTTP** — every backend request, keyed by ``METHOD route-template`` (the
  matched route pattern, not the raw path, so ``/portfolios/{id}`` doesn't blow
  up cardinality). Count, error count, status-class split, mean latency.
* **Providers** — each external data API call (yfinance / FMP / Massive / FRED /
  Treasury) classified by outcome (ok / cache_hit / empty / error / rate_limited
  / no_key), recorded at each provider's choke point.

These counters reset on restart/deploy **by design** — this is a live-activity
view, not the billing ledger. Real token cost stays in ``usage_events`` (Supabase),
surfaced by the slower ``/admin/usage`` endpoint. Every function is fail-soft and
must never raise into a request path.
"""

from __future__ import annotations

import threading
import time

_LOCK = threading.Lock()
_START = time.monotonic()

# route-key ("GET /api/v1/...") -> counters
_http: dict[str, dict] = {}
# provider name ("fmp") -> counters
_providers: dict[str, dict] = {}
# research dataset ("factpack") -> outcome counters (aggregate only — NO ticker)
_datasets: dict[str, dict] = {}

# Cardinality guard: a scanner hitting random paths must not grow this map
# unbounded. Past the cap, overflow rolls into a single "<other>" bucket.
_MAX_ROUTES = 200

# Outcomes a provider call can record. ``ok`` = returned usable data, ``empty``
# = reached upstream but nothing useful, the rest are self-explanatory.
PROVIDER_OUTCOMES = ("ok", "cache_hit", "empty", "error", "rate_limited", "no_key")

# Research dataset health — aggregate per DATASET (never per ticker; no
# question/holdings/response content). Distinguishes provider-reality gaps
# (empty / rate_limited) from code faults (provider_error) and honesty states
# (stale / fallback). ``requests`` counts every assembly attempt.
DATASET_OUTCOMES = (
    "present",  # usable data assembled
    "empty",  # providers reachable, nothing usable (provider-reality gap)
    "stale",  # served from a stale cache window
    "fallback",  # the secondary (free) source stood in for the primary
    "provider_error",  # the leg raised / upstream 5xx (code or provider fault)
    "rate_limited",  # provider throttled the assembly
)

# Closed set — a typo'd dataset name must not grow the map.
RESEARCH_DATASETS = ("factpack", "financials", "earnings", "dcf", "peers", "news", "thesis")


def _new_http() -> dict:
    return {"count": 0, "errors": 0, "s2xx": 0, "s4xx": 0, "s5xx": 0, "lat_ms_sum": 0.0}


def _new_provider() -> dict:
    return {"calls": 0, **{o: 0 for o in PROVIDER_OUTCOMES}}


def _new_dataset() -> dict:
    return {"requests": 0, **{o: 0 for o in DATASET_OUTCOMES}}


def record_request(method: str, route: str, status: int, latency_ms: float) -> None:
    """Record one HTTP request. Called from the ASGI metrics middleware."""
    key = f"{method} {route}"
    try:
        with _LOCK:
            r = _http.get(key)
            if r is None:
                if len(_http) >= _MAX_ROUTES:
                    key = f"{method} <other>"
                    r = _http.get(key)
                if r is None:
                    r = _new_http()
                    _http[key] = r
            r["count"] += 1
            r["lat_ms_sum"] += float(latency_ms)
            if status >= 500:
                r["errors"] += 1
                r["s5xx"] += 1
            elif status >= 400:
                r["s4xx"] += 1
            else:
                r["s2xx"] += 1
    except Exception:  # noqa: BLE001 - metrics must never break a request
        pass


def record_provider(name: str, outcome: str) -> None:
    """Record one external-provider call outcome. Called from each provider's
    cache/choke point. Unknown outcomes still bump ``calls`` so totals stay
    honest."""
    try:
        with _LOCK:
            p = _providers.get(name)
            if p is None:
                p = _new_provider()
                _providers[name] = p
            p["calls"] += 1
            if outcome in p:
                p[outcome] += 1
    except Exception:  # noqa: BLE001
        pass


def record_dataset(dataset: str, *outcomes: str) -> None:
    """Record one research-dataset assembly: ONE ``requests`` bump plus every
    applicable (non-exclusive) outcome — e.g. ``("present", "fallback",
    "stale")``. AGGREGATE only — callers must never pass a ticker or content.
    Unknown dataset names are dropped (closed set — no cardinality growth);
    unknown outcomes are ignored while ``requests`` stays honest."""
    try:
        if dataset not in RESEARCH_DATASETS:
            return
        with _LOCK:
            d = _datasets.get(dataset)
            if d is None:
                d = _new_dataset()
                _datasets[dataset] = d
            d["requests"] += 1
            for outcome in outcomes:
                if outcome in d and outcome != "requests":
                    d[outcome] += 1
    except Exception:  # noqa: BLE001 - metrics must never break a request
        pass


def snapshot() -> dict:
    """A cheap, JSON-ready point-in-time view. Routes + providers are sorted by
    volume so the busiest sit on top."""
    with _LOCK:
        routes = []
        for key, r in _http.items():
            method, _, route = key.partition(" ")
            cnt = r["count"] or 0
            routes.append(
                {
                    "method": method,
                    "route": route,
                    "count": cnt,
                    "errors": r["errors"],
                    "status_2xx": r["s2xx"],
                    "status_4xx": r["s4xx"],
                    "status_5xx": r["s5xx"],
                    "avg_ms": round(r["lat_ms_sum"] / cnt, 1) if cnt else 0.0,
                }
            )
        providers = [{"name": name, **p} for name, p in _providers.items()]
        datasets = [{"name": name, **d} for name, d in _datasets.items()]
        total_requests = sum(r["count"] for r in _http.values())
        total_errors = sum(r["errors"] for r in _http.values())

    routes.sort(key=lambda x: x["count"], reverse=True)
    providers.sort(key=lambda x: x["calls"], reverse=True)
    datasets.sort(key=lambda x: x["requests"], reverse=True)
    return {
        "uptime_s": round(time.monotonic() - _START, 1),
        "total_requests": total_requests,
        "total_errors": total_errors,
        "routes": routes,
        "providers": providers,
        "datasets": datasets,
    }


def reset() -> None:
    """Test hook — clear all counters."""
    with _LOCK:
        _http.clear()
        _providers.clear()
        _datasets.clear()
