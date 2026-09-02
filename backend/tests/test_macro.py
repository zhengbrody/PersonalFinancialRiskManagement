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
    assert body["data"]["source"] == "FRED"
    assert body["data"]["cache_ttl_seconds"] == 3600
    assert "Auto-refreshes" in body["data"]["refresh_policy"]


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
    assert data["source"] == "US Treasury"
    assert data["stale"] is False
    assert data["cache_ttl_seconds"] == 3600
    assert "Auto-refreshes" in data["refresh_policy"]


_CURVE_CSV = (
    'Date,"1 Mo","3 Mo","6 Mo","1 Yr","2 Yr","5 Yr","10 Yr","30 Yr"\n'
    "05/28/2026,3.72,3.69,3.79,3.80,3.99,4.15,4.45,4.98\n"
)


def _expire_cache_ttl():
    """Age every cached entry past its TTL without touching ``stored_at``.

    Simulates "the hour has elapsed, so the next call re-fetches" — which
    is the only state in which the upstream-failure path is reachable.
    """
    from backend.app.services import macro_data as md

    for entry in md._cache.values():
        entry.expires_at = 0.0


def test_yield_curve_upstream_failure_without_cache_is_503(test_client, fake_http):
    """Cold cache + dead upstream: no answer exists, so 503 (retry later) —
    not 500, which would blame a bug in us for a Treasury timeout."""
    fake_http.raise_with(TimeoutError("Treasury timeout"))
    resp = test_client.get("/api/v1/macro/yield_curve")
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "service_unavailable"


def test_yield_curve_serves_last_good_copy_when_upstream_fails(test_client, fake_http):
    """The real production failure: Treasury read-times-out after we already
    have today's curve. The last good copy is still the newest curve that
    exists, so it is served — flagged stale — instead of erroring."""
    fake_http.set("daily-treasury-rates.csv", _CURVE_CSV)
    first = test_client.get("/api/v1/macro/yield_curve")
    assert first.status_code == 200
    assert first.json()["data"]["stale"] is False

    _expire_cache_ttl()
    fake_http.raise_with(TimeoutError("Treasury timeout"))

    resp = test_client.get("/api/v1/macro/yield_curve")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["stale"] is True
    assert data["as_of"] == "2026-05-28"
    assert {p["tenor"]: p["yield_pct"] for p in data["points"]}["10Y"] == pytest.approx(4.45)


def test_yield_curve_stale_fallback_stops_at_the_ceiling(fake_http, monkeypatch):
    """Past STALE_MAX_SECONDS we would be guessing, so the error propagates
    (and the endpoint above turns it into a 503)."""
    from backend.app.services import macro_data as md

    fake_http.set("daily-treasury-rates.csv", _CURVE_CSV)
    assert md.get_yield_curve().as_of == "2026-05-28"

    _expire_cache_ttl()
    monkeypatch.setattr(md, "STALE_MAX_SECONDS", -1)  # every entry is now too old
    fake_http.raise_with(TimeoutError("Treasury timeout"))

    with pytest.raises(TimeoutError):
        md.get_yield_curve(allow_stale=True)


def test_yield_curve_default_call_still_raises(fake_http):
    """allow_stale is opt-in: research_dcf and the MCP tool, which have their
    own fail-soft handling, must keep seeing the exception."""
    from backend.app.services import macro_data as md

    fake_http.set("daily-treasury-rates.csv", _CURVE_CSV)
    md.get_yield_curve()

    _expire_cache_ttl()
    fake_http.raise_with(TimeoutError("Treasury timeout"))

    with pytest.raises(TimeoutError):
        md.get_yield_curve()


# ── /macro/regime ─────────────────────────────────────────────────


@pytest.fixture
def _reset_regime_cache():
    from backend.app.services import market_regime as mr

    mr.reset_cache()
    yield
    mr.reset_cache()


@pytest.fixture
def fake_regime_sources(monkeypatch, _reset_regime_cache):
    """Patch the market_intelligence fns market_regime imports lazily.
    Defaults to all-healthy; tests override individual legs."""
    import market_intelligence as mi

    state = {
        "vix": {"current": 18.4, "change": -0.031, "level": "Calm"},
        "fear_greed": {"score": 62.0, "rating_display": "Greed"},
        # fetch_yield_curve returns (df, analysis)
        "yield_curve": (None, {"curve_status": "Normal", "3M-10Y Spread": 0.76}),
    }

    def _mk(key):
        def _fn(*a, **k):
            v = state[key]
            if isinstance(v, Exception):
                raise v
            return v

        return _fn

    monkeypatch.setattr(mi, "get_vix_current", _mk("vix"))
    monkeypatch.setattr(mi, "fetch_fear_greed", _mk("fear_greed"))
    monkeypatch.setattr(mi, "fetch_yield_curve", _mk("yield_curve"))
    return state


