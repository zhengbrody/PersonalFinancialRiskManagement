"""Request / response schemas for the Copilot chat endpoint.

``ChatResponse`` mirrors ``domain.models.AgentResponse`` field-for-field
so the route can serialise the orchestrator's typed result straight onto
the wire without a hand-rolled adapter.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ChatRequest(BaseModel):
    """One chat turn from the user. The orchestrator routes the message
    to the right agent (analyzer / optimizer); we don't parse intent
    here."""

    model_config = ConfigDict(str_strip_whitespace=True)

    message: str = Field(..., min_length=1, max_length=4000)


class ChatResponse(BaseModel):
    """JSON view of ``domain.models.AgentResponse``.

    ``grounded_in`` carries the engine's exact metrics so a consumer can
    verify the markdown reply matches the deterministic numbers."""

    agent_name: str
    response_markdown: str
    # Non-transactional risk-management levers — never buy/sell instructions.
    risk_levers: list[dict] = Field(default_factory=list)
    tool_trace: list[str] = Field(default_factory=list)
    grounded_in: dict[str, Any] = Field(default_factory=dict)
    # True = LLM-synthesized markdown; False = deterministic fallback template.
    ai_generated: bool = False
