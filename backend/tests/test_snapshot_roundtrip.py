"""Snapshot record → windowed-fetch → change-report round trip (Slice 4).

Exercises the full deterministic loop against a FAKE Supabase client (in-memory),
so it's offline + DB-free: record_snapshot persists the richer payload (per-
dimension scores + data-quality), get_snapshot_at_window reads the prior-day row,
and build_change_report attributes the move — proving a one-day change is
explainable by the component deltas, end to end.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from backend.app.schemas.score_changes import ScoreChangeRequest
from backend.app.services import score_changes, snapshots
from libs.mindmarket_core.portfolio_scoring import AssetPosition, score_portfolio


class _Resp:
    def __init__(self, data):
        self.data = data


class _FakeTable:
    """Minimal stand-in for the supabase-py query builder chain used by snapshots."""

    def __init__(self, store):
        self.store = store
        self._filters: list[tuple] = []
        self._order = None
        self._limit = None
        self._insert = None

    def select(self, *a, **k):
        return self

    def insert(self, row):
        self._insert = row
        return self

    def gte(self, col, val):
        self._filters.append((col, ">=", val))
        return self

    def lt(self, col, val):
        self._filters.append((col, "<", val))
        return self

    def order(self, col, desc=False):
        self._order = (col, desc)
        return self

    def limit(self, n):
        self._limit = n
        return self

    def execute(self):
        if self._insert is not None:
            row = dict(self._insert)
            row.setdefault("created_at", self.store["now"])
            self.store["rows"].append(row)
            return _Resp([row])
        rows = [r for r in self.store["rows"] if self._match(r)]
        if self._order:
            col, desc = self._order
            rows = sorted(rows, key=lambda r: r.get(col) or "", reverse=desc)
        if self._limit is not None:
            rows = rows[: self._limit]
        return _Resp(rows)

    def _match(self, r) -> bool:
        for col, op, val in self._filters:
            v = r.get(col)
            if v is None:
                return False
            if op == ">=" and not (v >= val):
                return False
            if op == "<" and not (v < val):
                return False
        return True


class _FakeSB:
    def __init__(self, store):
        self.store = store

    def table(self, name):
        return _FakeTable(self.store)


def _build_score(seed: int, drift: float):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2024-01-01", periods=252)
    frame = pd.DataFrame(
        {
            "AAA": rng.normal(drift, 0.01, 252),
            "BBB": rng.normal(drift * 0.5, 0.012, 252),
        },
        index=idx,
    )
    pos = [
        AssetPosition("AAA", "A", "public_security", 60_000, 55_000),
        AssetPosition("BBB", "B", "public_security", 40_000, 38_000),
    ]
    return score_portfolio(pos, frame, benchmark_returns=frame["AAA"], risk_preference=3)


def test_snapshot_record_then_window_then_change_report(monkeypatch):
    now = datetime.now(timezone.utc)
    # The prior snapshot lands ~25h ago so the "previous" window (older than 20h)
    # finds it.
    store = {"rows": [], "now": (now - timedelta(hours=25)).isoformat()}
    monkeypatch.setattr(snapshots, "_client", lambda token: _FakeSB(store))

    prev_score = _build_score(seed=1, drift=0.0006)  # healthier
    snapshots.record_snapshot(
        "tok",
        score=prev_score,
        top_positions=[{"ticker": "AAA", "weight": 0.6}, {"ticker": "BBB", "weight": 0.4}],
    )
    # The richer payload is persisted (no migration — existing JSONB columns).
    assert len(store["rows"]) == 1
    stored = store["rows"][0]
    assert "dimensions" in stored["risk_metrics"]
    assert stored["risk_metrics"]["overall_score"] == prev_score.overall_score
    assert stored["data_quality"]["confidence"] in ("high", "medium", "low")

    # Windowed fetch returns the prior-day baseline.
    prev = snapshots.get_snapshot_at_window("tok", "previous")
    assert prev is not None
    assert prev["risk_metrics"]["overall_score"] == prev_score.overall_score

    # A worse "today" score → the change report attributes the move.
    cur = _build_score(seed=2, drift=-0.001)
    req = ScoreChangeRequest(
        window="previous",
        overall_score=cur.overall_score,
        base_overall=cur.base_overall,
        dimensions={k: d.score for k, d in cur.dimensions.items()},
        metrics={
            "annual_volatility": cur.metrics.annual_volatility,
            "sharpe_ratio": cur.metrics.sharpe_ratio,
            "max_drawdown": cur.metrics.max_drawdown,
        },
        confidence=cur.metrics.confidence,
    )
    report = score_changes.build_change_report(req, prev)
    assert report.available is True
    assert report.score_delta == cur.overall_score - prev_score.overall_score
    # The one-day move is explainable by the component deltas (exact up to the
    # per-stage integer rounding of dimension scores + the overall).
    summed = sum((c.points_contribution or 0) for c in report.component_deltas)
    assert abs(summed - (report.score_delta or 0)) <= 3


def test_snapshot_dedup_skips_a_recent_write(monkeypatch):
    """A second score within the gap window must NOT write a duplicate snapshot."""
    now = datetime.now(timezone.utc)
    store = {"rows": [], "now": now.isoformat()}  # "now" → inside the 20h gap
    monkeypatch.setattr(snapshots, "_client", lambda token: _FakeSB(store))
    s = _build_score(seed=3, drift=0.0004)
    snapshots.record_snapshot("tok", score=s)
    snapshots.record_snapshot("tok", score=s)  # deduped
    assert len(store["rows"]) == 1
