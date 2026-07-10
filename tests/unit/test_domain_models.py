"""Tests for the Pydantic input-validation layer at the Portfolio Copilot boundary.

The math layer assumes finite, non-negative, well-typed input. These
tests prove the boundary actually catches the dangerous inputs (NaN,
negative shares, formula-injection tickers, impossibly-large cost
bases) BEFORE they reach the frozen dataclasses + NumPy math.
"""

from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from domain.models import (
    AgentResponse,
    AssetPosition,
    AssetPositionInput,
    PortfolioInput,
)

# ── AssetPositionInput field-level validation ─────────────────────────


def test_valid_position_round_trips_to_frozen_dataclass():
    raw = AssetPositionInput(
        ticker="aapl",  # lowercase → normalized to AAPL
        name="Apple Inc.",
        asset_type="public_security",
        market_value=10_000.0,
        cost_basis=8_000.0,
    )
    assert raw.ticker == "AAPL"
    pos = raw.to_position()
    assert isinstance(pos, AssetPosition)
    assert pos.ticker == "AAPL"
    assert pos.market_value == 10_000.0


def test_negative_market_value_rejected():
    with pytest.raises(ValidationError, match="greater than or equal to 0"):
        AssetPositionInput(
            ticker="AAPL",
            name="Apple",
            asset_type="public_security",
            market_value=-100.0,
        )


def test_nan_market_value_rejected():
    with pytest.raises(ValidationError, match="finite"):
        AssetPositionInput(
            ticker="AAPL",
            name="Apple",
            asset_type="public_security",
            market_value=math.nan,
        )


def test_inf_cost_basis_rejected():
    with pytest.raises(ValidationError, match="finite"):
        AssetPositionInput(
            ticker="AAPL",
            name="Apple",
            asset_type="public_security",
            market_value=1000,
            cost_basis=math.inf,
        )


def test_malformed_ticker_rejected():
    """Formula-injection / XSS strings must die at the boundary so they
    can't poison downstream HTML rendering or DB writes."""
    with pytest.raises(ValidationError, match="not a recognizable symbol"):
        AssetPositionInput(
            ticker="=cmd|'/c calc'!A0",
            name="malicious",
            asset_type="public_security",
            market_value=1000,
        )


def test_class_share_and_crypto_tickers_accepted():
    """BRK.B and BTC-USD are legitimate symbols and must pass."""
    p1 = AssetPositionInput(
        ticker="BRK.B",
        name="Berkshire B",
        asset_type="public_security",
        market_value=10000,
    )
    p2 = AssetPositionInput(
        ticker="BTC-USD",
        name="Bitcoin",
        asset_type="crypto",
        market_value=5000,
    )
    assert p1.ticker == "BRK.B"
    assert p2.ticker == "BTC-USD"


def test_unsupported_asset_type_rejected():
    with pytest.raises(ValidationError):
        AssetPositionInput(
            ticker="AAPL",
            name="Apple",
            asset_type="commodity",  # not in Literal
            market_value=1000,
        )


def test_impossibly_large_cost_basis_rejected():
    """Catches data-entry slip-ups: user typed an extra zero on cost
    basis. 50× ratio is the threshold (allows real distressed loss
    positions but rejects 100× typos)."""
    with pytest.raises(ValidationError, match="cost_basis"):
        AssetPositionInput(
            ticker="AAPL",
            name="Apple",
            asset_type="public_security",
            market_value=100.0,
            cost_basis=100_000.0,  # 1000× ratio
        )


def test_normal_loss_position_accepted():
    """Down 30% is a real and common state — must NOT trip the typo guard."""
    p = AssetPositionInput(
        ticker="AAPL",
        name="Apple",
        asset_type="public_security",
        market_value=7_000.0,
        cost_basis=10_000.0,
    )
    assert p.cost_basis == 10_000.0


# ── PortfolioInput full-shape validation ─────────────────────────────


def test_empty_portfolio_rejected():
    with pytest.raises(ValidationError):
        PortfolioInput(positions=[])


def test_all_disabled_or_zero_portfolio_rejected():
    with pytest.raises(ValidationError, match="no enabled positions"):
        PortfolioInput(
            positions=[
                AssetPositionInput(
                    ticker="AAPL",
                    name="Apple",
                    asset_type="public_security",
                    market_value=0,  # zero
                    enabled=True,
                ),
                AssetPositionInput(
                    ticker="MSFT",
                    name="Microsoft",
                    asset_type="public_security",
                    market_value=1000,
                    enabled=False,  # disabled
                ),
            ]
        )


