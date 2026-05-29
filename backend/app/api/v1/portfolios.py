"""``GET /api/v1/portfolios/me`` — authed portfolio listing.

This is the canonical example of the per-route JWT dependency pattern
(ADR-0004). The dependency:

  * is mounted on this route only — ``/health`` stays public,
  * extracts ``Authorization: Bearer <jwt>``,
  * verifies HS256 against ``SUPABASE_JWT_SECRET``,
  * returns a frozen ``AuthedUser`` whose ``access_token`` is the raw
    JWT we just verified.

We then call the existing ``libs.auth.portfolios.list_portfolios``
with the token attached, which forwards it to Supabase so every row
returned is filtered by the database's RLS policies — never trust
the network layer to do that filtering.

Failure modes:
  * Supabase unreachable → the underlying call raises; we map it to
    ``server_error`` so the frontend can render a retry banner.
  * Token verified but user has no rows → returns ``portfolios: []``.
    Not an error — the new-user empty state is the frontend's job.
"""

from __future__ import annotations

import logging
import time

from fastapi import APIRouter, Depends, Request

from ...core.deps_auth import AuthedUser, require_user
from ...core.responses import ok, server_error
from ...schemas.portfolios import PortfoliosMeResponse

router = APIRouter(prefix="/api/v1/portfolios", tags=["portfolios"])

_logger = logging.getLogger(__name__)


@router.get("/me", summary="Return the authed user's portfolios")
def list_my_portfolios(
    request: Request,
    user: AuthedUser = Depends(require_user),
):
    """Authed-only. Returns the JWT holder's RLS-filtered portfolios."""
    started = time.perf_counter()

    try:
        from libs.auth.portfolios import list_portfolios
    except Exception as exc:  # pragma: no cover - import guard
        _logger.error("portfolios.import_failed err=%s", exc)
        raise server_error("Portfolios module unavailable.") from exc

    try:
        rows = list_portfolios(access_token=user.access_token)
    except Exception as exc:
        # Supabase down or auth misconfig — surface a clean 500 instead
        # of leaking the upstream stack trace.
        _logger.warning("portfolios.list_failed user=%s err=%s", user.id, exc)
        raise server_error("Could not load portfolios.", reason=type(exc).__name__) from exc

    payload = PortfoliosMeResponse(
        user_id=user.id,
        email=user.email,
        portfolios=rows,  # Pydantic coerces each dict via PortfolioOut
    )
    return ok(payload.model_dump(), request=request, started_at=started)
