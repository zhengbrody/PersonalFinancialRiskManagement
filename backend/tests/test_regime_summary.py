"""Tests for the composed /regime/summary readout — deterministic, no network."""

from __future__ import annotations

from backend.app.services import market_regime
from backend.app.services.regime_summary import CAVEAT, build_summary


def _snapshot(
    vix=18.4,
    vix_chg=0.6,
    vix_level="Elevated",
    fg=55.0,
    fg_rating="Greed",
    curve="Normal",
    spread=0.45,
):
    return market_regime.RegimeSnapshot(
        vix=market_regime.VixState(vix, vix_chg, vix_level),
        fear_greed=market_regime.FearGreedState(fg, fg_rating),
        yield_curve=market_regime.YieldCurveState(
            curve, spread, (spread < 0) if spread is not None else None
        ),
    )


def _ml(regime="volatile", source="model", conf=0.72):
    return {
        "regime": regime,
        "source": source,
        "confidence": conf,
        "model_version": "v1",
        "last_updated": "2026-06-23",
        "top_drivers": [
            {"feature": "vol_3m", "label": "3-month volatility", "vs_normal": "above normal"},
            {"feature": "vix", "label": "VIX level", "vs_normal": "elevated"},
        ],
    }


def test_build_summary_model_present():
    out = build_summary(_ml(), _snapshot())
    assert out["regime_state"] == "volatile"
    assert out["label"] == "Elevated"
    assert out["confidence"] == 0.72
    assert out["source"] == "model"
    assert out["headline"] == "Market risk-state: Elevated"
    assert len(out["drivers"]) == 2
    assert out["drivers"][0]["label"] == "3-month volatility"
    # post_text is quotable, bounded, carries the label + macro + the site, no advice.
    pt = out["post_text"]
    assert "Elevated" in pt and "VIX 18.4" in pt and "mindmarket.app/risk-today" in pt
    assert len(pt) <= 280
    for word in ("buy", "sell", "should"):
        assert word not in pt.lower()


def test_caveat_is_compliant_and_in_payload():
    out = build_summary(_ml(), _snapshot())
    assert out["caveat"] == CAVEAT
    assert "not investment advice" in CAVEAT
    assert "does not change your Health Score" in CAVEAT


def test_build_summary_model_unavailable_falls_back_to_macro():
    """Model down (regime None / source unavailable) but the macro snapshot is
    still live — we render the snapshot, not a 500-equivalent blank."""
    ml = {"source": "unavailable"}
    out = build_summary(ml, _snapshot())
    assert out["regime_state"] is None
    assert out["label"] is None
    assert out["source"] == "unavailable"
    assert out["headline"] == "Market risk read temporarily unavailable"
    assert out["drivers"] == []
    # macro still surfaces in the body + post_text.
    assert out["vix"]["current"] == 18.4
    assert "VIX 18.4" in out["post_text"]


def test_build_summary_everything_down():
    ml = {"source": "unavailable"}
    blank = market_regime.RegimeSnapshot(
        vix=market_regime.VixState(None, None, None),
        fear_greed=market_regime.FearGreedState(None, None),
        yield_curve=market_regime.YieldCurveState(None, None, None),
    )
    out = build_summary(ml, blank)
    assert out["source"] == "unavailable"
    assert out["vix"]["current"] is None
    # Still a well-formed, advice-free post_text ending at the site.
    assert out["post_text"].endswith("mindmarket.app/risk-today")


def test_endpoint_returns_envelope(test_client, monkeypatch):
    monkeypatch.setattr(
        "backend.app.api.v1.regime_summary.regime_summary_service.get_regime_summary",
        lambda: build_summary(_ml(), _snapshot()),
    )
    resp = test_client.get("/api/v1/regime/summary")
    assert resp.status_code == 200
    body = resp.json()
    assert body["error"] is None
    assert body["data"]["label"] == "Elevated"
    assert body["data"]["caveat"] == CAVEAT
    assert body["meta"]["request_id"]
