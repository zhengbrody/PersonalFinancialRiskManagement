"""Public no-signup risk check — abuse surface + math + flag + rate limit.

The endpoint is DEFAULT OFF; tests enable it per-case via env + settings
reset. Market data is always monkeypatched (offline, deterministic).
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from backend.app.api.v1 import public_risk
from backend.app.core.config import reset_settings_cache
from backend.app.services import public_risk_check
from backend.app.services.rate_limit import TokenBucket, client_ip

URL = "/api/v1/public/risk_check"


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    public_risk.reset_rate_limiter()
    yield
    public_risk.reset_rate_limiter()
    reset_settings_cache()


@pytest.fixture()
def enabled(monkeypatch):
    monkeypatch.setenv("PUBLIC_RISK_CHECK_ENABLED", "true")
    reset_settings_cache()


@pytest.fixture()
def fake_prices(monkeypatch):
    """Synthetic 1y closes for AAPL/MSFT/SPY; unknown tickers absent."""
    idx = pd.bdate_range(end="2026-06-30", periods=300)
    rng = np.random.default_rng(7)
    frame = pd.DataFrame(
        {
            "AAPL": 100 * np.exp(np.cumsum(rng.normal(0.0006, 0.02, 300))),
            "MSFT": 200 * np.exp(np.cumsum(rng.normal(0.0004, 0.015, 300))),
            "SPY": 400 * np.exp(np.cumsum(rng.normal(0.0004, 0.01, 300))),
        },
        index=idx,
    )

    def fake(tickers, *, days=365, cache_provider=None, provenance=None):
        cols = [t for t in tickers if t in frame.columns]
        if provenance is not None:
            provenance["by_ticker"] = {t: "yfinance" for t in cols}
            provenance["missing"] = [t for t in tickers if t not in frame.columns]
        return frame[cols]

    from backend.app.services import market_data

    monkeypatch.setattr(market_data, "get_price_history", fake)
    return frame


def _post(client, holdings):
    return client.post(URL, json={"holdings": holdings})


# ── feature flag ──────────────────────────────────────────────────────


def test_disabled_by_default_returns_503(test_client):
    resp = _post(test_client, [{"ticker": "AAPL", "shares": 1}])
    assert resp.status_code == 503
    assert resp.json()["error"]["details"]["reason"] == "feature_disabled"


# ── happy path ────────────────────────────────────────────────────────


def test_happy_path_limited_result_set(test_client, enabled, fake_prices):
    resp = _post(
        test_client,
        [{"ticker": "AAPL", "shares": 10}, {"ticker": "MSFT", "shares": 5}],
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    # Limited scope: concentration, metrics, stress, provenance — nothing else.
    assert set(data) == {"concentration", "metrics", "stress", "provenance", "disclaimer"}
    assert data["concentration"]["top_ticker"] in {"AAPL", "MSFT"}
    assert 0 < data["concentration"]["top_weight"] <= 1
    m = data["metrics"]
    assert m["annual_volatility"] > 0
    assert m["var_95_1d"] > 0 and m["cvar_95_1d"] >= m["var_95_1d"]
    assert len(data["stress"]) == 3
    assert data["provenance"]["priced"] == ["AAPL", "MSFT"]
    assert data["provenance"]["observations"] >= 30
    # No AI / recommendation fields, no BUY/SELL text anywhere.
    import json as _json
    import re as _re

    assert not _re.search(r"\b(BUY|SELL)\b", _json.dumps(data))


def test_unpriceable_tickers_are_reported_not_fatal(test_client, enabled, fake_prices):
    resp = _post(
        test_client,
        [{"ticker": "AAPL", "shares": 1}, {"ticker": "ZZZZZ", "shares": 1}],
    )
    assert resp.status_code == 200
    prov = resp.json()["data"]["provenance"]
    assert prov["missing"] == ["ZZZZZ"]


def test_all_unpriceable_is_422(test_client, enabled, fake_prices):
    resp = _post(test_client, [{"ticker": "ZZZZZ", "shares": 1}])
    assert resp.status_code == 422
    assert "priced" in resp.json()["error"]["message"].lower()


# ── abuse: validation surface ─────────────────────────────────────────


@pytest.mark.parametrize(
    "bad_ticker",
    [
        '=HYPERLINK("http://evil")',  # spreadsheet formula injection
        "'; DROP TABLE portfolios;--",  # SQL-ish garbage
        "@cmd",
        "-AAPL",
        "aapl bad",
        "TOOLONGTICKER",
        "",
    ],
)
def test_hostile_tickers_never_validate(test_client, enabled, bad_ticker):
    resp = _post(test_client, [{"ticker": bad_ticker, "shares": 1}])
    assert resp.status_code == 422


@pytest.mark.parametrize("bad_shares", ["NaN", "Infinity", -5, 0, 1e12])
def test_nan_inf_and_out_of_range_shares_rejected(test_client, enabled, bad_shares):
    resp = _post(test_client, [{"ticker": "AAPL", "shares": bad_shares}])
    assert resp.status_code == 422


def test_more_than_ten_holdings_rejected(test_client, enabled):
    holdings = [{"ticker": f"T{i}", "shares": 1} for i in range(11)]
    resp = _post(test_client, holdings)
    assert resp.status_code == 422


def test_duplicate_tickers_rejected(test_client, enabled):
    resp = _post(test_client, [{"ticker": "AAPL", "shares": 1}, {"ticker": "AAPL", "shares": 2}])
    assert resp.status_code == 422


def test_extra_fields_rejected(test_client, enabled):
    resp = _post(test_client, [{"ticker": "AAPL", "shares": 1, "avg_cost": 5}])
    assert resp.status_code == 422
    resp2 = test_client.post(URL, json={"holdings": [], "email": "x@y.z"})
    assert resp2.status_code == 422


def test_oversized_payload_rejected_before_parsing(test_client, enabled):
    big = "x" * 20_000
    resp = test_client.post(
        URL,
        content=('{"holdings":[{"ticker":"AAPL","shares":1}],"pad":"' + big + '"}').encode(),
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["details"]["reason"] == "payload_too_large"


# ── rate limiting ─────────────────────────────────────────────────────


def test_per_ip_token_bucket_429(test_client, enabled, fake_prices, monkeypatch):
    monkeypatch.setattr(public_risk, "_bucket", TokenBucket(capacity=2.0, refill_per_sec=0.0))
    body = [{"ticker": "AAPL", "shares": 1}]
    assert _post(test_client, body).status_code == 200
    assert _post(test_client, body).status_code == 200
    resp = _post(test_client, body)
    assert resp.status_code == 429


def test_bucket_refills_over_time():
    import time as _time

    bucket = TokenBucket(capacity=1.0, refill_per_sec=1000.0)
    assert bucket.allow("k")
    assert not bucket.allow("k")  # exhausted immediately
    _time.sleep(0.01)  # fast refill restores ≥1 token
    assert bucket.allow("k")


def test_bucket_prunes_address_scans():
    bucket = TokenBucket(capacity=1.0, refill_per_sec=0.0, max_keys=10)
    for i in range(50):
        bucket.allow(f"ip-{i}")
    assert len(bucket._state) <= 11  # pruned — an address scan can't grow memory


# ── trusted client identity ───────────────────────────────────────────


class _Req:
    def __init__(self, headers=None, host="10.0.0.9"):
        self.headers = headers or {}
        self.client = type("C", (), {"host": host})()


class _Cfg:
    def __init__(self, trust):
        self.trust_cf_connecting_ip = trust


def test_cf_header_used_only_when_deployment_asserts_cf_ingress():
    headers = {"cf-connecting-ip": "203.0.113.7", "x-forwarded-for": "1.2.3.4, 172.18.0.2"}
    # Trusted deployment (SG locked to Cloudflare) → CF header wins.
    assert client_ip(_Req(headers), _Cfg(trust=True)) == "203.0.113.7"
    # Untrusted deployment → the client-forgeable CF header is IGNORED; the
    # LAST X-Forwarded-For hop (appended by our own proxy) is used.
    assert client_ip(_Req(headers), _Cfg(trust=False)) == "172.18.0.2"
    # No headers at all → the direct peer.
    assert client_ip(_Req(), _Cfg(trust=False)) == "10.0.0.9"


# ── statelessness (privacy) ───────────────────────────────────────────


def test_payload_never_persisted(test_client, enabled, fake_prices):
    """The service keeps NO module-level state derived from the user payload —
    the only caches in play are per-ticker market data (keyed by ticker, not
    by user), and the rate limiter keyed by IP."""
    _post(test_client, [{"ticker": "AAPL", "shares": 12345}])
    import json as _json

    module_state = {k: v for k, v in vars(public_risk_check).items() if isinstance(v, (dict, list))}
    assert "12345" not in _json.dumps(module_state, default=str)


def test_check_math_is_deterministic(fake_prices):
    class _H:
        def __init__(self, t, s):
            self.ticker, self.shares = t, s

    a = public_risk_check.run_check([_H("AAPL", 10), _H("MSFT", 5)])
    b = public_risk_check.run_check([_H("AAPL", 10), _H("MSFT", 5)])
    assert a == b
    assert math.isclose(sum(a["concentration"]["weights"].values()), 1.0, rel_tol=1e-6)


def test_oversized_chunked_body_capped_without_content_length(test_client, enabled):
    """Review-caught: the old Content-Length-only guard was bypassable by a
    chunked request. The streaming cap must refuse an oversized body even with
    NO Content-Length header (starlette's stream honors the cap)."""
    big = b'{"holdings":[{"ticker":"AAPL","shares":1}],"pad":"' + b"x" * 20_000 + b'"}'

    def gen():
        # yield in chunks with no length header → chunked transfer
        for i in range(0, len(big), 4096):
            yield big[i : i + 4096]

    resp = test_client.post(URL, content=gen(), headers={"Content-Type": "application/json"})
    assert resp.status_code == 400
    assert resp.json()["error"]["details"]["reason"] == "payload_too_large"


def test_flag_and_rate_limit_gate_before_body_ingestion(test_client, monkeypatch):
    """Cheap gates run BEFORE the body is read: with the feature OFF, a huge
    body returns 503 (feature_disabled) — it is never buffered/parsed."""
    # feature stays OFF (no `enabled` fixture)
    big = b'{"holdings":[{"ticker":"AAPL","shares":1}],"pad":"' + b"x" * 50_000 + b'"}'
    resp = test_client.post(URL, content=big, headers={"Content-Type": "application/json"})
    assert resp.status_code == 503
    assert resp.json()["error"]["details"]["reason"] == "feature_disabled"


def test_global_budget_throttles_across_ips(test_client, enabled, fake_prices, monkeypatch):
    """A DISTRIBUTED scan (each IP under its own per-IP limit) still can't
    hammer the shared yfinance egress IP: the global bucket 429s once the
    platform-wide budget is spent, protecting the authed product."""
    # per-IP unlimited, global capacity 2 → the 3rd request (even from a NEW
    # IP each time) hits the global ceiling.
    monkeypatch.setattr(public_risk, "_bucket", TokenBucket(capacity=1e9, refill_per_sec=1e9))
    monkeypatch.setattr(
        public_risk, "_global_bucket", TokenBucket(capacity=2.0, refill_per_sec=0.0)
    )
    body = [{"ticker": "AAPL", "shares": 1}]
    assert _post(test_client, body).status_code == 200
    assert _post(test_client, body).status_code == 200
    assert _post(test_client, body).status_code == 429
