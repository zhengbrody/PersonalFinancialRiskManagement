"""Lightweight AI-quality eval signals, logged to telemetry for monitoring the
assistant's behaviour over time (a future routing / MLE foundation, NOT a stock
model).

These are best-effort HEURISTICS that flag for review — they never block a
response. They look only at the answer text + the deterministic evidence the
platform already computed; no user data beyond that is involved.
"""

from __future__ import annotations

import re

# Imperative buy/sell language the assistant must never emit. We match action
# phrases, not the bare words "buy"/"sell" (which appear in honest framing like
# "if you were to sell…") — conservative, to avoid false alarms.
_ADVICE_RE = re.compile(
    r"(you should (buy|sell|short|dump|load up)"
    r"|i('?d| would) (buy|sell|short)"
    r"|(buy|sell|short) (it|this|now|today|immediately)"
    r"|strong (buy|sell)"
    r"|time to (buy|sell))",
    re.IGNORECASE,
)

# A salient money or percent figure (the kind a verdict/answer cites).
_SALIENT_NUM_RE = re.compile(r"(\$\s?\d[\d,]*\.?\d*|\d[\d,]*\.?\d*\s?%)")


def detect_direct_advice(text: str | None) -> bool:
    return bool(text and _ADVICE_RE.search(text))


def answer_grounded(text: str | None, evidence_count: int) -> bool:
    """True when a non-trivial answer has supporting evidence to cite. A
    non-empty answer with ZERO evidence spoke without platform data."""
    if not text or not text.strip():
        return False
    return evidence_count > 0


def detect_invented_number(text: str | None, evidence_count: int) -> bool:
    """Flag the unambiguous failure mode: the answer asserts a $/% figure while
    the pipeline gathered NO deterministic evidence to back it. When evidence
    exists, the synthesis is constrained to cite it, so we don't second-guess
    rounding/rephrasing (that would be noisy and produce false positives)."""
    if not text or evidence_count > 0:
        return False
    return bool(_SALIENT_NUM_RE.search(text))


def eval_signals(
    *,
    text: str | None,
    evidence_count: int,
    intent: str | None = None,
    tool_turn_count: int | None = None,
    fallback_used: bool | None = None,
) -> dict:
    """Bundle the eval fields for telemetry metadata. All keys are scalar +
    privacy-safe (no tickers / $ / holdings / raw prompt)."""
    out: dict = {
        "answer_grounded": answer_grounded(text, evidence_count),
        "invented_number_detected": detect_invented_number(text, evidence_count),
        "direct_advice_detected": detect_direct_advice(text),
    }
    if intent is not None:
        out["intent"] = intent
    if tool_turn_count is not None:
        out["tool_turn_count"] = tool_turn_count
    if fallback_used is not None:
        out["fallback_used"] = fallback_used
    return out
