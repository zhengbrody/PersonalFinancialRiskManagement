"""Experimental TypeSafe "Jev" intent classifier — shadow-only, fail-soft.

Research adapter for docs/jev-intent-experiment.md. It asks Jev one Choice
question ("which Copilot intent is this?") over the user's question text and
returns a label from the router's CLOSED intent set, or ``None``.

Hard boundaries (tested):

* Default OFF. With ``MINDMARKET_JEV_INTENT_ENABLED`` false or no
  ``TYPESAFE_API_KEY`` the adapter performs no network I/O at all.
* The request ``state`` is ONLY the user's own question text (stripped and
  length-bounded). Never account data, holdings-derived tickers, prompts,
  page context or user ids.
* Never raises. Timeout, transport error, non-200, malformed JSON, a label
  outside the closed set, a non-finite confidence or an exhausted budget all
  return ``None`` so the caller keeps the deterministic classifier.
* It classifies routing intent only. It must never feed arithmetic,
  authorization, signing, saving or orders — and it is NOT wired into the
  live ``/ask`` path. :func:`shadow_compare` exists for logging-only
  comparison; it logs label enums and latency, never text.
* Jev's own ``confidence`` is returned for analysis but is NOT a decision
  threshold: any threshold must be chosen from the offline eval's
  reliability data (see the doc's calibration section).

Endpoint/schema per https://docs.typesafe.ai/api (verified 2026-10-10).
"""

from __future__ import annotations

import logging
import math
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Callable, Optional

import httpx

from ..core.config import get_settings

log = logging.getLogger(__name__)

ENDPOINT = "https://api.typesafe.ai/v1/systemone"
# Pinned versioned id (not the moving ``jev-latest`` alias): the docs advise
# pinning when thresholds were tuned against a specific version.
MODEL = "jev-1.13.0"
TIMEOUT_SECONDS = 1.5
MAX_QUESTION_CHARS = 500
# Per-process budget. Conservative on purpose: this is an experiment.
MAX_CALLS_PER_MINUTE = 30
MAX_CALLS_PER_HOUR = 600
_QUESTION_ID = "intent"

# Closed label set — must equal copilot_router._KW keys (a test pins it).
# Descriptions are the Choice criteria Jev reads; they describe the ROUTE,
# mirroring how the deterministic router uses each intent.
INTENT_CRITERIA: dict[str, str] = {
    "portfolio_diagnosis": (
        "How risky, healthy, diversified or concentrated the user's own "
        "portfolio is overall; general questions about their holdings."
    ),
    "scenario_simulation": (
        "What would happen to the user's portfolio under a hypothetical market "
        "move: crash, drop, recession, correction, or a specific % shock."
    ),
    "macro_rates": (
        "The overall market or economy: interest rates, the Fed, inflation, "
        "VIX, yield curve, market regime, fear and greed. Not one stock."
    ),
    "tax_fee_review": ("Taxes, tax-loss harvesting, fund fees or expense ratios."),
    "explain_metric": (
        "A definition or explanation of a financial concept or metric "
        "(e.g. what Sharpe, VaR, beta or drawdown means), not a request to "
        "assess the user's own account."
    ),
    "action_plan": (
        "What the user should do next to improve or rebalance their portfolio; "
        "next steps or an improvement plan."
    ),
    "ticker_research": ("Research, valuation or opinion about one specific named stock or ETF."),
    "compare_tickers": ("Comparing two or more specific named stocks or ETFs against each other."),
    "margin_risk": (
        "Margin, leverage, borrowed money, buying power or maintenance "
        "requirements in the user's account."
    ),
    "options_risk": (
        "Options positions or options concepts: greeks, assignment, expiry, "
        "spreads, covered calls, puts."
    ),
}
INTENT_LABELS: frozenset[str] = frozenset(INTENT_CRITERIA)

_INSTRUCTIONS = (
    "Which kind of request is this investor question to a portfolio-risk "
    "assistant? Pick the single best route."
)


@dataclass(frozen=True)
class JevIntent:
    label: str
    confidence: float
    model: str
    latency_ms: float


class _Budget:
    """Thread-safe per-process sliding-window call limiter."""

    def __init__(self, per_minute: int, per_hour: int, clock: Callable[[], float]):
        self._per_minute = per_minute
        self._per_hour = per_hour
        self._clock = clock
        self._calls: deque[float] = deque()
        self._lock = threading.Lock()

    def try_acquire(self) -> bool:
        with self._lock:
            now = self._clock()
            while self._calls and now - self._calls[0] >= 3600.0:
                self._calls.popleft()
            last_minute = sum(1 for t in self._calls if now - t < 60.0)
            if last_minute >= self._per_minute or len(self._calls) >= self._per_hour:
                return False
            self._calls.append(now)
            return True


