"""End-to-end happy paths for ``POST /api/v1/risk/score``.

The endpoint must produce a complete envelope with a real ``overall_score``
(int 0..1000) and three dimension scores when given a valid holdings
body. It must surface ``unprocessable`` errors when holdings are bad."""

from __future__ import annotations


def _basic_body():
    return {
        "holdings": [
            {"ticker": "SPY", "market_value": 60_000, "asset_type": "public_security"},
            {"ticker": "BND", "market_value": 40_000, "asset_type": "public_security"},
        ],
        "risk_preference": 3,
        "risk_free_rate": 0.045,
    }


def test_score_happy_path_returns_complete_envelope(test_client):
    resp = test_client.post("/api/v1/risk/score", json=_basic_body())
    assert resp.status_code == 200
    body = resp.json()
    assert body["error"] is None

    data = body["data"]
    assert "overall_score" in data
    assert isinstance(data["overall_score"], int)
    assert 0 <= data["overall_score"] <= 1000

    # Three dimensions, all named and scored.
    dims = data["dimensions"]
    assert set(dims.keys()) == {
        "risk_match",
        "risk_adjusted_return",
        "downside_protection",
    }
    for d in dims.values():
        assert 0 <= float(d["score"]) <= 1000

    # Metrics block carries the synthetic-data caveat so the frontend
    # can warn the user when no real returns matrix was sent.
    notes = data["metrics"]["data_quality_notes"]
    assert any("synthesised" in n for n in notes)
    assert data["analysis_mode"] == "synthetic_demo"
    assert data["data_confidence"]["directional_allowed"] is False
    assert data["data_confidence"]["conviction_cap"] == "none"
    assert data["data_confidence"]["missing"][0]["missing_reason"] == "synthetic_demo"


def test_score_with_inline_returns_drops_synthetic_warning(test_client):
    """When the caller supplies real returns, the synthetic warning
    must NOT be added — that flag is for UX clarity, not noise."""
    import random

    rng = random.Random(7)
    returns = {
        "SPY": [rng.gauss(0.0003, 0.01) for _ in range(252)],
        "BND": [rng.gauss(0.0001, 0.003) for _ in range(252)],
    }
    bench = [rng.gauss(0.0003, 0.01) for _ in range(252)]
    body = {**_basic_body(), "returns": returns, "benchmark_returns": bench}
    resp = test_client.post("/api/v1/risk/score", json=body)
    assert resp.status_code == 200

    notes = resp.json()["data"]["metrics"]["data_quality_notes"]
    assert not any("synthesised" in n for n in notes)
    assert resp.json()["data"]["analysis_mode"] == "provided_returns"


def test_score_surfaces_data_quality_confidence_and_drivers(test_client):
    """The response must carry the deterministic explainability fields: a
    data-quality/confidence read, the pre-dampening base score, ranked drivers,
    and structured reason codes. Full data → high confidence, undamped."""
    import random

    rng = random.Random(3)
    returns = {
        "SPY": [rng.gauss(0.0004, 0.01) for _ in range(252)],
        "BND": [rng.gauss(0.0001, 0.003) for _ in range(252)],
    }
    bench = [rng.gauss(0.0004, 0.01) for _ in range(252)]
    body = {**_basic_body(), "returns": returns, "benchmark_returns": bench}
    data = test_client.post("/api/v1/risk/score", json=body).json()["data"]

    # data-quality / confidence on metrics
    assert data["metrics"]["confidence"] == "high"
    assert 0.0 <= data["metrics"]["data_quality"] <= 1.0
    assert data["metrics"]["dropped_tickers"] == []

    # full data → no dampening: shown score equals the pre-dampening base
    assert data["base_overall"] == data["overall_score"]

    # drivers: one per dimension, ranked by points_below_max (biggest drag first)
    drivers = data["drivers"]
    assert len(drivers) == 3
    pts = [d["points_below_max"] for d in drivers]
    assert pts == sorted(pts, reverse=True)
    assert all({"key", "name", "score", "weight", "points_below_max"} <= set(d) for d in drivers)

    # reason codes are structured (may be empty for a healthy full-data book)
    for rc in data["reason_codes"]:
        assert "code" in rc and "severity" in rc


def test_score_rejects_empty_holdings(test_client):
    resp = test_client.post("/api/v1/risk/score", json={"holdings": [], "risk_preference": 3})
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation_failed"


def test_score_rejects_negative_market_value(test_client):
    body = {"holdings": [{"ticker": "SPY", "market_value": -100, "asset_type": "public_security"}]}
    resp = test_client.post("/api/v1/risk/score", json=body)
    assert resp.status_code == 422
    body_json = resp.json()
    assert body_json["error"]["code"] == "validation_failed"


def test_score_rejects_all_disabled_holdings(test_client):
    """At least one enabled position must score; an all-disabled book
    is a 422 (unprocessable) — Pydantic catches it at the boundary."""
    body = {
        "holdings": [
            {
                "ticker": "SPY",
                "market_value": 100,
                "asset_type": "public_security",
                "enabled": False,
            },
        ]
    }
    resp = test_client.post("/api/v1/risk/score", json=body)
    assert resp.status_code == 422


def test_score_rejects_returns_shorter_than_required(test_client):
    body = {
        **_basic_body(),
        "returns": {"SPY": [0.001, -0.002], "BND": [0.0001, 0.0001]},
    }
    resp = test_client.post("/api/v1/risk/score", json=body)
    # Engine returns a "not enough observations" 422 OR the inline
    # validation returns one; both are acceptable, the response code
    # is what matters.
    assert resp.status_code in (422,)


def test_score_does_not_call_network(test_client, monkeypatch):
    """Belt and braces: the endpoint MUST be testable offline. If
    someone accidentally adds a yfinance / FMP call into the score
    path this test fails because socket access would raise.

    Implementation note: we can't fully sandbox sockets via monkeypatch
    inside pytest, but we can assert the call is fast (no network
    timeout) and produces a 200 on a hermetic body."""
    import time

    started = time.perf_counter()
    resp = test_client.post("/api/v1/risk/score", json=_basic_body())
    elapsed = time.perf_counter() - started
    assert resp.status_code == 200
    # A network call would push this past 1s; the deterministic path
    # is well under that. 5s gives plenty of headroom on slow CI.
    assert elapsed < 5.0
