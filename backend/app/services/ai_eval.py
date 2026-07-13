"""Lightweight AI-quality eval signals, logged to telemetry for monitoring the
assistant's behaviour over time (a future routing / MLE foundation, NOT a stock
model).

These are best-effort HEURISTICS that flag for review — they never block a
response. They look only at the answer text + the deterministic evidence the
platform already computed; no user data beyond that is involved.
"""

from __future__ import annotations

import math
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
# Chinese imperative buy/sell phrases (same conservative discipline: an action
# prefix + a trade verb, so honest framing like "如果你想卖出…" doesn't trip).
# The (?<!不) lookbehind keeps negated boundary language ("不建议买入") clean.
_ADVICE_ZH_RE = re.compile(r"(?<!不)(立即|马上|应该|建议|强烈)(买入|卖出|清仓|抛售|加仓|做空)")

# A salient money or percent figure (the kind a verdict/answer cites).
_SALIENT_NUM_RE = re.compile(r"([$¥￥]\s?\d[\d,]*\.?\d*|\d[\d,]*\.?\d*\s?[%％])")


def detect_direct_advice(text: str | None) -> bool:
    if not text:
        return False
    return bool(_ADVICE_RE.search(text) or _ADVICE_ZH_RE.search(text))


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


# ── numeric-claim extraction + kind-aware matching (grounding evals) ──
#
# Used by evals/run_grounding_eval.py AND the runtime grounding gate to score
# answers against the evidence packet. HONEST SCOPE: this measures numeric
# TRACEABILITY (every figure the answer asserts IS an evidence value, a unit
# conversion of one, or a display rounding of one — or an explicitly-framed
# user assumption), not semantic correctness — an answer that cites an
# evidence number for the wrong metric still counts as traceable. The
# deterministic template prints evidence verbatim, so template-mode
# faithfulness ≈ 100% by construction; a live-LLM run (--llm) is what
# produces a meaningful number.

_SUFFIX_MULT = {
    "k": 1e3,
    "thousand": 1e3,
    "m": 1e6,
    "million": 1e6,
    "b": 1e9,
    "bn": 1e9,
    "billion": 1e9,
}

# Boundary classes are ASCII-only (NOT \w/\b, which are Unicode-aware and
# would treat CJK characters as word chars — "贝塔是1.18" must extract 1.18).
_MONEY_CLAIM_RE = re.compile(
    r"\$\s?(-?\d[\d,]*(?:\.\d+)?)\s*(k|m|bn|b|billion|million|thousand)?(?![0-9A-Za-z_])",
    re.IGNORECASE,
)
# The sign is a minus only when NOT preceded by a digit — "3-5%" is a range
# whose right side is +5%, not -5%. Full-width ％ is normal zh-CN typography.
_PCT_CLAIM_RE = re.compile(r"((?:(?<!\d)-)?\d[\d,]*(?:\.\d+)?)\s?[%％]")
_MULT_CLAIM_RE = re.compile(
    r"((?:(?<!\d)-)?\d[\d,]*(?:\.\d+)?)\s?[x×](?![A-Za-z0-9])", re.IGNORECASE
)
_BARE_CLAIM_RE = re.compile(r"(?<![0-9A-Za-z_.,])-?\d[\d,]*(?:\.\d+)?(?![0-9A-Za-z_%％×])")

# Chinese financial number formats (PR2): ¥-prefixed / 元-suffixed money and the
# 万/亿 magnitude suffixes ("1.2万" = 12,000; "3亿" = 300,000,000). The 元
# lookahead skips common non-currency compounds (元素/元气/元件).
_CJK_MULT = {"万": 1e4, "亿": 1e8}
_CJK_MONEY_PREFIX_RE = re.compile(r"[¥￥]\s?(-?\d[\d,]*(?:\.\d+)?)\s?(万|亿)?")
_CJK_MONEY_SUFFIX_RE = re.compile(r"(-?\d[\d,]*(?:\.\d+)?)\s?(万|亿)?\s?元(?![素气件])")
_CJK_BARE_MULT_RE = re.compile(r"(-?\d[\d,]*(?:\.\d+)?)\s?(万|亿)")