_budget = _Budget(MAX_CALLS_PER_MINUTE, MAX_CALLS_PER_HOUR, time.monotonic)


def reset_budget_for_tests(
    per_minute: int = MAX_CALLS_PER_MINUTE,
    per_hour: int = MAX_CALLS_PER_HOUR,
    clock: Callable[[], float] = time.monotonic,
) -> None:
    global _budget
    _budget = _Budget(per_minute, per_hour, clock)


def _request_body(question: str) -> dict[str, Any]:
    return {
        "state": question,
        "model": MODEL,
        "questions": {
            _QUESTION_ID: {
                "type": "choice",
                "instructions": _INSTRUCTIONS,
                "criteria": dict(INTENT_CRITERIA),
            }
        },
    }


def _parse(payload: Any) -> Optional[tuple[str, float, str]]:
    """Validate the typed response; anything off-contract → None."""
    if not isinstance(payload, dict):
        return None
    answers = payload.get("answers")
    if not isinstance(answers, dict):
        return None
    ans = answers.get(_QUESTION_ID)
    if not isinstance(ans, dict) or ans.get("type") != "choice":
        return None
    label = ans.get("choice")
    if not isinstance(label, str) or label not in INTENT_LABELS:
        return None
    conf = ans.get("confidence")
    if isinstance(conf, bool) or not isinstance(conf, (int, float)):
        return None
    conf = float(conf)
    if not math.isfinite(conf) or not 0.0 <= conf <= 1.0:
        return None
    model = payload.get("model")
    return label, conf, model if isinstance(model, str) else "unknown"


def classify_intent(
    question: str,
    *,
    transport: Optional[httpx.BaseTransport] = None,
    settings: Any = None,
) -> Optional[JevIntent]:
    """Return Jev's intent for ``question``, or None (caller keeps its own)."""
    try:
        cfg = settings if settings is not None else get_settings()
        if not getattr(cfg, "jev_intent_enabled", False):
            return None
        key = getattr(cfg, "typesafe_api_key", "") or ""
        if not key:
            return None
        text = (question or "").strip()[:MAX_QUESTION_CHARS]
        if not text:
            return None
        if not _budget.try_acquire():
            log.info("jev_intent.budget_exhausted")
            return None
        started = time.perf_counter()
        with httpx.Client(timeout=TIMEOUT_SECONDS, transport=transport) as client:
            resp = client.post(
                ENDPOINT,
                json=_request_body(text),
                headers={"Authorization": f"Bearer {key}"},
            )
        latency_ms = (time.perf_counter() - started) * 1000.0
        if resp.status_code != 200:
            log.info("jev_intent.http_status status=%s", resp.status_code)
            return None
        parsed = _parse(resp.json())
        if parsed is None:
            log.info("jev_intent.off_contract")
            return None
        label, conf, model = parsed
        return JevIntent(label=label, confidence=conf, model=model, latency_ms=latency_ms)
    except Exception as exc:  # fail-soft by contract: never raise to the caller
        log.info("jev_intent.failed err=%s", type(exc).__name__)
        return None


def shadow_compare(
    question: str,
    *,
    tickers: Optional[list[str]] = None,
    route: Optional[str] = None,
    transport: Optional[httpx.BaseTransport] = None,
    settings: Any = None,
) -> dict[str, Any]:
    """Both labels for logging-only comparison. The deterministic label is the
    one any caller must act on; this function changes nothing.

    Logs label enums, agreement and latency only — never the question text.
    """
    from . import copilot_router

    tks = tickers if tickers is not None else copilot_router.extract_tickers(question)
    current = copilot_router.classify(question, tks, route=route)
    jev = classify_intent(question, transport=transport, settings=settings)
    out = {
        "current": current,
        "jev": jev.label if jev else None,
        "agree": (jev.label == current) if jev else None,
        "jev_confidence": jev.confidence if jev else None,
        "jev_model": jev.model if jev else None,
        "latency_ms": round(jev.latency_ms, 1) if jev else None,
    }
    log.info(
        "jev_intent.shadow current=%s jev=%s agree=%s latency_ms=%s",
        out["current"],
        out["jev"],
        out["agree"],
        out["latency_ms"],
    )
    return out
