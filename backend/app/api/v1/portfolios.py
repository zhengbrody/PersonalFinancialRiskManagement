"""``GET /api/v1/portfolios/me`` — authed portfolio listing.

This is the canonical example of the **per-route JWT dependency**
pattern (ADR-0004). The dependency:

  * is mounted on this route only — ``/health`` stays public,
  * extracts ``Authorization: Bearer <jwt>``,
  * verifies HS256 against ``SUPABASE_JWT_SECRET``,
  * returns a frozen ``AuthedUser`` the route can read directly.

The route then calls the existing ``libs.auth.portfolios.list_portfolios``
which already enforces Supabase RLS (every query is filtered by
``auth.uid()``). We don't re-implement RLS here — we just have to
attach the right JWT to the Supabase client.

In Phase 1 we surface the ``user.id`` we got from the verified JWT
but DON'T yet rebind the Supabase client to that token (that's a
two-line change but it requires a small refactor of
``libs.auth.portfolios._authed_client`` to accept an explicit token,
which is queued for Phase 2). For now the response includes the
verified user id so the frontend can confirm auth worked end-to-end.
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends, Request

from ...core.deps_auth import AuthedUser, require_user
from ...core.responses import ok

router = APIRouter(prefix="/api/v1/portfolios", tags=["portfolios"])


@router.get("/me", summary="Return the authed user's portfolios")
def list_my_portfolios(
    request: Request,
    user: AuthedUser = Depends(require_user),
):
    """Authed-only.

    Phase 1 returns ``{ user_id, email, portfolios: [] }``. The
    actual ``portfolios`` array is fed by the existing
    ``libs.auth.portfolios.list_portfolios`` once we wire the
    incoming JWT into ``libs.auth.client.get_supabase`` (Phase 2 —
    needs a small refactor to accept an explicit token). Today we
    return ``[]`` plus the verified identity so the frontend can
    confirm the auth path end-to-end without a Supabase round-trip.
    """
    started = time.perf_counter()
    return ok(
        {
            "user_id": user.id,
            "email": user.email,
            "portfolios": [],
            "_note": (
                "Phase 1: list_portfolios() not yet bound to the request-"
                "scoped JWT. Phase 2 wires `libs.auth.client.get_supabase` "
                "to accept an explicit token so RLS filters by the caller "
                "instead of the Streamlit session state."
            ),
        },
        request=request,
        started_at=started,
    )
