"""Tests for libs/risk/action_cards.py.

The action card generator is the rule-based fallback that fires even
when the LLM is down. These tests pin the trigger thresholds — if a
threshold changes (e.g. 'critical margin distance' moves from 15% to
20%), this file should be updated AND a product-decision note added.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from libs.risk import generate_action_cards
from libs.risk.action_cards import ActionCard


@dataclass
class _FakeReport:
    margin_call_info: dict | None = None
    sharpe_ratio: float | None = None
    annual_volatility: float | None = None
    component_var_pct: Any = None


def _id_set(cards: list[ActionCard]) -> set[str]:
    return {c.id for c in cards}


# ── margin rules ────────────────────────────────────────────────────


def test_margin_distance_critical_under_15pct():
    report = _FakeReport(margin_call_info={"has_margin": True, "distance_to_call_pct": 0.10})
    cards = generate_action_cards(report=report, weights={"SPY": 1.0})
    assert "margin_distance_critical" in _id_set(cards)
    crit = next(c for c in cards if c.id == "margin_distance_critical")
    assert crit.severity == "critical"


def test_margin_distance_watch_between_15_and_30():
    report = _FakeReport(margin_call_info={"has_margin": True, "distance_to_call_pct": 0.22})
    cards = generate_action_cards(report=report, weights={"SPY": 1.0})
    ids = _id_set(cards)
    assert "margin_distance_critical" not in ids
    assert "margin_distance_watch" in ids


def test_margin_distance_no_card_when_buffer_healthy():
    report = _FakeReport(margin_call_info={"has_margin": True, "distance_to_call_pct": 0.50})
    cards = generate_action_cards(report=report, weights={"SPY": 1.0})
    ids = _id_set(cards)
    assert "margin_distance_critical" not in ids
    assert "margin_distance_watch" not in ids


def test_no_margin_means_no_margin_card():
    report = _FakeReport(margin_call_info={"has_margin": False})
    cards = generate_action_cards(report=report, weights={"SPY": 1.0})
    assert not any(c.id.startswith("margin_") for c in cards)


# ── concentration ───────────────────────────────────────────────────


def test_concentration_critical_when_top_over_50pct():
    cards = generate_action_cards(weights={"NVDA": 0.60, "AAPL": 0.40})
    top = next(c for c in cards if c.id == "concentration_top")
    assert top.severity == "critical"
    assert "NVDA" in top.title


def test_concentration_important_when_30_to_50():
    cards = generate_action_cards(weights={"NVDA": 0.35, "AAPL": 0.30, "MSFT": 0.35})
    top = next(c for c in cards if c.id == "concentration_top")
    assert top.severity == "important"


def test_no_concentration_card_when_well_diversified():
    weights = {f"X{i}": 0.10 for i in range(10)}
    cards = generate_action_cards(weights=weights)
    assert not any(c.id == "concentration_top" for c in cards)


# ── sharpe + vol ────────────────────────────────────────────────────


def test_sharpe_negative_card():
    cards = generate_action_cards(report=_FakeReport(sharpe_ratio=-0.20), weights={"SPY": 1.0})
    assert "sharpe_negative" in _id_set(cards)


def test_sharpe_low_card():
    cards = generate_action_cards(report=_FakeReport(sharpe_ratio=0.30), weights={"SPY": 1.0})
    assert "sharpe_low" in _id_set(cards)


def test_sharpe_healthy_emits_no_card():
    cards = generate_action_cards(report=_FakeReport(sharpe_ratio=0.85), weights={"SPY": 1.0})
    assert not any(c.id.startswith("sharpe_") for c in cards)


def test_vol_high_card_triggers_at_25pct():
    cards = generate_action_cards(report=_FakeReport(annual_volatility=0.30), weights={"SPY": 1.0})
    assert "vol_high" in _id_set(cards)


# ── data quality ────────────────────────────────────────────────────


def test_cost_basis_card_when_coverage_below_70():
    cards = generate_action_cards(
        weights={"SPY": 1.0},
        meta={
            "position_cost_info": {
                "coverage_by_mv_pct": 0.55,
                "tickers_missing_cost": ["NVDA", "META"],
            }
        },
    )
    card = next(c for c in cards if c.id == "cost_basis_partial")
    assert "55%" in card.evidence
    assert card.confidence == "medium"


def test_cash_zero_card_only_when_value_is_zero():
    cards_zero = generate_action_cards(weights={"SPY": 1.0}, meta={"cash_balance": 0})
    assert "cash_zero" in _id_set(cards_zero)
    cards_pos = generate_action_cards(weights={"SPY": 1.0}, meta={"cash_balance": 5_000})
    assert "cash_zero" not in _id_set(cards_pos)


def test_missing_tickers_emits_data_missing_card():
    cards = generate_action_cards(
        weights={"SPY": 1.0},
        meta={"missing": ["DELISTED", "NOSUCH"]},
    )
    card = next(c for c in cards if c.id == "data_missing")
    assert card.metadata["missing_count"] == 2


# ── snapshot delta ──────────────────────────────────────────────────


def test_delta_equity_drop_card_at_5pct_threshold():
    cards = generate_action_cards(
        weights={"SPY": 1.0},
        snapshot_delta={
            "has_prior": True,
            "net_equity": {
                "current": 95_000,
                "previous": 100_000,
                "delta": -5_000,
                "pct_change": -0.05,
            },
        },
    )
    assert "delta_equity_drop" in _id_set(cards)


def test_delta_top_swap_emits_watch_card():
    cards = generate_action_cards(
        weights={"NVDA": 0.30, "AAPL": 0.30},
        snapshot_delta={
            "has_prior": True,
            "top_concentration": {
                "current": {"ticker": "NVDA", "weight": 0.30},
                "previous": {"ticker": "AAPL", "weight": 0.32},
                "changed": True,
            },
        },
    )
    card = next(c for c in cards if c.id == "delta_top_swap")
    assert card.severity == "watch"


# ── ordering + caps ─────────────────────────────────────────────────


def test_cards_sorted_critical_first_then_watch():
    cards = generate_action_cards(
        report=_FakeReport(
            margin_call_info={"has_margin": True, "distance_to_call_pct": 0.10},
            sharpe_ratio=0.30,
            annual_volatility=0.30,
        ),
        weights={"NVDA": 0.55, "AAPL": 0.45},
    )
    severities = [c.severity for c in cards]
    # First card must be critical, then severities must be monotonically
    # non-decreasing in the precedence order critical < important < watch < info.
    order = {"critical": 0, "important": 1, "watch": 2, "info": 3}
    ranks = [order[s] for s in severities]
    assert ranks == sorted(ranks)
    assert severities[0] == "critical"


def test_max_cards_caps_output():
    cards = generate_action_cards(
        report=_FakeReport(
            margin_call_info={"has_margin": True, "distance_to_call_pct": 0.10},
            sharpe_ratio=-0.1,
            annual_volatility=0.30,
        ),
        weights={"NVDA": 0.60, "AAPL": 0.40},
        meta={"cash_balance": 0, "missing": ["X"]},
        max_cards=2,
    )
    assert len(cards) == 2


def test_action_card_is_json_serialisable():
    """The cards travel through session_state and into save_insights;
    if any field can't round-trip JSON, persistence breaks."""
    import json

    cards = generate_action_cards(weights={"NVDA": 0.55, "AAPL": 0.45})
    raw = json.dumps([c.to_dict() for c in cards])
    parsed = json.loads(raw)
    assert isinstance(parsed, list)
    if parsed:
        assert parsed[0]["title"]
        assert parsed[0]["severity"] in {"critical", "important", "watch", "info"}


def test_generator_never_raises_on_empty_inputs():
    """Owner empties / brand-new user paths must not blow up."""
    assert generate_action_cards() == []
    assert generate_action_cards(report=None, weights=None, meta=None) == []


def test_component_var_overrides_raw_weight_for_top_concentration():
    """When component VaR is available, the concentration card should
    cite it (not raw weight) as basis."""
    import pandas as pd

    report = _FakeReport(component_var_pct=pd.Series({"NVDA": 0.55, "AAPL": 0.20}))
    cards = generate_action_cards(report=report, weights={"NVDA": 0.10, "AAPL": 0.30})
    card = next(c for c in cards if c.id == "concentration_top")
    assert card.metadata["ticker"] == "NVDA"
    assert card.metadata["basis"] == "var"
    assert card.severity == "critical"  # 55% via VaR
