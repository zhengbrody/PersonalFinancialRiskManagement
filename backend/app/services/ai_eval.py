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


# ── numeric-claim extraction + tolerance matching (grounding evals) ──
#
# Used by evals/run_grounding_eval.py to score answers against the evidence
# packet. HONEST SCOPE: this measures numeric TRACEABILITY (every figure the
# answer asserts can be found in the evidence within tolerance), not semantic
# correctness — an answer that cites an evidence number for the wrong metric
# still counts as traceable. The deterministic template prints evidence
# verbatim, so template-mode faithfulness ≈ 100% by construction; a live-LLM
# run (--llm) is what produces a meaningful number.

_SUFFIX_MULT = {
    "k": 1e3,
    "thousand": 1e3,
    "m": 1e6,
    "million": 1e6,
    "b": 1e9,
    "bn": 1e9,
    "billion": 1e9,
}

_MONEY_CLAIM_RE = re.compile(
    r"\$\s?(-?\d[\d,]*(?:\.\d+)?)\s*(k|m|bn|b|billion|million|thousand)?\b", re.IGNORECASE
)
# The sign is a minus only when NOT preceded by a digit — "3-5%" is a range
# whose right side is +5%, not -5%.
_PCT_CLAIM_RE = re.compile(r"((?:(?<!\d)-)?\d[\d,]*(?:\.\d+)?)\s?%")
_MULT_CLAIM_RE = re.compile(
    r"((?:(?<!\d)-)?\d[\d,]*(?:\.\d+)?)\s?[x×](?![A-Za-z0-9])", re.IGNORECASE
)
_BARE_CLAIM_RE = re.compile(r"(?<![\w.,])-?\d[\d,]*(?:\.\d+)?(?![\w%×])")

# Structural digit patterns masked BEFORE extraction (spaces of equal length,
# so spans stay aligned): ISO/slash dates and small "2-4"-style ranges. A
# range directly tied to a unit (3-5%, 2-3×) is NOT masked — that is a real
# numeric claim. Fractions like 720/1000 (3+ digits) are untouched.
_DATELIKE_RES = (
    re.compile(r"\b\d{4}-\d{1,2}(?:-\d{1,2})?\b"),  # 2026-07-08 / 2026-07
    re.compile(r"\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b"),  # 12/31, 12/31/2026
    re.compile(r"\b\d{1,2}-\d{1,2}\b(?!\s?[%×x])"),  # 2-4 steps, 12-month
)


def _mask_datelike(text: str) -> str:
    for rx in _DATELIKE_RES:
        text = rx.sub(lambda m: " " * len(m.group(0)), text)
    return text


def _to_float(raw: str) -> float:
    return float(raw.replace(",", ""))


def _is_noise_bare_number(text: str, value: float, start: int, end: int) -> bool:
    """Exclusions for BARE numbers only (money/%/× are always claims):
    years, list numbering, and small counting integers (≤12 — 'top 5',
    '3 holdings'; real metrics are decimals, %, $, or larger)."""
    raw = text[start:end].lstrip("-")
    if value == int(value) and 1900 <= abs(value) <= 2100 and len(raw.split(".")[0]) == 4:
        return True  # year
    after = text[end : end + 1]
    line_start = text.rfind("\n", 0, start) + 1
    if text[line_start:start].strip() == "" and after and after in ".)":
        return True  # list numbering "1." / "2)"
    if value == int(value) and abs(value) <= 12:
        return True  # small counting cardinal
    return False


def extract_numeric_claims(text: str | None) -> list[dict]:
    """All numeric claims in an answer: money ($, k/m/bn expanded), percents
    (sign kept), multiples (1.35×), then bare numbers not already covered.
    Each claim: {raw, value, kind, context (±40 chars), span}."""
    if not text:
        return []
    original = text
    text = _mask_datelike(text)
    claims: list[dict] = []
    taken: list[tuple[int, int]] = []

    def overlaps(a: int, b: int) -> bool:
        return any(a < t_end and b > t_start for t_start, t_end in taken)

    def add(match: re.Match, value: float, kind: str) -> None:
        a, b = match.span()
        if overlaps(a, b):
            return
        taken.append((a, b))
        ctx = " ".join(original[max(0, a - 40) : b + 40].split())
        claims.append(
            {"raw": match.group(0), "value": value, "kind": kind, "context": ctx, "span": (a, b)}
        )

    for m in _MONEY_CLAIM_RE.finditer(text):
        mult = _SUFFIX_MULT.get((m.group(2) or "").lower(), 1.0)
        add(m, _to_float(m.group(1)) * mult, "money")
    for m in _PCT_CLAIM_RE.finditer(text):
        add(m, _to_float(m.group(1)), "percent")
    for m in _MULT_CLAIM_RE.finditer(text):
        add(m, _to_float(m.group(1)), "multiple")
    for m in _BARE_CLAIM_RE.finditer(text):
        a, b = m.span()
        if overlaps(a, b):
            continue
        value = _to_float(m.group(0))
        if _is_noise_bare_number(text, value, a, b):
            continue
        add(m, value, "number")
    claims.sort(key=lambda c: c["span"][0])
    return claims


def numeric_values(text: str | None) -> list[float]:
    """Just the values — used to build the evidence value set with the SAME
    extractor (so formatting differences cancel out)."""
    return [c["value"] for c in extract_numeric_claims(text)]


def _close(a: float, b: float, rtol: float) -> bool:
    if a == b:
        return True
    if a == 0.0 or b == 0.0:
        return abs(a - b) <= 1e-9
    return abs(a - b) <= rtol * max(abs(a), abs(b))


def match_claims(claims: list[dict], evidence_values: list[float], *, rtol: float = 0.06) -> dict:
    """Tolerance-match each claim against the evidence value set.

    Candidates per claim cover representation differences the SAME number can
    legitimately take: percent↔ratio (×100 / ÷100) and sign/absolute phrasing
    ("drawdown of 31%" vs evidence "-31.0%"). A claim with no candidate within
    ``rtol`` of any evidence value is a violation. No claims → faithfulness
    1.0 (nothing asserted, nothing to invent)."""
    ev = [float(v) for v in evidence_values]
    matched = 0
    violations: list[dict] = []
    for c in claims:
        v = float(c["value"])
        candidates = {v, v * 100.0, v / 100.0, abs(v), -v, abs(v) * 100.0, abs(v) / 100.0}
        if any(_close(cand, e, rtol) for cand in candidates for e in ev):
            matched += 1
        else:
            violations.append(c)
    total = len(claims)
    return {
        "total": total,
        "matched": matched,
        "faithfulness": (matched / total) if total else 1.0,
        "violations": violations,
    }


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
