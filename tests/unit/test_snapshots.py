"""Tests for libs/auth/snapshots.py.

Covered:
- build_snapshot_payload: shape + NaN/None handling
- compute_delta: pure delta math, empty-state, top-position swap detection
- list_recent_snapshots / write_snapshot: safe degradation when DB
  unreachable (anonymous user, no table, RLS blocks) — must never raise.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from libs.auth import snapshots as snap

# ── build_snapshot_payload ──────────────────────────────────────────


@dataclass
class _FakeReport:
    annual_return: float = 0.10
    annual_volatility: float = 0.18
    sharpe_ratio: float = 0.55
    max_drawdown: float = -0.22
    var_95: float = -0.034
    var_99: float = -0.052
    cvar_95: float = -0.041
    stress_loss: float = -0.18


def test_build_snapshot_payload_keeps_only_finite_values():
    payload = snap.build_snapshot_payload(
        report=_FakeReport(),
        weights={"NVDA": 0.4, "AAPL": 0.3, "BAD": float("nan")},
        meta={
            "net_equity": 105_000,
            "total_long": 120_000,
            "margin_loan": 15_000,
            "leverage": 1.4,
            "data_quality": {"stale": False, "fmp_unavailable": True},
            "sector_exposure": {"Tech": 0.7, "Bad": float("inf")},
        },
        source="auto",
    )

    # Headline fields land on top-level columns.
    assert payload["net_equity"] == 105_000
    assert payload["margin_loan"] == 15_000
    assert payload["source"] == "auto"

    # Top positions: ordered desc and bad weight filtered.
    tickers = [p["ticker"] for p in payload["top_positions"]]
    assert tickers == ["NVDA", "AAPL"]

    # Sector with infinite weight is dropped.
    assert "Bad" not in payload["sector_exposure"]
    assert payload["sector_exposure"]["Tech"] == 0.7

    # Risk metrics only include finite scalars.
    risk = payload["risk_metrics"]
    assert risk["sharpe_ratio"] == 0.55
    assert risk["var_95"] == -0.034


def test_build_snapshot_payload_omits_missing_capital_columns():
    """If meta has no cash_balance/leverage, those keys should be
    dropped so the row inserts as DB DEFAULT (NULL)."""
    payload = snap.build_snapshot_payload(
        report=None,
        weights={"SPY": 1.0},
        meta={"net_equity": 50_000},
    )
    assert payload["net_equity"] == 50_000
    assert "cash_balance" not in payload
    assert "leverage" not in payload
    # Empty risk_metrics is fine (LLM/UI handle empty).
    assert payload["risk_metrics"] == {}


# ── compute_delta ───────────────────────────────────────────────────


def test_compute_delta_empty_when_no_prior():
    out = snap.compute_delta(curr={"net_equity": 100_000}, prev=None)
    assert out["has_prior"] is False


def test_compute_delta_scalars():
    curr = {
        "net_equity": 110_000,
        "leverage": 1.45,
        "margin_loan": 20_000,
        "risk_metrics": {"var_95": -0.045, "sharpe_ratio": 0.6, "max_drawdown": -0.20},
    }
    prev = {
        "net_equity": 100_000,
        "leverage": 1.30,
        "margin_loan": 18_000,
        "risk_metrics": {"var_95": -0.030, "sharpe_ratio": 0.50, "max_drawdown": -0.18},
    }
    d = snap.compute_delta(curr, prev)
    assert d["has_prior"] is True
    assert d["net_equity"]["delta"] == 10_000
    assert d["net_equity"]["pct_change"] == pytest.approx(0.10, abs=1e-6)
    assert d["leverage"]["delta"] == pytest.approx(0.15, abs=1e-6)
    assert d["margin_loan"]["delta"] == 2_000
    # VaR more negative means risk worsened — the raw delta is the
    # number; consumers decide good/bad.
    assert d["var_95"]["delta"] == pytest.approx(-0.015, abs=1e-6)
    assert d["sharpe"]["delta"] == pytest.approx(0.10, abs=1e-6)


def test_compute_delta_pct_change_none_when_prev_zero():
    """Division-by-zero protection: pct_change must be None, not Inf."""
    d = snap.compute_delta(
        curr={"net_equity": 5_000},
        prev={"net_equity": 0},
    )
    assert d["net_equity"]["delta"] == 5_000
    assert d["net_equity"]["pct_change"] is None


def test_compute_delta_top_position_swap_detected():
    curr = {
        "top_positions": [
            {"ticker": "NVDA", "weight": 0.32},
            {"ticker": "AAPL", "weight": 0.30},
        ]
    }
    prev = {
        "top_positions": [
            {"ticker": "AAPL", "weight": 0.35},
            {"ticker": "NVDA", "weight": 0.28},
        ]
    }
    d = snap.compute_delta(curr, prev)
    assert d["top_concentration"]["changed"] is True
    assert d["top_concentration"]["delta"] is None  # different tickers
    assert d["top_concentration"]["current"]["ticker"] == "NVDA"


def test_compute_delta_top_position_same_ticker_uses_weight_delta():
    curr = {"top_positions": [{"ticker": "NVDA", "weight": 0.30}]}
    prev = {"top_positions": [{"ticker": "NVDA", "weight": 0.22}]}
    d = snap.compute_delta(curr, prev)
    assert d["top_concentration"]["changed"] is False
    assert d["top_concentration"]["delta"] == pytest.approx(0.08, abs=1e-6)


def test_compute_delta_missing_fields_render_as_none():
    """When a field exists on neither snapshot, the slot is None so
    the UI can decide whether to render."""
    curr = {"net_equity": 100}
    # prev needs at least one truthy field to count as a real prior
    # snapshot (an empty dict means "no prior" by convention).
    prev = {"placeholder": True}
    d = snap.compute_delta(curr, prev)
    assert d["leverage"] is None
    # net_equity has only one side → also None.
    assert d["net_equity"] is None


# ── DB-touching helpers: must NOT raise on failure ──────────────────


def test_write_snapshot_returns_none_when_unauthenticated(monkeypatch):
    """Anonymous user (demo flow) gets None, never an exception."""
    from libs.auth.client import AuthError

    def _raise(*_a, **_kw):
        raise AuthError("not authed")

    monkeypatch.setattr(snap, "_authed_client", _raise)
    result = snap.write_snapshot(
        report=_FakeReport(),
        weights={"SPY": 1.0},
        meta={"net_equity": 100_000},
    )
    assert result is None


def test_list_recent_snapshots_returns_empty_on_db_failure(monkeypatch, caplog):
    """Missing table / RLS blocks must collapse to []."""

    class _Boom:
        def table(self, *_a, **_kw):
            raise RuntimeError("relation does not exist")

    monkeypatch.setattr(snap, "_authed_client", lambda: _Boom())
    assert snap.list_recent_snapshots(limit=2) == []


def test_list_recent_snapshots_limit_zero_short_circuits(monkeypatch):
    """Guard against accidental .limit(0) DB calls."""
    called: list[bool] = []

    def _client():
        called.append(True)
        raise AssertionError("should not be called for limit=0")

    monkeypatch.setattr(snap, "_authed_client", _client)
    assert snap.list_recent_snapshots(limit=0) == []
    assert called == []
