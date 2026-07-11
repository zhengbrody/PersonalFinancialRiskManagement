"""Auditable Health Score methodology version (SCORE_VERSION).

Proves the four contract points, all offline (no LLM, no DB):
  1. ONE source — `context_cache.RISK_ENGINE_VERSION` aliases `SCORE_VERSION`;
     the changelog carries the current version.
  2. The version rides the API response AND every snapshot.
  3. Cross-version trend comparison is refused (no market/holdings delta).
  4. Stamping the version does NOT change any computed number (pure pass-through).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from backend.app.api.v1.risk import _serialize_score
from backend.app.schemas.score_changes import ScoreChangeRequest
from backend.app.services import context_cache as cc
from backend.app.services import score_changes, snapshots
from libs.mindmarket_core.portfolio_scoring import AssetPosition, score_portfolio
from libs.mindmarket_core.score_version import (
    LEGACY_SCORE_VERSION,
    SCORE_VERSION,
    SCORE_VERSION_CHANGELOG,
    is_comparable,
)

_DIMS = {"risk_match": 6.0, "risk_adjusted_return": 6.0, "downside_protection": 6.0}
_DIMS_WORSE = {"risk_match": 5.0, "risk_adjusted_return": 5.0, "downside_protection": 5.0}


def _score(seed: int = 1, drift: float = 0.0005):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2024-01-01", periods=252)
    frame = pd.DataFrame(
        {"AAA": rng.normal(drift, 0.01, 252), "BBB": rng.normal(drift * 0.5, 0.012, 252)},
        index=idx,
    )
    pos = [
        AssetPosition("AAA", "A", "public_security", 60_000, 55_000),
        AssetPosition("BBB", "B", "public_security", 40_000, 38_000),
    ]
    return score_portfolio(pos, frame, benchmark_returns=frame["AAA"], risk_preference=3)


# ── 1. single source ────────────────────────────────────────────────────────


def test_risk_engine_version_is_the_single_score_version():
    assert cc.RISK_ENGINE_VERSION == SCORE_VERSION
    assert SCORE_VERSION.startswith("mindmarket-score-v")
    # The current version is documented in the changelog (rendered on the page).
    assert any(e["version"] == SCORE_VERSION for e in SCORE_VERSION_CHANGELOG)


def test_is_comparable_matrix():
    assert is_comparable(SCORE_VERSION, SCORE_VERSION) is True
    assert is_comparable(LEGACY_SCORE_VERSION, SCORE_VERSION) is False
    assert is_comparable(None, SCORE_VERSION) is False
    assert is_comparable("", SCORE_VERSION) is False
    assert is_comparable("mindmarket-score-v0.9.0", SCORE_VERSION) is False


# ── 2. version rides the API response + 4. numbers unchanged ────────────────


def test_score_response_carries_version_without_changing_numbers():
    s = _score()
    resp = _serialize_score(s)
    assert resp.score_version == SCORE_VERSION
    # Every computed number is a pure pass-through of the engine — the version is
    # purely additive (this is the "math unchanged" guarantee for the response).
    assert resp.overall_score == s.overall_score
    assert resp.base_overall == s.base_overall
    for k, d in s.dimensions.items():
        assert resp.dimensions[k].score == float(d.score)
    assert resp.metrics.sharpe_ratio == s.metrics.sharpe_ratio
    assert resp.metrics.annual_volatility == s.metrics.annual_volatility
    assert resp.metrics.max_drawdown == s.metrics.max_drawdown
    assert resp.metrics.var_95_daily == s.metrics.var_95_daily


# ── 2. version rides the snapshot ───────────────────────────────────────────


class _Resp:
    def __init__(self, data):
        self.data = data


class _CaptureTable:
    def __init__(self, captured):
        self.captured = captured
        self._insert = None

    def select(self, *a, **k):
        return self

    def insert(self, row):
        self._insert = row
        return self

    def gte(self, *a):
        return self

    def lt(self, *a):
        return self

    def order(self, *a, **k):
        return self

    def limit(self, n):
        return self

    def execute(self):
        if self._insert is not None:
            self.captured.update(self._insert)
            return _Resp([self._insert])
        return _Resp([])  # dedup select → "no recent row" → insert proceeds


class _CaptureSB:
    def __init__(self, captured):
        self.captured = captured

    def table(self, name):
        return _CaptureTable(self.captured)


def test_snapshot_persists_the_version(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(snapshots, "_client", lambda tok: _CaptureSB(captured))
    snapshots.record_snapshot("tok", score=_score())
    assert captured.get("score_version") == SCORE_VERSION


# ── 3. cross-version comparison is refused ──────────────────────────────────


def _req(overall: int, dims: dict) -> ScoreChangeRequest:
    return ScoreChangeRequest(
        window="previous",
        overall_score=overall,
        base_overall=overall,
        dimensions=dims,
        metrics={"annual_volatility": 0.15, "sharpe_ratio": 0.8},
        confidence="high",
    )


def _prev(overall: int, dims: dict, version) -> dict:
    row = {
        "created_at": "2026-06-13T00:00:00+00:00",
        "risk_metrics": {"overall_score": overall, "base_overall": overall, "dimensions": dims},
        "data_quality": {"confidence": "high"},
        "top_positions": [],
    }
    if version is not None:
        row["score_version"] = version
    return row


def test_same_version_comparison_is_allowed():
    rep = score_changes.build_change_report(
        _req(500, _DIMS), _prev(560, _DIMS_WORSE, SCORE_VERSION)
    )
    assert rep.comparable is True
    assert rep.score_delta == 500 - 560
    assert rep.top_drivers  # decomposition present
    assert rep.current_score_version == SCORE_VERSION
    assert rep.previous_score_version == SCORE_VERSION


def test_cross_version_comparison_is_blocked():
    rep = score_changes.build_change_report(
        _req(500, _DIMS), _prev(560, _DIMS_WORSE, "mindmarket-score-v0.9.0")
    )
    assert rep.available is True
    assert rep.comparable is False
    assert rep.score_delta is None  # refuses a comparable delta
    assert rep.component_deltas == []  # no market/holdings decomposition leaks
    assert rep.input_changes == []
    assert rep.top_drivers == []
    assert rep.previous_score_version == "mindmarket-score-v0.9.0"
    assert rep.current_score_version == SCORE_VERSION
    # A genuine version-to-version change DOES say the methodology changed.
    assert "methodology changed" in rep.summary.lower()
    # It still shows the two raw scores (just not framed as a comparable move).
    assert rep.current_score == 500
    assert rep.previous_score == 560


def test_legacy_or_untagged_snapshot_is_not_comparable_without_claiming_a_change():
    # A pre-versioning snapshot has UNKNOWN provenance — we must NOT claim the
    # methodology changed (it may not have; v1.0.0 is documented as no-math-change).
    for version in ("legacy", None):
        rep = score_changes.build_change_report(_req(500, _DIMS), _prev(560, _DIMS_WORSE, version))
        assert rep.comparable is False, version
        assert rep.score_delta is None, version
        assert "predates" in rep.summary.lower(), version
        assert "methodology changed" not in rep.summary.lower(), version
