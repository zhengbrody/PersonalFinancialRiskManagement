"""Portfolio Copilot quantitative engine — pure NumPy/Pandas math.

Per ADR 01: nothing in this package may call an LLM, hit a network, or
touch session state. Outputs from here are immutable ground truth that
the agent layer must not contradict.
"""

from .quant import (
    RISK_TARGETS,
    active_positions,
    compute_portfolio_metrics,
    create_draft_positions,
    demo_asset_positions,
    normalize_target_weights,
    positions_to_frame,
    score_portfolio,
    score_portfolio_from_input,
    score_status,
)

__all__ = [
    "RISK_TARGETS",
    "active_positions",
    "compute_portfolio_metrics",
    "create_draft_positions",
    "demo_asset_positions",
    "normalize_target_weights",
    "positions_to_frame",
    "score_portfolio",
    "score_portfolio_from_input",
    "score_status",
]
