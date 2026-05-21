"""Portfolio Copilot domain layer — type-safe data contracts.

Public surface for callers outside the math/agents internals. Imports
from this package are the canonical way to construct + validate
portfolio state from raw user input.
"""

from .models import (
    AgentResponse,
    AssetPosition,
    AssetPositionInput,
    DimensionScore,
    PortfolioInput,
    PortfolioMetrics,
    PortfolioScore,
)

__all__ = [
    "AgentResponse",
    "AssetPosition",
    "AssetPositionInput",
    "DimensionScore",
    "PortfolioInput",
    "PortfolioMetrics",
    "PortfolioScore",
]
