"""Contract tests for ``/api/v1/macro/series`` + ``/api/v1/macro/yield_curve``.

Hermetic: the ``_http_get`` HTTP call in ``services.macro_data`` is
monkeypatched so we never touch FRED or Treasury in CI. We also reset
the in-process TTL cache between tests so one test can't poison the
next.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _reset_cache():
    """Macro cache is in-process; isolate it between tests."""
    from backend.app.services import macro_data as md

    md.reset_cache()
    yield
    md.reset_cache()


@pytest.fixture
def fake_http(monkeypatch):
    """Patch ``_http_get`` so tests serve fixed CSV bodies."""

    class _Stub:
        def __init__(self) -> None:
            self.bodies: dict[str, str] = {}
            self.calls: list[str] = []
            self.raise_on_call: Exception | None = None

        def set(self, url_fragment: str, body: str) -> None:
            self.bodies[url_fragment] = body

        def raise_with(self, exc: Exception) -> None:
            self.raise_on_call = exc

        def __call__(self, url: str) -> str:
            self.calls.append(url)
            if self.raise_on_call is not None:
                raise self.raise_on_call
            for fragment, body in self.bodies.items():
                if fragment in url:
                    return body
            raise AssertionError(f"Unexpected URL: {url}")

    stub = _Stub()
    from backend.app.services import macro_data as md

    monkeypatch.setattr(md, "_http_get", stub)
    return stub


# ── /macro/series ─────────────────────────────────────────────────


def test_returns_fred_series_envelope(test_client, fake_http):
    fake_http.set(
        "id=DFF",
        "observation_date,DFF\n2026-05-26,4.30\n2026-05-27,4.31\n",
    )
    resp = test_client.get("/api/v1/macro/series?series=DFF")
    assert resp.status_code == 200
    body = resp.json()
    assert body["error"] is None
    series = body["data"]["series"]
    assert len(series) == 1
    assert series[0]["series_id"] == "DFF"
    assert series[0]["latest_value"] == pytest.approx(4.31)
    assert series[0]["latest_date"] == "2026-05-27"
    assert len(series[0]["points"]) == 2


def test_strips_fred_missing_value_sentinel(test_client, fake_http):
    """FRED uses ``.`` to mean "no value reported". The service must
    coerce to NaN and drop those rows, not emit them as null floats
    (which would also break JSON encoding via NaN scrub)."""
    fake_http.set(
        "id=DFF",
        "observation_date,DFF\n2026-05-26,.\n2026-05-27,4.31\n",
    )
    resp = test_client.get("/api/v1/macro/series?series=DFF")
    assert resp.status_code == 200
    points = resp.json()["data"]["series"][0]["points"]
    assert len(points) == 1
    assert points[0]["date"] == "2026-05-27"


def test_rejects_unknown_series_with_422(test_client, fake_http):
    resp = test_client.get("/api/v1/macro/series?series=NOTREAL")
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "unprocessable"


def test_rejects_garbage_series_id(test_client, fake_http):
    resp = test_client.get("/api/v1/macro/series?series=$$$")
    assert resp.status_code == 422


def test_maps_upstream_failure_to_server_error(test_client, fake_http):
    fake_http.raise_with(RuntimeError("FRED 503"))
    resp = test_client.get("/api/v1/macro/series?series=DFF")
    assert resp.status_code == 500
    body = resp.json()
    assert body["error"]["code"] == "server_error"
    assert "FRED 503" not in body["error"]["message"]


def test_cache_avoids_duplicate_http_calls(test_client, fake_http):
    """Two requests within the TTL window → one upstream call only."""
    fake_http.set(
        "id=DFF",
        "observation_date,DFF\n2026-05-27,4.31\n",
    )
    resp1 = test_client.get("/api/v1/macro/series?series=DFF&days=180")
    resp2 = test_client.get("/api/v1/macro/series?series=DFF&days=180")
    assert resp1.status_code == 200
    assert resp2.status_code == 200
    assert len(fake_http.calls) == 1


# ── /macro/yield_curve ────────────────────────────────────────────


def test_returns_yield_curve_envelope(test_client, fake_http):
    fake_http.set(
        "daily-treasury-rates.csv",
        (
            'Date,"1 Mo","3 Mo","6 Mo","1 Yr","2 Yr","5 Yr","10 Yr","30 Yr"\n'
            "05/28/2026,3.72,3.69,3.79,3.80,3.99,4.15,4.45,4.98\n"
            "05/27/2026,3.72,3.68,3.79,3.80,4.00,4.17,4.48,5.01\n"
        ),
    )
    resp = test_client.get("/api/v1/macro/yield_curve")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["as_of"] == "2026-05-28"
    tenors = [p["tenor"] for p in data["points"]]
    assert tenors == ["1M", "3M", "6M", "1Y", "2Y", "5Y", "10Y", "30Y"]
    by_tenor = {p["tenor"]: p["yield_pct"] for p in data["points"]}
    assert by_tenor["10Y"] == pytest.approx(4.45)


def test_yield_curve_upstream_failure_is_server_error(test_client, fake_http):
    fake_http.raise_with(TimeoutError("Treasury timeout"))
    resp = test_client.get("/api/v1/macro/yield_curve")
    assert resp.status_code == 500
    assert resp.json()["error"]["code"] == "server_error"
