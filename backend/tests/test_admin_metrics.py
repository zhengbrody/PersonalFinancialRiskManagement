"""Tests for the live in-process API metrics + the owner /billing/admin/metrics
endpoint.

Covers the registry (counters/snapshot/cardinality guard), the ASGI middleware
recording real requests through the TestClient, and owner-gating on the endpoint.
"""

from __future__ import annotations

import pytest

from backend.app.services import metrics

_OWNER = "owner@mindmarket.test"


def _auth(mint_token, **claims):
    return {"Authorization": f"Bearer {mint_token(**claims)}"}


@pytest.fixture
def as_owner(monkeypatch):
    monkeypatch.setenv("MINDMARKET_OWNER_EMAILS", _OWNER)


@pytest.fixture(autouse=True)
def _clean_metrics():
    """Each test starts from a clean registry so counts are deterministic."""
    metrics.reset()
    yield
    metrics.reset()


# ── registry unit tests ─────────────────────────────────────────────


def test_record_request_aggregates_status_classes_and_latency():
    metrics.record_request("GET", "/api/v1/x", 200, 10.0)
    metrics.record_request("GET", "/api/v1/x", 200, 30.0)
    metrics.record_request("GET", "/api/v1/x", 500, 50.0)

    snap = metrics.snapshot()
    row = next(r for r in snap["routes"] if r["route"] == "/api/v1/x")
    assert row["count"] == 3
    assert row["status_2xx"] == 2
    assert row["status_5xx"] == 1
    assert row["errors"] == 1
    assert row["avg_ms"] == pytest.approx(30.0)  # (10+30+50)/3
    assert snap["total_requests"] == 3
    assert snap["total_errors"] == 1


def test_record_provider_classifies_outcomes():
    for outcome in ("ok", "ok", "cache_hit", "rate_limited", "error", "no_key"):
        metrics.record_provider("massive", outcome)

    snap = metrics.snapshot()
    p = next(p for p in snap["providers"] if p["name"] == "massive")
    assert p["calls"] == 6
    assert p["ok"] == 2
    assert p["cache_hit"] == 1
    assert p["rate_limited"] == 1
    assert p["error"] == 1
    assert p["no_key"] == 1


def test_unknown_provider_outcome_still_counts_the_call():
    metrics.record_provider("fmp", "weird")
    p = next(p for p in metrics.snapshot()["providers"] if p["name"] == "fmp")
    assert p["calls"] == 1
    assert p["ok"] == 0


def test_route_cardinality_is_bounded():
    # Far more distinct routes than the cap → overflow folds into one bucket.
    for i in range(metrics._MAX_ROUTES + 50):
        metrics.record_request("GET", f"/scan/{i}", 404, 1.0)
    snap = metrics.snapshot()
    assert len(snap["routes"]) <= metrics._MAX_ROUTES + 1  # +1 for the <other> bucket
    assert any(r["route"] == "<other>" for r in snap["routes"])


def test_record_functions_never_raise_on_bad_input():
    # Defensive: a None status / latency must not bubble up into a request path.
    metrics.record_request("GET", "/api/v1/y", None, None)  # type: ignore[arg-type]
    metrics.record_provider("fmp", None)  # type: ignore[arg-type]


# ── middleware integration ──────────────────────────────────────────


def test_middleware_records_real_requests(test_client):
    # A real request through the app must show up in the registry, keyed by the
    # matched route TEMPLATE, with the right status class.
    metrics.reset()
    test_client.get("/api/v1/health")
    snap = metrics.snapshot()
    assert snap["total_requests"] >= 1
    health = next((r for r in snap["routes"] if "health" in r["route"]), None)
    assert health is not None
    assert health["method"] == "GET"
    assert health["status_2xx"] >= 1


# ── endpoint owner-gating ───────────────────────────────────────────


def test_metrics_requires_bearer(test_client):
    assert test_client.get("/api/v1/billing/admin/metrics").status_code == 401


def test_metrics_forbidden_for_non_owner(test_client, mint_token, monkeypatch):
    monkeypatch.setenv("MINDMARKET_OWNER_EMAILS", "someone-else@x.com")
    resp = test_client.get("/api/v1/billing/admin/metrics", headers=_auth(mint_token))
    assert resp.status_code == 403


def test_metrics_snapshot_for_owner(test_client, mint_token, as_owner):
    # Warm up so there's recorded traffic. (The metrics request's own row is
    # written by the middleware AFTER the handler reads the snapshot, so a
    # request never appears in its own response — diffing across polls covers it.)
    test_client.get("/api/v1/health")
    resp = test_client.get("/api/v1/billing/admin/metrics", headers=_auth(mint_token, email=_OWNER))
    assert resp.status_code == 200, resp.json()
    data = resp.json()["data"]
    assert "uptime_s" in data
    assert "routes" in data and isinstance(data["routes"], list)
    assert "providers" in data and isinstance(data["providers"], list)
    assert data["total_requests"] >= 1  # the warm-up health hit


# ── research dataset health counters ───────────────────────────────


def test_record_dataset_counts_requests_once_with_multiple_outcomes():
    metrics.reset()
    metrics.record_dataset("factpack", "present", "fallback", "stale")
    metrics.record_dataset("factpack", "empty")
    d = next(x for x in metrics.snapshot()["datasets"] if x["name"] == "factpack")
    assert d["requests"] == 2
    assert d["present"] == 1
    assert d["fallback"] == 1
    assert d["stale"] == 1
    assert d["empty"] == 1
    assert d["provider_error"] == 0


def test_record_dataset_is_a_closed_set_no_cardinality_growth():
    metrics.reset()
    metrics.record_dataset("totally-made-up", "present")
    metrics.record_dataset("AAPL", "present")  # a ticker must NEVER become a bucket
    assert metrics.snapshot()["datasets"] == []


def test_record_dataset_distinguishes_provider_reality_from_code_faults():
    metrics.reset()
    metrics.record_dataset("earnings", "empty")  # provider-reality gap
    metrics.record_dataset("earnings", "rate_limited", "empty")
    metrics.record_dataset("earnings", "provider_error")  # the leg raised
    d = next(x for x in metrics.snapshot()["datasets"] if x["name"] == "earnings")
    assert d["requests"] == 3
    assert d["empty"] == 2
    assert d["rate_limited"] == 1
    assert d["provider_error"] == 1


def test_record_dataset_never_raises_on_bad_input():
    metrics.record_dataset("factpack", None)  # type: ignore[arg-type]
    metrics.record_dataset(None, "present")  # type: ignore[arg-type]