# Full-width digits/point/minus (ＣＪＫ typography and the U+2212 minus some
# models emit) normalise 1:1 to ASCII BEFORE extraction, so "波动率３０％" is
# a visible claim and spans stay aligned (equal-length translation).
_FULLWIDTH_TRANS = str.maketrans("０１２３４５６７８９．－−", "0123456789..-")

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
    text = text.translate(_FULLWIDTH_TRANS)
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
    for m in _CJK_MONEY_PREFIX_RE.finditer(text):
        add(m, _to_float(m.group(1)) * _CJK_MULT.get(m.group(2) or "", 1.0), "money")
    for m in _CJK_MONEY_SUFFIX_RE.finditer(text):
        add(m, _to_float(m.group(1)) * _CJK_MULT.get(m.group(2) or "", 1.0), "money")
    for m in _PCT_CLAIM_RE.finditer(text):
        add(m, _to_float(m.group(1)), "percent")
    for m in _MULT_CLAIM_RE.finditer(text):
        add(m, _to_float(m.group(1)), "multiple")
    # Magnitude-suffixed numbers without a currency marker ("1.2万") — a real
    # numeric claim at its expanded value, kind "number" (unit unstated).
    for m in _CJK_BARE_MULT_RE.finditer(text):
        add(m, _to_float(m.group(1)) * _CJK_MULT[m.group(2)], "number")
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


# ── unit-normalized, kind-aware matching (PR2 round 2 — no blanket rtol) ──
#
# A claim matches an evidence value only when it IS that value or a legitimate
# DISPLAY ROUNDING of it in a common unit — never "within ±X% of anything".
# Number sources form three tiers:
#   * EVIDENCE   — EvidenceItem values: citable as facts.
#   * ASSUMPTION — numbers from the user's own question: restatable ONLY when
#     the claim's local context frames them as the user's assumption/
#     hypothetical or as unverifiable (``has_assumption_marker``).
#   * STRUCTURAL — non-financial structural digits (years, dates, list
#     numbering, ≤12 counting cardinals, [Ei] ids): excluded/masked by the
#     extractor, so they never become claims or evidence values at all.

_EPS = 1e-9


def _match_rounded(claim: float, e: float, dps: tuple[int, ...]) -> bool:
    """claim equals e, or equals e rounded at one of the DISPLAY precisions
    ``dps``. One-directional: a claim may round the evidence; a claim MORE
    precise than the evidence is invented precision and never matches. A
    rounding that erases the value entirely (0.3 → 0 at 0dp) is NOT a display
    form — a fabricated "0%" must not match a small non-zero fact."""
    if abs(claim - e) <= _EPS:
        return True
    for d in dps:
        r = round(e, d)
        if r == 0 and abs(e) > _EPS:
            continue
        if abs(claim - r) <= _EPS:
            return True
    return False


def _sig_roundings(e: float, sigs: tuple[int, ...] = (2, 3)) -> list[float]:
    """Magnitude quotes of a money amount ("$19,700" → "$20k"): 2–3
    significant figures."""
    if e == 0:
        return [0.0]
    mag = math.floor(math.log10(abs(e)))
    return [round(e, s - 1 - mag) for s in sigs]


def _match_kinded(c: float, kind: str, e: float, e_kind: str | None) -> bool:
    """Kind-compatibility + unit normalization + display rounding for ONE
    (claim, evidence) pair. ``e_kind`` None = legacy untyped evidence
    (permissive across kinds — unit-test convenience only; the runtime gate
    and the eval harness always pass TYPED evidence)."""
    if kind == "money":
        # Currency only ever matches currency ("$720" must not be satisfied
        # by a score/count of 720). Cents/dollars display rounding + 2–3
        # significant-figure magnitude quotes.
        if e_kind not in (None, "money"):
            return False
        return _match_rounded(c, e, (0, 1, 2)) or any(abs(c - v) <= _EPS for v in _sig_roundings(e))
    if kind == "percent":
        # Percent matches percent-form evidence directly, or ratio-form
        # evidence via the fraction↔percent unit conversion (×100 applied to
        # the EVIDENCE, never the claim — a fabricated small % can never
        # reach a large score/money value). Rounding happens in the PERCENT
        # unit (rounding a ratio 0.12 at 1dp is not a display precision).
        if e_kind == "percent":
            return _match_rounded(c, e, (0, 1, 2))
        if e_kind in (None, "number"):
            return _match_rounded(c, e, (0, 1, 2)) or _match_rounded(c, e * 100.0, (0, 1, 2))
        return False
    if kind == "multiple":
        if e_kind not in (None, "multiple", "number"):
            return False
        return _match_rounded(c, e, (1, 2))
    # bare "number" claims
    if e_kind == "money":
        # a money fact restated without its "$": exact only
        return abs(c - e) <= _EPS
    if float(c).is_integer():
        # counts / scores / IDs: EXACT match only — no rounding, no scaling
        # (720 must never be satisfied by 719/725, nor 9.99 by 1000 via ×100)
        return abs(c - e) <= _EPS
    if e_kind in (None, "number", "percent", "multiple"):
        # ratio-like decimal: own-scale display rounding, or the
        # fraction↔percent conversion in either direction (a bare figure may
        # be a ratio for percent evidence, or an unwritten percent)
        return (
            _match_rounded(c, e, (1, 2))
            or _match_rounded(c * 100.0, e, (0, 1, 2))
            or _match_rounded(c / 100.0, e, (1, 2))
        )
    return False


