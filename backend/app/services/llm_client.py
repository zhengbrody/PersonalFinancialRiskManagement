"""Stateless LLM wrapper for the Copilot agent layer.

The orchestrator (``agents.orchestrator.route_message``) accepts an
optional ``llm_callable`` with the signature
``(prompt, system, max_tokens, temperature) -> str``. When it's ``None``
the orchestrator degrades to deterministic, template-based answers
grounded in the engine's exact metrics — a fully functional (if less
fluent) Copilot.

**Degrade-to-None contract.** ``get_llm_callable()`` returns ``None``
whenever we *can't* safely call the configured provider — missing API key OR
the SDK isn't importable. Callers pass the result straight
through to ``route_message(..., llm_callable=...)``; ``None`` simply
selects the template path. This keeps the endpoint up even on a box
with no key configured, and means tests can exercise both modes by
monkeypatching this one function.

No Streamlit imports here — this lives in the FastAPI process only.
"""

from __future__ import annotations

import logging
from typing import Callable, Optional

from ..core.config import get_settings

_log = logging.getLogger(__name__)

# max_tokens at/below this routes to the cheaper/faster Haiku; larger
# generations (full analyses) go to Sonnet.
_HAIKU_MAX_TOKENS = 1024
_HAIKU_MODEL = "claude-haiku-4-5-20251001"
_SONNET_MODEL = "claude-sonnet-4-6"

# Tool-use loop bound. Each turn is one extra Anthropic round-trip plus
# the (possibly slow) tool executors, so we cap iterations to keep
# Copilot latency + cost bounded. 3 turns covers the common chains (the model
# rarely needs more than 2-3 tools); on the final turn tools are withheld so the
# model must synthesize text rather than dangle on a tool_use.
MAX_TOOL_TURNS = 3

# Module-level caches: build SDK clients once per process. ``None`` means "not
# yet attempted"; we (re)build lazily in get_llm_callable.
_anthropic_client = None
_deepseek_client = None


def _get_anthropic_client():
    """Return the cached Anthropic client, or ``None`` if we can't build
    one (no key / SDK import failure). This is the single gate behind the
    degrade-to-None contract used by both the plain and tool-use paths."""
    global _anthropic_client

    api_key = get_settings().anthropic_api_key
    if not api_key:
        # No key configured → degrade to templates silently. Logged at
        # debug so we don't spam a (legitimately) key-less deployment.
        _log.debug("llm_client.no_api_key — Copilot will use templates")
        return None

    if _anthropic_client is None:
        try:
            import anthropic
        except Exception as exc:  # pragma: no cover - SDK installed in CI
            _log.warning("llm_client.sdk_import_failed err=%s", type(exc).__name__)
            return None
        _anthropic_client = anthropic.Anthropic(api_key=api_key)

    return _anthropic_client


def _get_deepseek_client():
    """Return the cached OpenAI-compatible DeepSeek client, or ``None``."""
    global _deepseek_client

    settings = get_settings()
    if not settings.deepseek_api_key:
        _log.debug("llm_client.no_deepseek_key — Copilot will use templates")
        return None

    if _deepseek_client is None:
        try:
            from openai import OpenAI
        except Exception as exc:  # pragma: no cover - SDK installed in CI
            _log.warning("llm_client.openai_sdk_import_failed err=%s", type(exc).__name__)
            return None
        _deepseek_client = OpenAI(
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
        )

    return _deepseek_client


def _get_client():
    """Backward-compatible alias used by older tests for the Anthropic path."""
    return _get_anthropic_client()


def _text_of(resp) -> str:
    """Concatenate the text blocks of a Messages response, ignoring
    tool_use / other block types."""
    parts = []
    for block in getattr(resp, "content", []) or []:
        if getattr(block, "type", None) == "text":
            parts.append(getattr(block, "text", "") or "")
    return "".join(parts)


def _make_plain_callable(client) -> Callable[[str, str, int, float], str]:
    """Build the original no-tools callable (Haiku/Sonnet by max_tokens)."""

    def _call(prompt: str, system: str, max_tokens: int, temperature: float) -> str:
        model = _HAIKU_MODEL if max_tokens <= _HAIKU_MAX_TOKENS else _SONNET_MODEL
        resp = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.content[0].text

    return _call


def _make_deepseek_plain_callable(client) -> Callable[[str, str, int, float], str]:
    """Build an OpenAI-compatible DeepSeek callable."""
    settings = get_settings()
    model = settings.deepseek_model

    def _call(prompt: str, system: str, max_tokens: int, temperature: float) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        resp = client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=messages,
        )
        choice = (getattr(resp, "choices", None) or [None])[0]
        message = getattr(choice, "message", None)
        return (getattr(message, "content", "") or "").strip()

    return _call


