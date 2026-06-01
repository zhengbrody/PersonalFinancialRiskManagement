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

import json
import logging
import time

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from ...core.deps_auth import AuthedUser, require_user
from ...core.responses import APIError, ok, too_many_requests
from ...schemas.copilot import ChatRequest, ChatResponse
from ...services import copilot_context
from ...services.llm_client import get_answer_streamer, get_llm_callable

router = APIRouter(prefix="/api/v1/copilot", tags=["copilot"])

_log = logging.getLogger(__name__)


def _grounded(score) -> dict:
    """The exact engine metrics every answer must be grounded in (mirrors
    orchestrator.route_message's grounded_in)."""
    m = score.metrics
    return {
        "overall_score": score.overall_score,
        "sharpe_ratio": m.sharpe_ratio,
        "annual_volatility": m.annual_volatility,
        "max_drawdown": m.max_drawdown,
        "var_95_daily": m.var_95_daily,
        "beta_to_benchmark": m.beta_to_benchmark,
        "total_value": m.total_value,
    }


def _sse(event: str, data: dict) -> str:
    """Format one Server-Sent Event frame."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


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

    # with_tools=True → the LLM seam runs an Anthropic tool-use loop so
    # Claude can fetch live free data (sentiment/news/macro/fundamentals/
    # options IV) and ground its answer. Degrades to None (templates) with
    # no key, exactly as before.
    llm = get_llm_callable(with_tools=True)
    resp = route_message(body.message, score, positions, llm_callable=llm)

    payload = ChatResponse(**resp.model_dump()).model_dump()
    return ok(payload, request=request, started_at=started)


@router.post(
    "/chat/stream",
    summary="Streaming (SSE) Copilot chat — answer tokens arrive as written",
    response_model=None,
)
def copilot_chat_stream_endpoint(
    body: ChatRequest,
    request: Request,
    user: AuthedUser = Depends(require_user),
):
    """Same as /chat but **streams** the answer over Server-Sent Events so
    the UI renders text as it's generated instead of waiting for the whole
    turn. Events: ``status`` (phase), ``delta`` ({text}), ``done``
    ({agent_name, grounded_in, draft_trades}), ``error`` ({code, message}).

    Auth is enforced up-front (a 401 here is a normal HTTP error, not an SSE
    frame). Everything after the stream starts is reported via SSE events —
    a 422 (no portfolio) / 429 (quota) becomes an ``error`` event so the
    client maps it to the same friendly CTA as the non-streaming route.
    """

    def gen():
        yield _sse("status", {"phase": "analyzing"})

        # Resolve positions + score (422 codes → error event, not a 500).
        try:
            positions, score = copilot_context.load_positions_and_score(user)
        except APIError as exc:
            yield _sse("error", {"code": exc.code, "message": exc.message})
            return
        except Exception as exc:  # noqa: BLE001
            _log.warning("copilot.stream.context_failed reason=%s", type(exc).__name__)
            yield _sse("error", {"code": "server_error", "message": "Could not load portfolio."})
            return

        # Quota gate (429 → error event; fail-open on a metering blip).
        from libs.billing.usage import QuotaExceeded, check_and_consume

        try:
            check_and_consume(user.id, "chat")
        except QuotaExceeded as exc:
            yield _sse("error", {"code": "quota_exceeded", "message": str(exc)})
            return
        except Exception as exc:  # noqa: BLE001 - fail-open
            _log.warning("copilot.stream.quota_failed reason=%s", type(exc).__name__)

        grounded = _grounded(score)
        from agents.orchestrator import generate_draft_trades
        from libs.ai_agents.portfolio_agents import build_agent_context, build_formatter_messages

        try:
            draft_trades = generate_draft_trades(score, list(positions))
        except Exception:  # noqa: BLE001
            draft_trades = []

        streamer = get_answer_streamer()

        # No LLM key → one-shot deterministic template (still grounded).
        if streamer is None:
            from agents.orchestrator import route_message

            resp = route_message(body.message, score, positions, llm_callable=None)
            yield _sse("delta", {"text": resp.response_markdown})
            yield _sse(
                "done",
                {
                    "agent_name": resp.agent_name,
                    "grounded_in": grounded,
                    "draft_trades": draft_trades,
                },
            )
            return

        context = build_agent_context(score, list(positions))
        tool_results = {
            "overall_score": score.overall_score,
            "annual_return": score.metrics.annual_return,
            "annual_volatility": score.metrics.annual_volatility,
            "sharpe_ratio": score.metrics.sharpe_ratio,
            "max_drawdown": score.metrics.max_drawdown,
            "var_95_daily": score.metrics.var_95_daily,
            "beta_to_benchmark": score.metrics.beta_to_benchmark,
        }
        system, prompt = build_formatter_messages(
            user_message=body.message,
            context=context,
            tool_results=tool_results,
            agent_name="Portfolio Copilot",
        )

        yield _sse("status", {"phase": "writing"})
        produced = False
        try:
            for chunk in streamer(prompt, system, 3500, 0.3):
                produced = True
                yield _sse("delta", {"text": chunk})
        except Exception as exc:  # noqa: BLE001 - stream blew up
            _log.warning("copilot.stream.failed reason=%s", type(exc).__name__)

        # If NOTHING streamed — whether the stream raised before the first
        # token OR completed yielding no text (e.g. the model spent every
        # tool turn without composing an answer) — fall back to the
        # deterministic template so the user never gets a blank bubble.
        if not produced:
            from agents.orchestrator import route_message

            resp = route_message(body.message, score, positions, llm_callable=None)
            yield _sse("delta", {"text": resp.response_markdown})

        yield _sse(
            "done",
            {
                "agent_name": "Portfolio Copilot",
                "grounded_in": grounded,
                "draft_trades": draft_trades,
            },
        )

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
