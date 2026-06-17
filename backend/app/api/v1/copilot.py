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
from ...schemas.copilot2 import CopilotAskRequest
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


_CHAT_MODEL = "claude-sonnet-4-6"


def _record_chat_cost(user_id: str, answer_text: str) -> None:
    """Record the ACTUAL token cost of a chat turn so credits deplete and the
    owner dashboard reflects real spend. Output dominates cost; input is a
    fixed context proxy (positions + score + grounding). Never raises."""
    try:
        from libs.billing.costs import estimate_cost_usd, estimate_tokens
        from libs.billing.usage import record_event

        tokens_out = estimate_tokens(answer_text)
        tokens_in = 1500  # context proxy; output dominates the bill
        cost = estimate_cost_usd(
            "anthropic", _CHAT_MODEL, tokens_in=tokens_in, tokens_out=tokens_out
        )
        record_event(
            user_id,
            "chat",
            provider="anthropic",
            model=_CHAT_MODEL,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost,
        )
    except Exception:  # noqa: BLE001
        _log.warning("copilot.cost_record_failed")


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

    # ── Credit gate ───────────────────────────────────────────────────
    # AI usage is metered by credits (= real token cost). A hard
    # QuotaExceeded → 429 (out of credits). ANY OTHER failure (Supabase
    # outage, schema drift) must NOT lock the user out: we'd rather eat the
    # rare unmetered call than hand a paying customer a 500.
    from libs.billing.usage import ESTIMATED_COST_USD, QuotaExceeded, check_credits

    try:
        check_credits(user.id, email=user.email, estimated_cost_usd=ESTIMATED_COST_USD["chat"])
    except QuotaExceeded as exc:
        raise too_many_requests(str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - fail-open on metering blip
        _log.warning("copilot.credit_check_failed reason=%s", type(exc).__name__)

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

    # Record the ACTUAL cost so credits deplete + the dashboard is accurate.
    _record_chat_cost(user.id, resp.response_markdown or "")

    payload = ChatResponse(**resp.model_dump()).model_dump()
    return ok(payload, request=request, started_at=started)


@router.post(
    "/ask",
    summary="Copilot 2.0 — intent-routed, evidence-grounded answer",
    response_model=None,
)
def copilot_ask_endpoint(
    body: CopilotAskRequest,
    request: Request,
    user: AuthedUser = Depends(require_user),
):
    """Copilot 2.0: classify the message into one of 8 intents, gather
    deterministic evidence (ticker FactPacks, portfolio score, macro regime,
    fee/tax scans, metric glossary), then synthesize ONE answer in the fixed
    five-section format using only that evidence.

    Unlike ``/chat`` this does NOT require an active portfolio — ticker /
    compare / macro / explain intents answer with no holdings. Evidence
    gathering is fail-soft (a dead provider just thins the evidence).
    Credit-gated (LLM); fail-open on a metering blip; data-only without a key.
    """
    started = time.perf_counter()

    # ── Response cache (input-hash, 30 min). Keyed per-user because the
    # evidence folds in the caller's portfolio — never share across users.
    # Checked before the credit gate so a repeated question is free.
    from ...services.ai_cache import ask_cache
    from ...services.ai_telemetry import input_hash

    cache_key = input_hash(f"{user.id}|{body.message.strip()}")
    cached = ask_cache.get(cache_key)
    if cached is not None:
        return ok(cached, request=request, started_at=started)

    from libs.billing.usage import ESTIMATED_COST_USD, QuotaExceeded, check_credits

    try:
        check_credits(user.id, email=user.email, estimated_cost_usd=ESTIMATED_COST_USD["chat"])
    except QuotaExceeded as exc:
        raise too_many_requests(str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - fail-open on metering blip
        _log.warning("copilot.ask.credit_check_failed reason=%s", type(exc).__name__)

    from ...services import copilot_router

    llm = get_llm_callable(with_tools=False)
    result = copilot_router.answer(body.message, user=user, llm_callable=llm)

    if llm is not None and not result.data_only:
        _record_ask_cost(user.id, result, started)
        ask_cache.put(cache_key, result.model_dump())

    return ok(result.model_dump(), request=request, started_at=started)


def _record_ask_cost(user_id: str, result, started: float) -> None:
    from libs.billing.costs import estimate_tokens

    from ...services.ai_eval import eval_signals
    from ...services.ai_telemetry import input_hash, record_ai_call

    ev_text = "\n".join(f"{e.label}:{e.value}" for e in result.evidence)
    record_ai_call(
        user_id,
        "chat",
        model=_CHAT_MODEL,
        tokens_in=estimate_tokens(ev_text) + 600,
        tokens_out=estimate_tokens(result.answer_markdown or ""),
        latency_ms=(time.perf_counter() - started) * 1000,
        input_hash=input_hash(result.intent + "|" + ev_text),
        # Privacy-safe AI-quality eval signals (no tickers/$/prompt) for
        # monitoring the assistant over time — see services/ai_eval.py.
        eval_metadata=eval_signals(
            text=result.answer_markdown,
            evidence_count=len(result.evidence),
            intent=result.intent,
            fallback_used=bool(result.data_only),
        ),
    )


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

        # Credit gate (429 → error event; fail-open on a metering blip).
        from libs.billing.usage import ESTIMATED_COST_USD, QuotaExceeded, check_credits

        try:
            check_credits(user.id, email=user.email, estimated_cost_usd=ESTIMATED_COST_USD["chat"])
        except QuotaExceeded as exc:
            yield _sse("error", {"code": "quota_exceeded", "message": str(exc)})
            return
        except Exception as exc:  # noqa: BLE001 - fail-open
            _log.warning("copilot.stream.credit_failed reason=%s", type(exc).__name__)

        grounded = _grounded(score)

        # Route + assemble the prompt the SAME way the non-streaming /chat
        # does, so the streaming (live) path gets real agent routing: a
        # fee/tax/rebalance question reaches the StrategyOptimizer's scans,
        # not analyzer-only metrics. Cheap (no LLM) → safe before streaming.
        from agents.orchestrator import PortfolioAgentRouter, route_message

        try:
            plan = PortfolioAgentRouter().prepare(body.message, score, list(positions))
        except Exception:  # noqa: BLE001 - never fail the stream on routing
            plan = None

        agent_name = plan["agent_name"] if plan else "Portfolio Copilot"
        draft_trades = plan["draft_trades"] if plan else []

        streamer = get_answer_streamer()

        # No LLM key (or routing failed) → one-shot deterministic template.
        if streamer is None or plan is None:
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
            # Template path is cheap, but still meter it for an honest ledger.
            _record_chat_cost(user.id, resp.response_markdown or "")
            return

        system, prompt = plan["system"], plan["prompt"]

        yield _sse("status", {"phase": "writing"})
        produced = False
        parts: list[str] = []
        try:
            for chunk in streamer(prompt, system, 3500, 0.3):
                produced = True
                parts.append(chunk)
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
            parts.append(resp.response_markdown or "")
            yield _sse("delta", {"text": resp.response_markdown})

        yield _sse(
            "done",
            {
                "agent_name": agent_name,
                "grounded_in": grounded,
                "draft_trades": draft_trades,
                # produced=False means the deterministic fallback wrote the
                # answer — the UI labels the bubble accordingly.
                "ai_generated": produced,
            },
        )

        # Meter the ACTUAL answer (accumulated deltas) so credits deplete.
        _record_chat_cost(user.id, "".join(parts))

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
