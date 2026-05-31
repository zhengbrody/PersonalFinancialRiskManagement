"""Stateless Anthropic wrapper for the Copilot agent layer.

The orchestrator (``agents.orchestrator.route_message``) accepts an
optional ``llm_callable`` with the signature
``(prompt, system, max_tokens, temperature) -> str``. When it's ``None``
the orchestrator degrades to deterministic, template-based answers
grounded in the engine's exact metrics — a fully functional (if less
fluent) Copilot.

**Degrade-to-None contract.** ``get_llm_callable()`` returns ``None``
whenever we *can't* safely call Anthropic — missing API key OR the
``anthropic`` SDK isn't importable. Callers pass the result straight
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

# Module-level cache: build the SDK client once per process. ``None``
# means "not yet attempted"; we (re)build lazily in get_llm_callable.
_client = None


def get_llm_callable() -> Optional[Callable[[str, str, int, float], str]]:
    """Return a callable matching the orchestrator's ``LLMCallable``
    signature, or ``None`` to signal "use deterministic templates".

    Returns ``None`` when the API key is missing or the SDK import
    fails — that's the designed fallback, not an error.
    """
    global _client

    api_key = get_settings().anthropic_api_key
    if not api_key:
        # No key configured → degrade to templates silently. Logged at
        # debug so we don't spam a (legitimately) key-less deployment.
        _log.debug("llm_client.no_api_key — Copilot will use templates")
        return None

    if _client is None:
        try:
            import anthropic
        except Exception as exc:  # pragma: no cover - SDK installed in CI
            _log.warning("llm_client.sdk_import_failed err=%s", type(exc).__name__)
            return None
        _client = anthropic.Anthropic(api_key=api_key)

    client = _client

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