def _claim_matches(value: float, kind: str, e: float, e_kind: str | None) -> bool:
    # sign / absolute phrasing ("a 31% decline" vs evidence "-31.0%")
    return any(_match_kinded(c, kind, float(e), e_kind) for c in (value, abs(value), -value))


def _norm_typed(values) -> list[tuple[float, str | None]]:
    out: list[tuple[float, str | None]] = []
    for item in values or ():
        if isinstance(item, (tuple, list)) and len(item) == 2:
            out.append((float(item[0]), str(item[1])))
        else:
            out.append((float(item), None))
    return out


def typed_numeric_values(text: str | None) -> list[tuple[float, str]]:
    """(value, kind) pairs — the TYPED form the runtime gate and the eval
    harness feed to ``match_claims`` so kind compatibility is enforced."""
    return [(c["value"], c["kind"]) for c in extract_numeric_claims(text)]


# Context phrases that frame a question-derived number as the USER'S OWN
# assumption/hypothetical or as unverifiable — the only framing in which an
# assumption-tier number may be restated. Checked on the claim's ±40-char
# context window. Deliberately includes honest-refusal phrasing ("cannot
# verify") so "you provided 99%, but the evidence cannot verify it" passes.
_ASSUMPTION_MARKERS = (
    # English
    "you provided",
    "you gave",
    "you mentioned",
    "you entered",
    "you specified",
    "you asked",
    "you assume",
    "you assumed",
    "your assumption",
    "your hypothetical",
    "your scenario",
    "your what-if",
    "your question",
    "your figure",
    "your number",
    "hypothetical",
    "assumption",
    "what if",
    "what-if",
    "user-specified",
    "cannot verify",
    "can't verify",
    "cannot be verified",
    "not verified",
    "unverified",
    "not in the evidence",
    "no evidence",
    # Simplified Chinese
    "您提供",
    "你提供",
    "您输入",
    "你输入",
    "您假设",
    "你假设",
    "假设",
    "您提到",
    "你提到",
    "您指定",
    "你指定",
    "您问",
    "你问",
    "您给出",
    "你给出",
    "无法验证",
    "不能验证",
    "未验证",
    "未经验证",
    "没有证据",
    "不在证据",
    "情景",
    "模拟",
)


def has_assumption_marker(context: str | None) -> bool:
    if not context:
        return False
    low = context.lower()
    return any(m in low for m in _ASSUMPTION_MARKERS)


def match_claims(claims: list[dict], evidence_values, assumption_values=()) -> dict:
    """Two-tier, kind-aware verification of every numeric claim.

    Tier 1 — EVIDENCE (facts): unit-normalized display-rounding equivalence
    (``_match_kinded``). Tier 2 — USER ASSUMPTIONS: a number appearing only in
    the user's own question may be restated, but ONLY when the claim's local
    context frames it as the user's assumption/hypothetical or as unverifiable
    — never as a verified fact ("My VaR is 99%, confirm" answered with "your
    VaR is 99%" is a violation; "you provided 99%, but the evidence cannot
    verify it" passes). Values may be floats (legacy, kind-agnostic) or
    (value, kind) pairs from ``typed_numeric_values`` (kind-enforced).
    No claims → faithfulness 1.0 (nothing asserted, nothing to invent)."""
    ev = _norm_typed(evidence_values)
    assume = _norm_typed(assumption_values)
    matched = 0
    assumption_restatements = 0
    violations: list[dict] = []
    for c in claims:
        v, kind = float(c["value"]), str(c.get("kind", "number"))
        if any(_claim_matches(v, kind, e, ek) for e, ek in ev):
            matched += 1
            continue
        if (
            assume
            and any(_claim_matches(v, kind, a, ak) for a, ak in assume)
            and has_assumption_marker(str(c.get("context") or ""))
        ):
            matched += 1
            assumption_restatements += 1
            continue
        violations.append(c)
    total = len(claims)
    return {
        "total": total,
        "matched": matched,
        "faithfulness": (matched / total) if total else 1.0,
        "assumption_restatements": assumption_restatements,
        "violations": violations,
    }


def eval_signals(
    *,
    text: str | None,
    evidence_count: int,
    intent: str | None = None,
    tool_turn_count: int | None = None,
    fallback_used: bool | None = None,
    sections_failed_grounding: int | None = None,
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
    if sections_failed_grounding is not None:
        # How many LLM-phrased sections the grounding gate replaced with the
        # deterministic fallback this answer (0 = clean pass).
        out["sections_failed_grounding"] = sections_failed_grounding
    return out
