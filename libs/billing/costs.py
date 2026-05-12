"""LLM token and cost estimation helpers.

These estimates are intentionally conservative enough for owner cost
monitoring, but they are not a billing-grade provider invoice. Provider
dashboards remain the source of truth for final charges.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from typing import Optional


@dataclass(frozen=True)
class ModelPricing:
    input_per_million: float
    output_per_million: float


# Defaults can be overridden later from env/secrets if pricing changes.
# Values are USD per 1M tokens.
MODEL_PRICING: dict[str, ModelPricing] = {
    "anthropic": ModelPricing(input_per_million=3.00, output_per_million=15.00),
    "claude": ModelPricing(input_per_million=3.00, output_per_million=15.00),
    "deepseek": ModelPricing(input_per_million=0.55, output_per_million=2.19),
    "ollama": ModelPricing(input_per_million=0.00, output_per_million=0.00),
}


def estimate_tokens(text: Optional[str]) -> int:
    """Estimate tokens from text using a simple 4 chars/token heuristic."""
    if not text:
        return 0
    return max(1, ceil(len(text) / 4))


def normalize_provider(provider: Optional[str], model: Optional[str] = None) -> str:
    value = f"{provider or ''} {model or ''}".lower()
    if "deepseek" in value:
        return "deepseek"
    if "anthropic" in value or "claude" in value:
        return "anthropic"
    if "ollama" in value or "local" in value:
        return "ollama"
    return (provider or "unknown").strip().lower() or "unknown"


def estimate_cost_usd(
    provider: Optional[str],
    model: Optional[str],
    *,
    tokens_in: int,
    tokens_out: int,
) -> float:
    """Estimate USD cost from provider/model and token counts."""
    normalized = normalize_provider(provider, model)
    pricing = MODEL_PRICING.get(normalized)
    if pricing is None:
        return 0.0
    cost = (
        max(0, tokens_in) * pricing.input_per_million
        + max(0, tokens_out) * pricing.output_per_million
    ) / 1_000_000
    return round(cost, 6)


def estimate_llm_event(
    *,
    prompt: str,
    system: str = "",
    provider: Optional[str],
    model: Optional[str],
    max_tokens: int,
    response_text: str = "",
) -> dict[str, float | int | bool]:
    """Return token/cost metadata for a single LLM event.

    If ``response_text`` is unavailable before the provider call, the output
    estimate uses ``max_tokens`` and marks the event as estimated.
    """
    tokens_in = estimate_tokens(prompt) + estimate_tokens(system)
    if response_text:
        tokens_out = estimate_tokens(response_text)
        estimated = False
    else:
        tokens_out = max(0, int(max_tokens or 0))
        estimated = True
    return {
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "cost_usd": estimate_cost_usd(
            provider,
            model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
        ),
        "estimated": estimated,
    }
