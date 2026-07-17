"""Consolidated research bundle endpoint: one fetch assembles every block,
fail-soft per engine, and the deterministic thesis reuses the already-built
FactPack/DCF/earnings (no duplicate engine pass). Engines are monkeypatched so
the suite is offline + deterministic."""

from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.api.v1 import research as rmod
from backend.app.main import create_app


class _Stub:
    def __init__(self, **kw):
        self._d = dict(kw)
        for k, v in kw.items():
            setattr(self, k, v)

    def model_dump(self):
        return dict(self._d)


def test_bundle_requires_auth():
    assert TestClient(create_app()).get("/api/v1/research/AAPL/bundle").status_code == 401


def test_bundle_assembles_blocks_and_reuses_engines(monkeypatch, mint_token):
    captured: dict = {}
    monkeypatch.setattr(
        rmod.rf, "build_fact_pack_cached", lambda tk: _Stub(ticker=tk, drivers=["d"])
    )
    monkeypatch.setattr(
        rmod.rfin,
        "build_research_fact_pack",
        lambda tk: _Stub(as_of="2024-12-28", data_confidence=0.8, confidence_label="high"),
    )
    monkeypatch.setattr(rmod.rdcf, "build_dcf", lambda tk: _Stub(valid=True))

    def _peers(tk):
        raise RuntimeError("boom")  # a failing engine must degrade to null, not 500

    monkeypatch.setattr(rmod.rpeers, "build_peer_comparison", _peers)
    monkeypatch.setattr(rmod.rearn, "build_earnings_comparison", lambda tk: _Stub(periods=[]))

    def _thesis(tk, **kw):
        captured.update(kw)
        return _Stub(ai_generated=False, bull_case=["x"])

    monkeypatch.setattr(rmod.rthesis, "build_thesis", _thesis)
    monkeypatch.setattr(rmod.news_svc, "get_ticker_news", lambda tk: {"unexpected": True})

    client = TestClient(create_app())
    resp = client.get(
        "/api/v1/research/AAPL/bundle", headers={"Authorization": f"Bearer {mint_token()}"}
    )
    assert resp.status_code == 200
    b = resp.json()["data"]["bundle"]
    assert b["ticker"] == "AAPL"
    assert b["fact_pack"]["drivers"] == ["d"]
    assert b["data_confidence"] == 0.8 and b["confidence_label"] == "high"
    assert b["as_of"] == "2024-12-28"
    assert b["peers"] is None  # fail-soft: the raising engine became null
    assert b["thesis"]["ai_generated"] is False
    assert "news" in b
    # The deterministic thesis was handed the already-built engines (no re-build).
    assert captured.get("fp") is not None
    assert captured.get("dcf") is not None
    assert captured.get("earn") is not None


def test_bundle_records_aggregate_dataset_health_without_ticker(monkeypatch, mint_token):
    """The bundle bumps per-DATASET counters (present / provider_error / …) —
    aggregate only, no ticker ever becomes a metrics bucket."""
    from backend.app.services import metrics

    metrics.reset()
    monkeypatch.setattr(rmod.rf, "build_fact_pack_cached", lambda tk: _Stub(ticker=tk, price=100.0))
    monkeypatch.setattr(
        rmod.rfin,
        "build_research_fact_pack",
        lambda tk: _Stub(as_of="2024-12-28", quarters=[1], annuals=[], provenance=[]),
    )
    monkeypatch.setattr(rmod.rdcf, "build_dcf", lambda tk: _Stub(valid=True))

    def _peers(tk):
        raise RuntimeError("boom")

    monkeypatch.setattr(rmod.rpeers, "build_peer_comparison", _peers)
    monkeypatch.setattr(rmod.rearn, "build_earnings_comparison", lambda tk: _Stub(quarters=[]))
    monkeypatch.setattr(rmod.rthesis, "build_thesis", lambda tk, **kw: _Stub(bull_case=["x"]))
    monkeypatch.setattr(rmod.news_svc, "get_ticker_news", lambda tk: {"items": []})

    client = TestClient(create_app())
    resp = client.get(
        "/api/v1/research/NVDA/bundle", headers={"Authorization": f"Bearer {mint_token()}"}
    )
    assert resp.status_code == 200

    snap = metrics.snapshot()["datasets"]
    by = {d["name"]: d for d in snap}
    assert by["factpack"]["present"] == 1
    assert by["financials"]["present"] == 1
    assert by["dcf"]["present"] == 1
    assert by["peers"]["provider_error"] == 1  # the leg raised → code/provider fault
    assert by["earnings"]["empty"] == 1  # reachable but nothing usable
    assert by["news"]["empty"] == 1
    # NO ticker leaks into the bucket names.
    assert "NVDA" not in {d["name"] for d in snap}