def test_risk_preference_out_of_range_rejected():
    with pytest.raises(ValidationError):
        PortfolioInput(
            positions=[
                AssetPositionInput(
                    ticker="AAPL",
                    name="Apple",
                    asset_type="public_security",
                    market_value=1000,
                )
            ],
            risk_preference=7,  # >5
        )


def test_to_positions_returns_list_of_frozen_dataclasses():
    p = PortfolioInput(
        positions=[
            AssetPositionInput(
                ticker="AAPL",
                name="Apple",
                asset_type="public_security",
                market_value=10000,
            ),
            AssetPositionInput(
                ticker="MSFT",
                name="Microsoft",
                asset_type="public_security",
                market_value=5000,
            ),
        ],
        risk_preference=4,
    )
    positions = p.to_positions()
    assert len(positions) == 2
    assert all(isinstance(x, AssetPosition) for x in positions)
    assert {x.ticker for x in positions} == {"AAPL", "MSFT"}


# ── AgentResponse adapter ────────────────────────────────────────────


def test_agent_response_from_legacy_result():
    """The adapter must accept the legacy AgentResult dataclass from
    libs/ai_agents and produce a validated Pydantic AgentResponse."""
    from libs.ai_agents.portfolio_agents import AgentResult

    legacy = AgentResult(
        agent_name="Portfolio Analyzer Agent",
        response_markdown="**Assessment:** all good",
        risk_levers=[{"lever": "review_leverage", "headline": "Review margin leverage"}],
        tool_trace=["read_quant_score"],
    )
    resp = AgentResponse.from_agent_result(legacy)
    assert resp.agent_name == "Portfolio Analyzer Agent"
    assert "Assessment" in resp.response_markdown
    assert resp.risk_levers[0]["lever"] == "review_leverage"
    assert resp.tool_trace == ["read_quant_score"]


def test_agent_response_grounded_in_round_trips():
    resp = AgentResponse(
        agent_name="x",
        response_markdown="ok",
        grounded_in={"overall_score": 750, "sharpe_ratio": 1.2},
    )
    dumped = resp.model_dump()
    assert dumped["grounded_in"]["overall_score"] == 750


# ── option positions (PR1 — data model) ───────────────────────────────


def test_valid_option_round_trips_with_contract_fields():
    raw = AssetPositionInput(
        ticker="aapl",  # underlying; the contract id is the JSONB key, not this
        name="AAPL 2026-01-16 C150",
        asset_type="option",
        market_value=1_040.0,  # 2 contracts × $5.20 × 100
        cost_basis=1_040.0,
        option_type="call",
        underlying="aapl",
        strike=150.0,
        expiry="2026-01-16",
        contract_multiplier=100.0,
    )
    assert raw.underlying == "AAPL"  # normalized like a ticker
    pos = raw.to_position()
    assert pos.is_option is True
    assert pos.option_type == "call"
    assert pos.strike == 150.0
    assert pos.expiry == "2026-01-16"
    assert pos.contract_multiplier == 100.0


@pytest.mark.parametrize("missing", ["option_type", "underlying", "strike", "expiry"])
def test_option_missing_contract_field_rejected(missing):
    fields = {
        "option_type": "put",
        "underlying": "SPY",
        "strike": 400.0,
        "expiry": "2026-03-20",
    }
    fields.pop(missing)
    with pytest.raises(ValidationError, match="contract fields"):
        AssetPositionInput(
            ticker="SPY",
            name="opt",
            asset_type="option",
            market_value=500.0,
            **fields,
        )


def test_option_bad_expiry_rejected():
    with pytest.raises(ValidationError, match="ISO date"):
        AssetPositionInput(
            ticker="SPY",
            name="opt",
            asset_type="option",
            market_value=500.0,
            option_type="call",
            underlying="SPY",
            strike=400.0,
            expiry="03/20/2026",
        )


def test_option_negative_strike_rejected():
    with pytest.raises(ValidationError):
        AssetPositionInput(
            ticker="SPY",
            name="opt",
            asset_type="option",
            market_value=500.0,
            option_type="call",
            underlying="SPY",
            strike=-1.0,
            expiry="2026-03-20",
        )


def test_non_option_ignores_contract_fields():
    # A plain equity never needs option_* and they default to None.
    pos = AssetPositionInput(
        ticker="VTI",
        name="Vanguard Total Market",
        asset_type="public_security",
        market_value=5_000.0,
    ).to_position()
    assert pos.is_option is False
    assert pos.option_type is None and pos.strike is None
