"""Tests for the composed /regime/summary readout — deterministic, no network.

The readout leads with the VALIDATED signal (elevated-risk probability) and
degrades to deterministic market context when the model tier is inactive, the
data is stale, or drift monitoring flags a problem. The 4-class label is only
secondary context (on 4-class accuracy the model loses to persistence)."""

from __future__ import annotations

from datetime import date

from backend.app.services import market_regime
from backend.app.services.regime_summary import CAVEAT, build_summary

_TODAY = date(2026, 6, 24)  # one day after the fixture's data date → fresh


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


def _ml(regime="volatile", source="model", conf=0.72, probs=None):
    return {
        "regime": regime,
        "source": source,
        "confidence": conf,
        "class_probabilities": (
            probs
            if probs is not None
            else {"risk_on": 0.15, "neutral": 0.27, "volatile": 0.40, "stress": 0.18}
        ),
        "model_version": "v1",
        "last_updated": "2026-06-23",
        "top_drivers": [
            {"feature": "vol_3m", "label": "3-month volatility", "vs_normal": "above normal"},
            {"feature": "vix", "label": "VIX level", "vs_normal": "elevated"},
        ],
    }


_HEALTHY = {"status": "ok", "overall_status": "healthy"}


def test_leads_with_elevated_risk_probability_when_healthy():
    out = build_summary(_ml(), _snapshot(), _HEALTHY, today=_TODAY)
    # Primary = probability (P(volatile)+P(stress) = 0.40+0.18 = 0.58 → 58%, High/Very high).
    assert out["elevated_risk_probability"] == 0.58
    assert out["probability_band"] == "Very high"
    assert out["headline"] == "Elevated-risk probability: 58%"
    assert out["degraded"] is False
    assert out["degraded_reason"] is None
    assert out["health_status"] == "healthy"
    # 4-class label is still carried, but only as SECONDARY context.
    assert out["regime_state"] == "volatile"
    assert out["label"] == "Elevated"
    assert out["as_of"] == "2026-06-23"
    assert out["model_version"] == "v1"
    # post_text uses probability + limitation language, no advice.
    pt = out["post_text"]
    assert "Elevated-risk probability 58%" in pt
    assert "not a price or return forecast" in pt
    assert "mindmarket.app/risk-today" in pt
    assert len(pt) <= 280
    for word in ("buy", "sell", "should"):
        assert word not in pt.lower()


def test_probability_bands():
    def band_for(pv, ps):
        out = build_summary(
            _ml(probs={"risk_on": 1 - pv - ps, "neutral": 0.0, "volatile": pv, "stress": ps}),
            _snapshot(),
            _HEALTHY,
            today=_TODAY,
        )
        return out["probability_band"]

    assert band_for(0.03, 0.02) == "Low"  # 0.05
    assert band_for(0.10, 0.05) == "Moderate"  # 0.15
    assert band_for(0.25, 0.10) == "High"  # 0.35
    assert band_for(0.40, 0.20) == "Very high"  # 0.60


def test_drift_degrades_to_market_context_no_probability():
    out = build_summary(
        _ml(), _snapshot(), {"status": "ok", "overall_status": "drift"}, today=_TODAY
    )
    assert out["degraded"] is True
    assert out["degraded_reason"] == "model_drift"
    assert out["elevated_risk_probability"] is None
    assert out["probability_band"] is None
    assert out["headline"] == "Today's market snapshot"
    # deterministic market context still surfaces.
    assert out["vix"]["current"] == 18.4
    assert "Market snapshot" in out["post_text"]
    assert "VIX 18.4" in out["post_text"]


def test_stale_data_degrades():
    out = build_summary(_ml(), _snapshot(), _HEALTHY, today=date(2026, 7, 15))
    assert out["degraded"] is True
    assert out["degraded_reason"] == "stale_data"
    assert out["elevated_risk_probability"] is None


def test_heuristic_tier_has_no_probability_and_degrades():
    ml = {
        "regime": "neutral",
        "source": "heuristic_fallback",
        "class_probabilities": {},
        "last_updated": "2026-06-23",
    }
    out = build_summary(ml, _snapshot(), {"status": "unavailable"}, today=_TODAY)
    assert out["degraded"] is True
    assert out["degraded_reason"] == "model_unavailable"
    assert out["elevated_risk_probability"] is None
    assert out["regime_state"] == "neutral"  # still carried as secondary context
    assert "VIX 18.4" in out["post_text"]


def test_unhealthy_serving_status_degrades_even_if_model_tier():
    out = build_summary(
        _ml(), _snapshot(), {"status": "not_ready", "overall_status": None}, today=_TODAY
    )
    assert out["degraded"] is True
    assert out["degraded_reason"] == "health_not_ready"
    assert out["elevated_risk_probability"] is None


def test_caveat_is_compliant_and_in_payload():
    out = build_summary(_ml(), _snapshot(), _HEALTHY, today=_TODAY)
    assert out["caveat"] == CAVEAT
    assert "not investment advice" in CAVEAT
    assert "does not change your Health Score" in CAVEAT


def test_everything_down_still_well_formed():
    ml = {"source": "unavailable"}
    blank = market_regime.RegimeSnapshot(
        vix=market_regime.VixState(None, None, None),
        fear_greed=market_regime.FearGreedState(None, None),
        yield_curve=market_regime.YieldCurveState(None, None, None),
    )
    out = build_summary(ml, blank, {}, today=_TODAY)
    assert out["degraded"] is True
    assert out["elevated_risk_probability"] is None
    assert out["headline"] == "Market read temporarily unavailable"
    assert out["post_text"].endswith("mindmarket.app/risk-today")


def test_endpoint_returns_envelope(test_client, monkeypatch):
    monkeypatch.setattr(
        "backend.app.api.v1.regime_summary.regime_summary_service.get_regime_summary",
        lambda: build_summary(_ml(), _snapshot(), _HEALTHY, today=_TODAY),
    )
    resp = test_client.get("/api/v1/regime/summary")
    assert resp.status_code == 200
    body = resp.json()
    assert body["error"] is None
    assert body["data"]["elevated_risk_probability"] == 0.58
    assert body["data"]["degraded"] is False
    assert body["data"]["caveat"] == CAVEAT
    assert body["meta"]["request_id"]
