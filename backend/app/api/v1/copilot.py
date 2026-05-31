"""``POST /api/v1/copilot/chat`` — AI Portfolio Copilot chat.

Authed endpoint. Resolves the caller's active portfolio, computes its
deterministic score, gates the call against the user's monthly chat
quota, then dispatches the message to the agent orchestrator.

The orchestrator NEVER raises (it catches internally and returns a typed
error response) and degrades to deterministic templates when no LLM is
configured — so this route stays a thin, predictable adapter. The heavy
data wiring lives in ``services/copilot_context.py``; the LLM seam lives
in ``services/llm_client.py``.
"""

from __future__ import annotations

import logging
import time

from fastapi import APIRouter, Depends, Request

from ...core.deps_auth import AuthedUser, require_user
from ...core.responses import ok, too_many_requests
from ...schemas.copilot import ChatRequest, ChatResponse
from ...services import copilot_context
from ...services.llm_client import get_llm_callable

router = APIRouter(prefix="/api/v1/copilot", tags=["copilot"])

_log = logging.getLogger(__name__)


@router.post(
    "/chat",
    summary="Chat with the AI Portfolio Copilot about the active portfolio",
    response_model=None,  # we wrap the response in the envelope ourselves
)
def copilot_chat_endpoint(
    body: ChatRequest,
    request: Request,
    user: AuthedUser = Depends(require_user),
):
    """Answer a chat turn about the caller's active portfolio.

    Flow:
      1. Resolve positions + score (422 codes on empty/unpriceable data).
      2. Gate on the user's monthly chat quota (429 when exhausted;
         fail-OPEN on a Supabase blip — availability over strict metering).
      3. Dispatch to the orchestrator with the LLM callable (or ``None``
         → deterministic templates).
    """
    started = time.perf_counter()

    # Active portfolio → typed positions + deterministic score. Raises
    # the shared 422/500 envelope codes; let them propagate.
    positions, score = copilot_context.load_positions_and_score(user)

    # ── Quota gate ────────────────────────────────────────────────────
    # A hard QuotaExceeded → 429 (caller must upgrade/wait). ANY OTHER
    # failure (Supabase outage, schema drift) must NOT lock the user out:
    # we'd rather eat the rare unmetered call than hand a paying customer
    # a 500. Same fail-soft posture as risk.py:_resolve_cash_and_margin.
    from libs.billing.usage import QuotaExceeded, check_and_consume

    try:
        check_and_consume(user.id, "chat")
    except QuotaExceeded as exc:
        raise too_many_requests(str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - fail-open on metering blip
        _log.warning("copilot.quota_check_failed reason=%s", type(exc).__name__)

    # ── Agent dispatch ────────────────────────────────────────────────
    # route_message never raises (returns a typed error response on
    # failure) and degrades to templates when llm is None.
    from agents.orchestrator import route_message

    llm = get_llm_callable()
    resp = route_message(body.message, score, positions, llm_callable=llm)

    payload = ChatResponse(**resp.model_dump()).model_dump()
    return ok(payload, request=request, started_at=started)
