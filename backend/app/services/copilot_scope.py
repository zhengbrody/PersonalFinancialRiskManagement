"""Optimistic portfolio binding for a foreground Copilot request.

Only a digest reaches the cache key; raw holdings are never logged. This is
not a durable snapshot or job authorization mechanism.
"""

import hashlib
import json
from dataclasses import asdict

from ..core.responses import APIError


def resolve_scope(token: str, expected: str | None) -> str:
    from libs.auth.active_portfolio import get_active_portfolio_context

    context = get_active_portfolio_context(access_token=token)
    if context.portfolio_id != expected:
        raise APIError(
            status=409,
            code="portfolio_changed",
            message="The active portfolio changed. Please ask again for the selected portfolio.",
        )
    return context_digest(asdict(context))


def context_digest(context: dict) -> str:
    return hashlib.sha256(json.dumps(context, sort_keys=True, allow_nan=False).encode()).hexdigest()


def verify_scope(token: str, expected: str | None, initial: str) -> None:
    if resolve_scope(token, expected) != initial:
        raise APIError(
            status=409,
            code="portfolio_changed",
            message="Portfolio inputs changed during this answer. Please ask again with the updated holdings.",
        )
