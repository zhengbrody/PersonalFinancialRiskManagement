"""Pin the response-envelope contract from ADR-0004.

The frontend's ``apiFetch<T>()`` (Phase 2) will rely on this shape;
break it here and the React Query layer breaks downstream.
"""

from __future__ import annotations


def _assert_envelope(body: dict):
    assert isinstance(body, dict)
    assert set(body.keys()) >= {"data", "error", "meta"}
    assert isinstance(body["meta"], dict)
    assert "request_id" in body["meta"]


def test_health_returns_envelope(test_client):
    resp = test_client.get("/api/v1/health")
    assert resp.status_code == 200
    body = resp.json()
    _assert_envelope(body)
    assert body["error"] is None
    assert body["data"]["status"] in ("ok", "degraded")


def test_envelope_carries_request_id_when_caller_sends_one(test_client):
    """The frontend will set X-Request-Id for log correlation; the
    envelope must echo whatever the caller sent, not mint a new one."""
    resp = test_client.get(
        "/api/v1/health",
        headers={"X-Request-Id": "ride-along-correlation"},
    )
    assert resp.json()["meta"]["request_id"] == "ride-along-correlation"


def test_envelope_includes_elapsed_ms_when_started_at_set(test_client):
    """Endpoints that pass started_at into ok() (we do this on every
    route) must report elapsed_ms as a non-negative integer."""
    body = test_client.get("/api/v1/health").json()
    elapsed = body["meta"].get("elapsed_ms")
    assert isinstance(elapsed, int)
    assert elapsed >= 0


def test_validation_error_returns_422_envelope(test_client):
    """Posting an invalid body to a real endpoint must come back as
    the envelope, not FastAPI's default ``{"detail": ...}`` shape."""
    resp = test_client.post("/api/v1/risk/score", json={})  # missing holdings
    assert resp.status_code == 422
    body = resp.json()
    _assert_envelope(body)
    assert body["data"] is None
    assert body["error"]["code"] == "validation_failed"
    # Pydantic errors are surfaced under details.errors for the frontend
    # to highlight the offending field.
    assert "errors" in body["error"]["details"]


def test_http_exception_is_rewritten_into_envelope(test_client):
    """A bogus path → FastAPI's HTTPException(404) → must come back
    in our envelope shape."""
    resp = test_client.get("/api/v1/nope")
    assert resp.status_code == 404
    body = resp.json()
    _assert_envelope(body)
    assert body["error"]["code"] == "not_found"