def test_regime_happy_path(test_client, fake_regime_sources):
    resp = test_client.get("/api/v1/macro/regime")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["vix"]["current"] == pytest.approx(18.4)
    assert data["vix"]["level"] == "Calm"
    assert data["fear_greed"]["score"] == pytest.approx(62.0)
    assert data["fear_greed"]["rating"] == "Greed"
    assert data["yield_curve"]["status"] == "Normal"
    assert data["yield_curve"]["spread_3m_10y"] == pytest.approx(0.76)
    assert data["yield_curve"]["inverted"] is False


def test_regime_inverted_curve_flag(test_client, fake_regime_sources):
    fake_regime_sources["yield_curve"] = (
        None,
        {"curve_status": "Inverted", "3M-10Y Spread": -0.45},
    )
    resp = test_client.get("/api/v1/macro/regime")
    data = resp.json()["data"]
    assert data["yield_curve"]["inverted"] is True


def test_regime_partial_failure_nulls_only_that_leg(test_client, fake_regime_sources):
    """A dead VIX upstream must null ONLY vix — F&G + yield curve still
    render, and the response is still a 200 (panel degrades gracefully)."""
    fake_regime_sources["vix"] = RuntimeError("yfinance VIX down")
    resp = test_client.get("/api/v1/macro/regime")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["vix"]["current"] is None
    assert data["fear_greed"]["score"] == pytest.approx(62.0)
    assert data["yield_curve"]["status"] == "Normal"


def test_regime_all_sources_down_is_still_200(test_client, fake_regime_sources):
    fake_regime_sources["vix"] = RuntimeError("x")
    fake_regime_sources["fear_greed"] = RuntimeError("y")
    fake_regime_sources["yield_curve"] = RuntimeError("z")
    resp = test_client.get("/api/v1/macro/regime")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["vix"]["current"] is None
    assert data["fear_greed"]["score"] is None
    assert data["yield_curve"]["status"] is None


# ── /macro/regime_detail ──────────────────────────────────────────


@pytest.fixture
def _reset_regime_detail_cache():
    from backend.app.services import regime_detail as rd

    rd.reset_cache()
    yield
    rd.reset_cache()


@pytest.fixture
def fake_regime_summary(monkeypatch, _reset_regime_detail_cache):
    """Patch regime_detector.get_regime_summary (lazily imported by the
    regime_detail service). Defaults to a healthy bull snapshot."""
    import pandas as pd

    state = {
        "ret": {
            "current_regime": "Bullish",
            "confidence": 0.72,
            "vix_regime": "Calm",
            "trend_regime": "Uptrend",
            "vol_regime": "Low Vol",
            "regime_since_date": "2026-03-01",
            "historical_regimes": pd.DataFrame(
                {
                    "composite_signal": ["Bearish", "Transition", "Bullish"],
                },
                index=pd.to_datetime(["2026-01-02", "2026-02-02", "2026-03-02"]),
            ),
        }
    }
    import regime_detector as rdmod

    def _fn(*a, **k):
        v = state["ret"]
        if isinstance(v, Exception):
            raise v
        return v

    monkeypatch.setattr(rdmod, "get_regime_summary", _fn)
    return state


def test_regime_detail_happy_path(test_client, fake_regime_summary):
    resp = test_client.get("/api/v1/macro/regime_detail")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["current_regime"] == "Bullish"
    assert data["confidence"] == pytest.approx(0.72)
    assert data["trend_regime"] == "Uptrend"
    assert len(data["history"]) == 3
    assert data["history"][0] == {"date": "2026-01-02", "regime": "Bearish"}
    assert data["history"][-1]["regime"] == "Bullish"


def test_regime_detail_unknown_sentinel_nulled(test_client, fake_regime_summary):
    import pandas as pd

    fake_regime_summary["ret"] = {
        "current_regime": "Unknown",
        "confidence": 0.0,
        "vix_regime": "Unknown",
        "trend_regime": "Unknown",
        "vol_regime": "Unknown",
        "regime_since_date": None,
        "historical_regimes": pd.DataFrame(),
    }
    resp = test_client.get("/api/v1/macro/regime_detail")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["current_regime"] is None  # "Unknown" sentinel → null
    assert data["history"] == []


def test_regime_detail_fail_soft(test_client, fake_regime_summary):
    fake_regime_summary["ret"] = RuntimeError("regime engine down")
    resp = test_client.get("/api/v1/macro/regime_detail")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["current_regime"] is None
    assert data["history"] == []
