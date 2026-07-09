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
import threading
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
    try:
        # bytes compare — a non-ASCII header must be a clean 401, not a 500
        matched = hmac.compare_digest(
            x_digest_token.encode("utf-8", "surrogatepass"), expected.encode()
        )
    except Exception:  # noqa: BLE001 - fail closed
        matched = False
    if not matched:
        raise HTTPException(status_code=401, detail="bad digest token")


@router.post("/run")
def run_digest(request: Request, _: None = Depends(require_cron_token)):
    started = time.perf_counter()
    # Terminal states report synchronously; a real batch runs in a daemon
    # thread — Cloudflare's proxy times out ~100s and a full batch can take
    # longer. Counts land in the logs + /admin live metrics (resend provider).
    pre = digest_service.preflight()
    if pre is not None:
        return ok(pre, request=request, started_at=started)
    threading.Thread(target=digest_service.run_and_log, daemon=True).start()
    return ok({"status": "started"}, request=request, started_at=started)


_PAGE_STYLE = (
    "font-family:-apple-system,Helvetica,Arial,sans-serif;max-width:28rem;"
    "margin:15vh auto;padding:0 1rem;color:#0B0E11;"
)


@router.get("/unsubscribe", response_class=HTMLResponse)
def unsubscribe_confirm(token: str = ""):
    """Confirmation page ONLY — no side effect on GET. Corporate mail
    link-scanners prefetch every href; a side-effecting GET would silently
    opt users out. The button (and RFC 8058 one-click providers) POST."""
    user_id = digest_service.verify_unsubscribe_token(token or "")
    if user_id is None:
        return HTMLResponse(
            f'<div style="{_PAGE_STYLE}"><h3>Invalid link</h3><p>This unsubscribe link is broken or has expired.'
            " You can also turn off the weekly digest from the Settings page in MindMarket.</p></div>",
            status_code=400,
        )
    from urllib.parse import quote

    action = f"/api/v1/digest/unsubscribe?token={quote(token)}"
    return HTMLResponse(
        f'<div style="{_PAGE_STYLE}"><h3>Unsubscribe from the weekly risk digest?</h3>'
        "<p>Once you confirm, you'll no longer receive MindMarket's weekly digest — you can re-enable it anytime from the Settings page.</p>"
        f'<form method="post" action="{action}">'
        '<button type="submit" style="padding:10px 18px;border-radius:8px;'
        "border:none;background:#0B0E11;color:#fff;font-size:15px;cursor:pointer;"
        '">Confirm unsubscribe</button></form></div>'
    )


@router.post("/unsubscribe", response_class=HTMLResponse)
def unsubscribe_apply(token: str = ""):
    user_id = digest_service.verify_unsubscribe_token(token or "")
    if user_id is None:
        return HTMLResponse(
            f'<div style="{_PAGE_STYLE}"><h3>Invalid link</h3><p>This unsubscribe link is broken or has expired.</p></div>',
            status_code=400,
        )
    try:
        digest_service.set_optout(user_id, enabled=False)
    except Exception:  # noqa: BLE001 - show an honest failure page, never a 500 trace
        _log.warning("digest.unsubscribe_failed", exc_info=True)
        return HTMLResponse(
            f'<div style="{_PAGE_STYLE}"><h3>Unable to unsubscribe right now</h3><p>Please try again later,'
            " or turn off the weekly digest from the Settings page.</p></div>",
            status_code=503,
        )
    return HTMLResponse(
        f'<div style="{_PAGE_STYLE}"><h3>Unsubscribed ✓</h3><p>You will no longer receive the MindMarket '
        "weekly risk digest. You can re-enable it anytime from the Settings page.</p></div>"
    )


@router.get("/pref")
def get_pref(request: Request, user: AuthedUser = Depends(require_user)):
    started = time.perf_counter()
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
    except Exception as exc:  # noqa: BLE001
        # 0007 unapplied → 503 so the settings card HIDES (its contract)
        # instead of showing a toggle whose save can only fail.
        if digest_service._table_missing(exc):
            raise HTTPException(status_code=503, detail="digest preferences unavailable") from None
        # transient read blip → default-on is the honest fallback
    return ok({"enabled": enabled}, request=request, started_at=started)


@router.post("/pref")
def set_pref(body: DigestPrefIn, request: Request, user: AuthedUser = Depends(require_user)):
    started = time.perf_counter()
    try:
        from libs.auth.client import get_supabase

        get_supabase(access_token=user.access_token).table("digest_prefs").upsert(
            {"user_id": user.id, "enabled": body.enabled}
        ).execute()
    except Exception:  # noqa: BLE001
        _log.warning("digest.set_pref_failed", exc_info=True)
        raise HTTPException(status_code=503, detail="digest preferences unavailable") from None
    return ok({"enabled": body.enabled}, request=request, started_at=started)