def _make_tool_using_callable(client) -> Callable[[str, str, int, float], str]:
    """Build a callable with the SAME orchestrator signature that runs an
    Anthropic tool-use loop, letting the model fetch live free market data
    (sentiment / news / macro / fundamentals / options IV) while composing
    its answer.

    Always uses Sonnet — tool-call reasoning is materially better on the
    larger model and the Copilot chat turn is worth it. The loop is capped
    at ``MAX_TOOL_TURNS``; if anything in the loop throws unexpectedly we
    fall back to a single plain (no-tools) create so the user still gets a
    grounded answer rather than an error. If even that fails we re-raise,
    letting ``route_message``'s own try/except drop to template fallback.
    """
    from .copilot_tools import TOOL_SPECS, execute_tool

    plain = _make_plain_callable(client)

    def _call(prompt: str, system: str, max_tokens: int, temperature: float) -> str:
        try:
            messages: list[dict] = [{"role": "user", "content": prompt}]
            resp = None
            for turn in range(MAX_TOOL_TURNS):
                # On the FINAL allowed turn, withhold the tools so the model is
                # forced to SYNTHESIZE a text answer from what it already
                # gathered — otherwise a model that keeps asking for tools
                # leaves us returning an empty/partial tool_use turn.
                last_turn = turn == MAX_TOOL_TURNS - 1
                kwargs: dict = dict(
                    model=_SONNET_MODEL,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    system=system,
                    messages=messages,
                )
                if not last_turn:
                    kwargs["tools"] = TOOL_SPECS
                resp = client.messages.create(**kwargs)
                if last_turn or getattr(resp, "stop_reason", None) != "tool_use":
                    break

                # Record the assistant turn (text + tool_use blocks) verbatim.
                messages.append({"role": "assistant", "content": resp.content})

                tool_results = []
                for block in resp.content:
                    if getattr(block, "type", None) == "tool_use":
                        result = execute_tool(block.name, block.input)
                        tool_results.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": result,
                            }
                        )
                messages.append({"role": "user", "content": tool_results})

            return _text_of(resp) if resp is not None else ""
        except Exception as exc:  # noqa: BLE001 - degrade tool loop → plain create
            _log.warning(
                "llm_client.tool_loop_failed err=%s — falling back to no-tools",
                type(exc).__name__,
            )
            # Re-raise here would skip the live answer entirely; a plain
            # create still grounds in the portfolio context already in the
            # prompt. If THIS throws too, let it propagate to route_message.
            return plain(prompt, system, max_tokens, temperature)

    return _call


def get_llm_callable(
    *, with_tools: bool = False
) -> Optional[Callable[[str, str, int, float], str]]:
    """Return a callable matching the orchestrator's ``LLMCallable``
    signature, or ``None`` to signal "use deterministic templates".

    Returns ``None`` when the API key is missing or the SDK import
    fails — that's the designed fallback, not an error.

    Args:
        with_tools: when True, return the tool-use variant that lets the
            model call free data tools (Sonnet, capped loop). When False
            (default — preserves the original behaviour + call sites),
            return the plain Haiku/Sonnet-by-size callable.
    """
    settings = get_settings()

    if settings.llm_provider == "deepseek":
        client = _get_deepseek_client()
        if client is None:
            return None
        if with_tools:
            _log.info("llm_client.deepseek_plain_fallback_for_tool_request")
        return _make_deepseek_plain_callable(client)

    client = _get_anthropic_client()
    if client is None:
        return None

    if with_tools:
        return _make_tool_using_callable(client)
    return _make_plain_callable(client)


def get_answer_streamer():
    """Return a generator ``(prompt, system, max_tokens, temperature) ->
    Iterator[str]`` that STREAMS the answer text token-by-token while running
    the same free-data tool-use loop — so the UI shows text as it's written
    instead of waiting for the whole turn. ``None`` when no key/SDK (caller
    falls back to a one-shot non-streamed answer).

    Each turn is streamed via the Anthropic streaming API: text deltas are
    yielded live; if the turn ends by requesting tools, we execute them and
    stream the next turn. The final (end_turn) turn's deltas ARE the answer.
    """
    settings = get_settings()
    if settings.llm_provider == "deepseek":
        callable_ = get_llm_callable(with_tools=False)
        if callable_ is None:
            return None

        def _deepseek_stream(prompt: str, system: str, max_tokens: int, temperature: float):
            # DeepSeek's OpenAI-compatible path is kept non-streaming for now;
            # yield once so callers keep the same iterator contract.
            yield callable_(prompt, system, max_tokens, temperature)

        return _deepseek_stream

    client = _get_anthropic_client()
    if client is None:
        return None

    from .copilot_tools import TOOL_SPECS, execute_tool

    def _stream(prompt: str, system: str, max_tokens: int, temperature: float):
        messages: list[dict] = [{"role": "user", "content": prompt}]
        for turn in range(MAX_TOOL_TURNS):
            # Final allowed turn → withhold tools so the model must stream a
            # text answer instead of requesting yet another tool (which would
            # end the loop with no answer). Mirrors _make_tool_using_callable.
            last_turn = turn == MAX_TOOL_TURNS - 1
            kwargs: dict = dict(
                model=_SONNET_MODEL,
                max_tokens=max_tokens,
                temperature=temperature,
                system=system,
                messages=messages,
            )
            if not last_turn:
                kwargs["tools"] = TOOL_SPECS
            with client.messages.stream(**kwargs) as stream:
                for chunk in stream.text_stream:
                    if chunk:
                        yield chunk
                final = stream.get_final_message()

            if last_turn or getattr(final, "stop_reason", None) != "tool_use":
                return  # end_turn (or tools exhausted) — deltas were the answer

            messages.append({"role": "assistant", "content": final.content})
            tool_results = []
            for block in final.content:
                if getattr(block, "type", None) == "tool_use":
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": execute_tool(block.name, block.input),
                        }
                    )
            messages.append({"role": "user", "content": tool_results})

    return _stream
