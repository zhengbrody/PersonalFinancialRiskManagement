"""Quant engine facade — re-exports the pure-math scoring API.

The implementation lives in :mod:`libs.mindmarket_core.portfolio_scoring`
(historical location, kept stable so the existing test suite + page 11
keep working). This module is the canonical public entrypoint per the
ADR-03 layered architecture: ``from engine.quant import score_portfolio``.

The only **net-new** function here is ``score_portfolio_from_input()``,
which threads a Pydantic-validated ``PortfolioInput`` through the math
layer so callers that accept raw user JSON get input validation for
free without re-implementing every guard.
"""

from __future__ import annotations

import pandas as pd

from domain.models import PortfolioInput, PortfolioScore

# Re-export pure-math primitives. The math layer is already audited +
# tested; we keep the implementation in libs/mindmarket_core/ and expose
# it here so the public API matches the ADR layout.
from libs.mindmarket_core.portfolio_scoring import (  # noqa: F401 (re-export)
    RISK_TARGETS,
    active_positions,
    compute_portfolio_metrics,
    create_draft_positions,
    demo_asset_positions,
    normalize_target_weights,
    positions_to_frame,
    score_portfolio,
    score_status,
)


def score_portfolio_from_input(
    portfolio_input: PortfolioInput,
    asset_returns: pd.DataFrame,
    *,
    benchmark_returns: pd.Series | None = None,
) -> PortfolioScore:
    """Validate raw input via Pydantic, then run the deterministic math.

    Use this entrypoint when the data crossing your boundary hasn't
    been audited yet (e.g. REST endpoint payload, broker import row,
    untrusted YAML config). For trusted in-process callers that already
    hold ``AssetPosition`` instances, ``score_portfolio()`` is fine.

    Args:
        portfolio_input:  Pydantic model. Validation has already run by
            the time you call this — anything not in spec raised at
            construction time.
        asset_returns:    Daily returns DataFrame (date × ticker).
        benchmark_returns: Optional benchmark series for beta calc.

    Returns:
        Frozen ``PortfolioScore`` dataclass: same shape downstream code
        already consumes; this function adds a validation step in
        front, not a new return type.
    """
    return score_portfolio(
        portfolio_input.to_positions(),
        asset_returns,
        benchmark_returns=benchmark_returns,
        risk_preference=portfolio_input.risk_preference,
        risk_free_rate=portfolio_input.risk_free_rate,
    )
