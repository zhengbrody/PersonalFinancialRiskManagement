"""Portfolio Copilot agent layer — stateless, ReAct-pattern dispatch.

Per ADR 02: no LangChain, no CrewAI, no thread-blocking abstraction
layers. Agents are pure-Python classes that:

1. Accept a fully-computed ``PortfolioScore`` + ``AssetPosition`` list
   as input (the math has already run; the agent just reads facts).
2. Run zero or more deterministic Python tools (fee scan, tax-loss
   scan, draft trade generator).
3. Optionally hand the *already-computed* facts to an LLM purely for
   prose formatting. The LLM may never invent a number.
"""

from .orchestrator import (
    PortfolioAgentRouter,
    PortfolioAnalyzerAgent,
    StrategyOptimizerAgent,
    build_agent_context,
    route_message,
    scan_hidden_fees,
    scan_tax_loss_harvesting,
)

__all__ = [
    "PortfolioAgentRouter",
    "PortfolioAnalyzerAgent",
    "StrategyOptimizerAgent",
    "build_agent_context",
    "route_message",
    "scan_hidden_fees",
    "scan_tax_loss_harvesting",
]
