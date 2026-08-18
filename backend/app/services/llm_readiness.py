"""Is the CONFIGURED LLM model still serviceable?

Every other integration check in this codebase asks "is a key present?". That
question could not have caught the failure that actually happened: on
2026-07-25 DeepSeek retired the model name we send (``deepseek-chat``) during
its v4 rollout. The key stayed perfectly valid, so nothing flagged it — every
AI surface silently fell back to deterministic templates, and it took a manual
Sentry read three weeks later to notice. (DeepSeek then restored the name; its
model list now advertises only v4, so the retirement will land for good.)

So this asks the question that matters: **is the model we are configured to
call actually offered by the provider right now?** The provider's model-list
endpoint answers it for free — no tokens, no cost — which is what makes it
cheap enough to poll.

Design notes:
  * Result is CACHED (``_TTL``) so the deep health probe and the admin page can
    both consult it without a network hop per request.
  * The model list alone is NOT the answer, which a live probe proved: on
    2026-08-17 ``deepseek-chat`` had already been dropped from the list while
    still answering completions — a deprecation grace period. Reporting that as
    "retired" would be a false alarm, and a check that cries wolf gets ignored,
    which is the very failure mode this exists to prevent. So an unlisted model
    is confirmed with ONE 1-token call, giving three honest outcomes: current,
    deprecated-but-serving (migrate now, on the provider's clock), and actually
    rejected (the outage).
  * Never raises. An unreachable provider is reported as ``unreachable``, not
    as a retired model — conflating "we could not ask" with "the answer is no"
    would page for a network blip.
  * INFORMATIONAL by design. AI degrading to deterministic templates is a
    documented product behaviour, so a bad answer here must never flip
    readiness — it exists to be *seen*, not to fail a probe.
"""

from __future__ import annotations

import json
import time
import urllib.request
from dataclasses import dataclass
from typing import Literal

from ..core.config import get_settings

# Long enough that polling is free, short enough that a retirement surfaces the
# same day. The failure this guards against takes effect on the provider's
# schedule, not ours.
_TTL = 900.0
# The deep probe is timeboxed ~2s in total; keep this well inside it.
_TIMEOUT = 2.0

State = Literal["ok", "deprecated", "model_retired", "unreachable", "not_configured"]


@dataclass(frozen=True)
class ModelReadiness:
    state: State
    detail: str
    provider: str
    model: str

    @property
    def ok(self) -> bool:
        """Is the model SERVICEABLE right now?

        ``deprecated`` counts: AI is working, so a readiness view must not go
        red for months while a migration is scheduled. ``unreachable`` does
        NOT count — it is unknown, and an unknown that reads as healthy is how
        the original failure hid.
        """
        return self.state in ("ok", "deprecated")

    @property
    def action_required(self) -> bool:
        """Separate axis from ``ok``: work is needed even while it still
        serves. This is the early warning — the whole point."""
        return self.state in ("deprecated", "model_retired")


_cache: dict[str, tuple[float, ModelReadiness]] = {}


def _deepseek_model_ids(settings) -> list[str]:
    req = urllib.request.Request(
        settings.deepseek_base_url.rstrip("/") + "/models",
        headers={"Authorization": f"Bearer {settings.deepseek_api_key}"},
    )
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:  # noqa: S310 - fixed host
        payload = json.load(resp)
    return [str(row.get("id")) for row in (payload.get("data") or []) if row.get("id")]


def _anthropic_model_ids(settings) -> list[str]:
    import anthropic

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key, timeout=_TIMEOUT)
    return [str(m.id) for m in client.models.list(limit=50).data]


def _deepseek_answers(settings, model: str) -> tuple[bool, str]:
    body = json.dumps(
        {"model": model, "messages": [{"role": "user", "content": "."}], "max_tokens": 1}
    ).encode()
    req = urllib.request.Request(
        settings.deepseek_base_url.rstrip("/") + "/chat/completions",
        data=body,
        headers={
            "Authorization": f"Bearer {settings.deepseek_api_key}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT):  # noqa: S310 - fixed host
            return True, ""
    except Exception as exc:  # noqa: BLE001
        return False, type(exc).__name__


def _model_answers(settings, model: str) -> tuple[bool, str]:
    """Provider-specific 'does this model still serve?' confirmation."""
    if settings.llm_provider == "deepseek":
        return _deepseek_answers(settings, model)
    return False, "no confirmation available"


def _probe(settings) -> ModelReadiness:
    provider = settings.llm_provider
    if provider == "deepseek":
        model, key, lister = settings.deepseek_model, settings.deepseek_api_key, _deepseek_model_ids
    elif provider == "anthropic":
        # The Anthropic path routes by max_tokens rather than a single pinned
        # model name, so there is no one id to assert; presence of ANY model
        # proves the key + endpoint. Report the provider, not a model.
        model, key, lister = "", settings.anthropic_api_key, _anthropic_model_ids
    else:
        return ModelReadiness("not_configured", f"No live check for '{provider}'.", provider, "")

    if not key:
        return ModelReadiness("not_configured", "No API key configured.", provider, model)

    try:
        ids = lister(settings)
    except Exception as exc:  # noqa: BLE001 - a probe must never break its caller
        return ModelReadiness(
            "unreachable", f"Could not reach {provider}: {type(exc).__name__}", provider, model
        )

    if not model:
        return ModelReadiness("ok", f"{provider} reachable ({len(ids)} models).", provider, model)
    if model in ids:
        return ModelReadiness("ok", f"'{model}' is offered by {provider}.", provider, model)

    # Unlisted — but is it actually gone? Confirm with the cheapest possible
    # call rather than guessing, so a grace period isn't reported as an outage.
    offered = ", ".join(sorted(ids)) or "none"
    serving, why = _model_answers(settings, model)
    if serving:
        return ModelReadiness(
            "deprecated",
            f"'{model}' still answers but {provider} no longer lists it — "
            f"migrate to: {offered}.",
            provider,
            model,
        )
    return ModelReadiness(
        "model_retired",
        f"'{model}' is rejected by {provider} ({why}) — available: {offered}.",
        provider,
        model,
    )


def check(*, force: bool = False) -> ModelReadiness:
    """Cached readiness of the configured provider+model. Never raises."""
    settings = get_settings()
    key = f"{settings.llm_provider}:{settings.deepseek_model}"
    now = time.monotonic()
    hit = _cache.get(key)
    if hit and not force and now - hit[0] < _TTL:
        return hit[1]
    result = _probe(settings)
    _cache[key] = (now, result)
    return result


def reset_cache() -> None:
    """Test seam — the module-level cache would otherwise leak across cases."""
    _cache.clear()
