"""One place to record an AI call's full telemetry.

Principle 6 of the upgrade brief: every AI call logs tokens_in/out, cost_usd,
latency_ms, model, cache_hit, and input_hash for the owner dashboard. The
scalar cost fields go in the dedicated ``usage_events`` columns (so credits
deplete + the existing dashboard aggregates them); the richer signals
(latency_ms / cache_hit / input_hash) ride along in the ``metadata`` jsonb —
no migration needed. Never raises: telemetry must not break a user action.
"""

from __future__ import annotations

import hashlib
import logging

_log = logging.getLogger(__name__)


def input_hash(text: str) -> str:
    """Stable short hash of an LLM input — lets the dashboard spot
    cache-worthy repeats without storing the prompt itself."""
    return hashlib.sha256(text.encode("utf-8", "ignore")).hexdigest()[:16]


def record_ai_call(
    user_id: str,
    kind: str,
    *,
    model: str,
    tokens_in: int,
    tokens_out: int,
    latency_ms: float,
    provider: str = "anthropic",
    cache_hit: bool = False,
    input_hash: str | None = None,
    eval_metadata: dict | None = None,
) -> None:
    """Record one AI call's cost + latency + optional quality-eval signals.

    ``eval_metadata`` (from ``ai_eval.eval_signals``) carries privacy-safe scalar
    flags — intent / tool_turn_count / answer_grounded / invented_number_detected
    / direct_advice_detected / fallback_used — for monitoring the assistant over
    time. It rides the existing ``usage_events.metadata`` jsonb (no migration).
    """
    try:
        from libs.billing.costs import estimate_cost_usd
        from libs.billing.usage import record_event

        cost = estimate_cost_usd(provider, model, tokens_in=tokens_in, tokens_out=tokens_out)
        metadata = {
            "latency_ms": round(float(latency_ms), 1),
            "cache_hit": bool(cache_hit),
            "input_hash": input_hash,
        }
        if eval_metadata:
            metadata.update(eval_metadata)
        record_event(
            user_id,
            kind,
            provider=provider,
            model=model,
            tokens_in=int(tokens_in),
            tokens_out=int(tokens_out),
            cost_usd=cost,
            metadata=metadata,
        )
    except Exception:  # noqa: BLE001 - telemetry never breaks the action
        _log.warning("ai_telemetry.record_failed kind=%s", kind)
