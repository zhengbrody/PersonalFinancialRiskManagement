"""``POST /api/v1/feedback`` — beta-tester feedback.

Routed to Sentry (already wired) as an info-level message tagged
``user_feedback`` + always logged, so the owner sees tester friction in one
place without standing up a new table during the beta. Authed so feedback is
attributable. Fail-soft: a Sentry hiccup never fails the user's submit.
"""

from __future__ import annotations

import logging
import time

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from ...core.deps_auth import AuthedUser, require_user
from ...core.responses import ok
from ...schemas.envelope import Envelope

router = APIRouter(prefix="/api/v1/feedback", tags=["feedback"])

_log = logging.getLogger(__name__)


class FeedbackIn(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    # The page the user was on when they hit "feedback" (e.g. "/scenarios").
    context: str = Field(default="", max_length=200)


@router.post("", summary="Submit beta feedback", response_model=Envelope[dict])
def submit_feedback(
    body: FeedbackIn,
    request: Request,
    user: AuthedUser = Depends(require_user),
):
    started = time.perf_counter()
    text = body.message.strip()
    page = body.context.strip() or "unknown"
    _log.info("feedback.received user=%s page=%s len=%d", user.id, page, len(text))
    try:
        import sentry_sdk

        # Embed attribution in the message so no scope manipulation is needed
        # (robust across sentry-sdk versions); only sends when Sentry is inited
        # (production), a no-op otherwise.
        # Privacy: attribute by ACCOUNT ID only — the user's email must not
        # be stored in the error tracker (Privacy Policy, review-caught).
        sentry_sdk.capture_message(
            f"[Feedback] page={page} user={user.id}: {text}",
            level="info",
        )
    except Exception:  # noqa: BLE001 - feedback submit must never fail
        _log.warning("feedback.sentry_failed")

    return ok({"received": True}, request=request, started_at=started)
