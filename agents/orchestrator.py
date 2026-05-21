"""Agent orchestration facade — public dispatcher for chat → agent.

The agent implementations live in :mod:`libs.ai_agents.portfolio_agents`
(historical location, full test coverage there). This module is the
canonical public entrypoint and adds:

* A typed ``route_message()`` helper that returns the ``AgentResponse``
  Pydantic model (vs. the internal ``AgentResult`` dataclass), so the
  UI / JSON consumers get a stable, validated schema.
* Re-exports of the deterministic tools so callers don't have to know
  about the ``libs.ai_agents`` private path.
"""

from __future__ import annotations

from typing import Callable, Iterable

from domain.models import AgentResponse, AssetPosition, PortfolioScore

# Re-export the resident agents + deterministic tools. Implementations
# are tested in tests/unit/test_portfolio_agents.py; this file is the
# public seam.
from libs.ai_agents.portfolio_agents import (  # noqa: F401 (re-export)
    PortfolioAgentRouter,
    PortfolioAnalyzerAgent,
    StrategyOptimizerAgent,
    build_agent_context,
    generate_draft_trades,
    scan_hidden_fees,
    scan_tax_loss_harvesting,
)

LLMCallable = Callable[..., str]


def route_message(
    user_message: str,
    score: PortfolioScore,
    positions: Iterable[AssetPosition],
    *,
    llm_callable: LLMCallable | None = None,
) -> AgentResponse:
    """Dispatch a chat message to the right agent and return a typed response.

    Wraps ``PortfolioAgentRouter().route(...)`` with two extras:

    1. The returned ``AgentResult`` (dataclass) is adapted to the
       ``AgentResponse`` Pydantic model so the UI gets a stable schema.
    2. The math-layer's exact metrics are attached under ``grounded_in``
       so a UI consumer (or audit log) can verify that every figure in
       the markdown reply actually matches the deterministic engine.

    Defensive: an empty user_message short-circuits to a friendly prompt
    rather than calling the router with garbage. A router exception is
    caught and surfaced as a typed error response rather than 500-ing
    the page.
    """
    message = (user_message or "").strip()
    if not message:
        return AgentResponse(
            agent_name="Portfolio Copilot",
            response_markdown=(
                "Ask a question to get a portfolio analysis or "
                "optimization plan. Examples: 'diagnose my risk', "
                "'find tax-loss harvesting candidates', 'draft trades "
                "to reduce drawdown'."
            ),
        )

    try:
        router = PortfolioAgentRouter()
        result = router.route(
            message,
            score,
            positions,
            llm_callable=llm_callable,
        )
    except Exception as exc:  # noqa: BLE001 (UI seam — must not 500)
        return AgentResponse(
            agent_name="Portfolio Copilot",
            response_markdown=(
                f"**Could not produce a response.** Internal error: {exc}\n\n"
                "Quant metrics on the page above are still valid; the "
                "failure is in the agent layer, not the score engine."
            ),
        )

    response = AgentResponse.from_agent_result(result)
    # Attach the immutable ground-truth so consumers can verify the
    # markdown reply matches the engine's exact numbers.
    response.grounded_in = {
        "overall_score": score.overall_score,
        "sharpe_ratio": score.metrics.sharpe_ratio,
        "annual_volatility": score.metrics.annual_volatility,
        "max_drawdown": score.metrics.max_drawdown,
        "var_95_daily": score.metrics.var_95_daily,
        "beta_to_benchmark": score.metrics.beta_to_benchmark,
        "total_value": score.metrics.total_value,
    }
    return response
