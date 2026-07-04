"""Weekly digest endpoints.

- POST /digest/run — the cron trigger. Auth = shared secret header
  ``X-Digest-Token`` (no user JWT: the caller is a GitHub Actions cron).
  503 when the token isn't configured server-side, 401 on mismatch.
- GET /digest/unsubscribe?token= — the email's one-click opt-out. Signed
  HMAC token, works logged-out, returns a tiny human HTML page.
- GET/POST /digest/pref — the authed /settings toggle (RLS-scoped upsert).
"""

from __future__ import annotations

import hmac
import logging
import time

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from ...core.config import get_settings
from ...core.deps_auth import AuthedUser, require_user
from ...core.responses import ok
from ...services import digest as digest_service

router = APIRouter(prefix="/api/v1/digest", tags=["digest"])

_log = logging.getLogger(__name__)


class DigestPrefIn(BaseModel):
    enabled: bool


def require_cron_token(x_digest_token: str = Header(default="")) -> None:
    expected = get_settings().digest_cron_token
    if not expected:
        raise HTTPException(status_code=503, detail="digest cron token not configured")
    if not hmac.compare_digest(x_digest_token, expected):
        raise HTTPException(status_code=401, detail="bad digest token")


@router.post("/run")
def run_digest(request: Request, _: None = Depends(require_cron_token)):
    started = time.time()
    summary = digest_service.run_weekly()
    _log.info("digest.run %s", summary)
    return ok(summary, request=request, started_at=started)


@router.get("/unsubscribe", response_class=HTMLResponse)
def unsubscribe(token: str = ""):
    user_id = digest_service.verify_unsubscribe_token(token or "")
    if user_id is None:
        return HTMLResponse(
            "<h3>链接无效</h3><p>退订链接已损坏或过期。你也可以在 MindMarket 的"
            " Settings 页关闭每周简报。</p>",
            status_code=400,
        )
    try:
        digest_service.set_optout(user_id, enabled=False)
    except Exception:  # noqa: BLE001 - show an honest failure page, never a 500 trace
        _log.warning("digest.unsubscribe_failed", exc_info=True)
        return HTMLResponse(
            "<h3>暂时无法退订</h3><p>请稍后重试,或在 Settings 页关闭每周简报。</p>",
            status_code=503,
        )
    return HTMLResponse(
        "<h3>已退订 ✓</h3><p>你不会再收到 MindMarket 每周风险简报。"
        "随时可以在 Settings 页重新开启。</p>"
    )


@router.get("/pref")
def get_pref(request: Request, user: AuthedUser = Depends(require_user)):
    started = time.time()
    enabled = True
    try:
        from libs.auth.client import get_supabase

        rows = (
            get_supabase(access_token=user.access_token)
            .table("digest_prefs")
            .select("enabled")
            .eq("user_id", user.id)
            .limit(1)
            .execute()
            .data
            or []
        )
        if rows:
            enabled = bool(rows[0].get("enabled", True))
    except Exception:  # noqa: BLE001 - table absent (0007 unapplied) → default on
        pass
    return ok({"enabled": enabled}, request=request, started_at=started)


@router.post("/pref")
def set_pref(body: DigestPrefIn, request: Request, user: AuthedUser = Depends(require_user)):
    started = time.time()
    try:
        from libs.auth.client import get_supabase

        get_supabase(access_token=user.access_token).table("digest_prefs").upsert(
            {"user_id": user.id, "enabled": body.enabled}
        ).execute()
    except Exception:  # noqa: BLE001
        _log.warning("digest.set_pref_failed", exc_info=True)
        raise HTTPException(status_code=503, detail="digest preferences unavailable") from None
    return ok({"enabled": body.enabled}, request=request, started_at=started)
