"""Contract tests for ``GET /api/v1/market/prices``.

Hermetic: the ``market_data`` service is monkeypatched so tests don't
hit yfinance. Asserts the public input contract (ticker normalisation,
422 on garbage), the envelope shape, and the partial-coverage path
where one ticker resolves and another doesn't."""

from __future__ import annotations

from dataclasses import dataclass

import pytest


@dataclass(frozen=True)
class _Latest:
    ticker: str
    price: float
    as_of: str


@pytest.fixture
def fake_market(monkeypatch):
    """Patch ``services.market_data.get_latest_prices`` so tests
    don't touch yfinance."""

    class _Stub:
        def __init__(self) -> None:
            self.rows: list[_Latest] = []
            self.calls: list[list[str]] = []
            self.raise_on_call: Exception | None = None

        def set(self, rows: list[_Latest]) -> None:
            self.rows = rows

        def raise_with(self, exc: Exception) -> None:
            self.raise_on_call = exc

        def __call__(self, tickers, *, cache_provider=None, provenance=None):
            self.calls.append(list(tickers))
            if self.raise_on_call is not None:
                raise self.raise_on_call
            requested = {t for t in tickers}
            rows = [r for r in self.rows if r.ticker in requested]
            if provenance is not None:
                provenance["by_ticker"] = {r.ticker: getattr(r, "source", "yfinance") for r in rows}
                provenance["missing"] = [t for t in requested if t not in {r.ticker for r in rows}]
            return rows

    stub = _Stub()
    from backend.app.services import market_data as md

    monkeypatch.setattr(md, "get_latest_prices", stub)
    return stub


def test_returns_envelope_with_priced_rows(test_client, fake_market):
    fake_market.set(
        [
            _Latest("BND", 72.5, "2026-05-28"),
            _Latest("SPY", 521.3, "2026-05-28"),
        ]
    )
    resp = test_client.get("/api/v1/market/prices?tickers=SPY,BND")
    assert resp.status_code == 200
    body = resp.json()
    assert body["error"] is None
    # Tickers are normalised and sorted before the service call.
    assert body["data"]["requested"] == ["BND", "SPY"]
    by_ticker = {row["ticker"]: row for row in body["data"]["prices"]}
    assert set(by_ticker) == {"SPY", "BND"}
    assert by_ticker["SPY"]["price"] == pytest.approx(521.3)
    assert by_ticker["BND"]["as_of"] == "2026-05-28"


def test_normalises_and_dedupes_input(test_client, fake_market):
    fake_market.set([_Latest("SPY", 521.0, "2026-05-28")])
    resp = test_client.get("/api/v1/market/prices?tickers=spy,SPY,SPY")
    assert resp.status_code == 200
    assert resp.json()["data"]["requested"] == ["SPY"]
    # Service was called once with the deduped list.
    assert fake_market.calls == [["SPY"]]


def test_partial_coverage_reports_only_priced_tickers(test_client, fake_market):
    """One delisted ticker → the resolvable one still comes back; the
    missing one appears only in ``requested`` so the UI can flag it."""
    fake_market.set([_Latest("SPY", 521.0, "2026-05-28")])
    resp = test_client.get("/api/v1/market/prices?tickers=SPY,DELIST")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["requested"] == ["DELIST", "SPY"]
    assert [r["ticker"] for r in data["prices"]] == ["SPY"]


def test_rejects_garbage_ticker_with_unprocessable(test_client, fake_market):
    resp = test_client.get("/api/v1/market/prices?tickers=$$$")
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "unprocessable"


def test_maps_upstream_failure_to_server_error(test_client, fake_market):
    fake_market.raise_with(RuntimeError("yfinance HTTP 500"))
    resp = test_client.get("/api/v1/market/prices?tickers=SPY")
    assert resp.status_code == 500
    body = resp.json()
    assert body["data"] is None
    assert body["error"]["code"] == "server_error"
    # Never leak the upstream message.
    assert "yfinance" not in body["error"]["message"]
