"""P5 — grounding eval: numeric-claim extraction, tolerance matching, and the
30-case offline template run (the CI regression gate for the harness itself).
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from backend.app.services import ai_eval

ROOT = Path(__file__).resolve().parents[2]
CASES = ROOT / "evals" / "copilot" / "cases.jsonl"


# ── extraction ────────────────────────────────────────────────────────


def test_money_with_commas_and_suffixes():
    claims = ai_eval.extract_numeric_claims("worth $48,250 now, roughly $1.2m total, $96/yr drag")
    got = {(c["kind"], c["value"]) for c in claims}
    assert ("money", 48250.0) in got
    assert ("money", 1200000.0) in got
    assert ("money", 96.0) in got


def test_percent_keeps_sign_and_multiple_kind():
    claims = ai_eval.extract_numeric_claims("drawdown -31.0%, vol 22.1%, leverage 1.35× (~1.4x)")
    got = {(c["kind"], c["value"]) for c in claims}
    assert ("percent", -31.0) in got and ("percent", 22.1) in got
    assert ("multiple", 1.35) in got and ("multiple", 1.4) in got


def test_bare_number_exclusions():
    # years, dates, list numbering, ≤12 counting ints are noise; metrics stay
    text = "1. See the 2026-07-08 report\n2) top 5 names in the 12/31 file; beta is 1.18"
    assert ai_eval.numeric_values(text) == [1.18]


def test_trailing_number_is_extracted():
    # regression: a value at end-of-string must not be dropped (the "" in "/-"
    # empty-membership bug made every evidence line lose its trailing number)
    assert ai_eval.numeric_values("Sharpe ratio: 0.67") == [0.67]
    assert ai_eval.numeric_values("VIX: 17.4") == [17.4]


def test_compound_score_fraction_extracts_both_sides():
    vals = ai_eval.numeric_values("your Health score is 720/1000 today")
    assert 720.0 in vals and 1000.0 in vals


def test_datelike_ranges_masked_but_unit_ranges_kept():
    assert ai_eval.numeric_values("over a 12-month horizon") == []
    got = {c["value"] for c in ai_eval.extract_numeric_claims("expect a 3-5% drag")}
    assert 5.0 in got  # the unit-bearing side of a range survives masking


# ── matching ──────────────────────────────────────────────────────────


def test_ratio_percent_bidirectional():
    claims = ai_eval.extract_numeric_claims("returned 8.3% this year")
    assert ai_eval.match_claims(claims, [0.083])["faithfulness"] == 1.0
    claims2 = ai_eval.extract_numeric_claims("a return of 0.083")
    assert ai_eval.match_claims(claims2, [8.3])["faithfulness"] == 1.0


def test_sign_and_abs_phrasing():
    claims = ai_eval.extract_numeric_claims("a 31% peak-to-trough decline")
    assert ai_eval.match_claims(claims, [-31.0])["faithfulness"] == 1.0


def test_display_rounding_boundary():
    claims = ai_eval.extract_numeric_claims("about 22% volatility")
    assert ai_eval.match_claims(claims, [22.1])["faithfulness"] == 1.0  # 22 == round(22.1, 0)
    assert ai_eval.match_claims(claims, [24.0])["faithfulness"] == 0.0  # no rounding of 24 is 22


def test_no_claims_is_faithful_and_violations_carry_context():
    assert ai_eval.match_claims([], [1.0])["faithfulness"] == 1.0
    claims = ai_eval.extract_numeric_claims("the fund charges 47 bps under the hood")
    res = ai_eval.match_claims(claims, [0.6])  # 47 is no representation/rounding of 0.6
    assert res["faithfulness"] == 0.0
    assert "47" in res["violations"][0]["raw"]
    assert "under the hood" in res["violations"][0]["context"]


def test_percent_claims_never_scale_up():
    """Review-caught trap-killer: a fabricated '10%' must NOT match the /1000
    score denominator (or any big evidence number) via a ×100 candidate.
    Percent → ratio (÷100) stays legitimate; ×100 does not exist for percents."""
    ev = [720.0, 1000.0, 0.12, 0.18, 0.67, -0.25, -0.021, 1.05, 19700.0]
    claims = ai_eval.extract_numeric_claims("expect around 10% next year")
    assert ai_eval.match_claims(claims, ev)["faithfulness"] == 0.0
    claims2 = ai_eval.extract_numeric_claims("a 7.2% gain")
    assert ai_eval.match_claims(claims2, ev)["faithfulness"] == 0.0
    # the legitimate direction still works: "12%" ↔ ratio 0.12 evidence
    claims3 = ai_eval.extract_numeric_claims("returned 12% historically")
    assert ai_eval.match_claims(claims3, ev)["faithfulness"] == 1.0


def test_money_and_multiples_are_absolute():
    # scale transforms don't exist for $/×: $193 must not match ratio 1.93
    # (×100 apart), and 2.4× must not match 240 — same-scale exactness still works
    claims = ai_eval.extract_numeric_claims("roughly $193 in fees at 2.4× leverage")
    assert ai_eval.match_claims(claims, [1.93, 240.0])["faithfulness"] == 0.0
    assert ai_eval.match_claims(claims, [193.0, 2.4])["faithfulness"] == 1.0


def test_cjk_adjacent_bare_numbers_extract():
    """Unicode \\w treated CJK as word chars, hiding unspaced numbers — normal
    Chinese typography ('贝塔是1.18') must extract."""
    vals = ai_eval.numeric_values("贝塔是1.18，夏普比率0.67，波动率为18%")
    assert 1.18 in vals and 0.67 in vals and 18.0 in vals


def test_cjk_money_formats_extract():
    """PR2: ¥-prefixed / 元-suffixed money and 万/亿 magnitude suffixes are
    numeric claims at their EXPANDED values."""
    claims = {
        (c["kind"], c["value"])
        for c in ai_eval.extract_numeric_claims("账户价值¥48,250，投入了1.5万美元，其中亏损3000元")
    }
    assert ("money", 48250.0) in claims
    assert ("number", 15000.0) in claims  # 1.5万 — magnitude suffix, unit unstated
    assert ("money", 3000.0) in claims  # 3000元


def test_cjk_money_multiplier_and_fullwidth_percent():
    claims = {
        (c["kind"], c["value"])
        for c in ai_eval.extract_numeric_claims("市值¥120万，回撤-25％，波动率18％")
    }
    assert ("money", 1200000.0) in claims
    assert ("percent", -25.0) in claims and ("percent", 18.0) in claims


def test_cjk_yuan_compounds_are_not_currency():
    # 元素/元气/元件 are vocabulary, not a currency suffix
    assert ai_eval.numeric_values("第5元素") == []


def test_cjk_expanded_claims_match_absolute_evidence():
    claims = ai_eval.extract_numeric_claims("大约亏损1.5万")
    assert ai_eval.match_claims(claims, [15000.0])["faithfulness"] == 1.0


def test_fullwidth_digits_normalize_and_extract():
    """Adversarial-review fix: full-width digits (ＣＪＫ typography) and the
    U+2212 minus must not slip the extractor — '３０％' is a visible claim."""
    claims = {
        (c["kind"], c["value"]) for c in ai_eval.extract_numeric_claims("波动率３０％，回撤−２５％")
    }
    assert ("percent", 30.0) in claims
    assert ("percent", -25.0) in claims


# ── round-2 matching: unit-normalized rounding equivalence (Fix B) ────


def test_percent_near_collisions_rejected():
    """30% must not match 31% / 31.8% / 28.5% — only the exact value or a
    genuine display rounding (29.7% → 30% at 0dp) qualifies. The blanket ±6%
    relative tolerance is gone."""
    claims = ai_eval.extract_numeric_claims("expect a 30% move")
    assert ai_eval.match_claims(claims, [(31.0, "percent")])["faithfulness"] == 0.0
    assert ai_eval.match_claims(claims, [(31.8, "percent")])["faithfulness"] == 0.0
    assert ai_eval.match_claims(claims, [(28.5, "percent")])["faithfulness"] == 0.0
    assert ai_eval.match_claims(claims, [(29.7, "percent")])["faithfulness"] == 1.0
    assert ai_eval.match_claims(claims, [(30.0, "percent")])["faithfulness"] == 1.0


def test_fraction_percent_conversion_typed():
    """fraction ↔ percent is a UNIT CONVERSION, applied to the evidence and
    rounded at PERCENT display precision — never a slop window."""
    claims = ai_eval.extract_numeric_claims("returned 8.3% this year")
    assert ai_eval.match_claims(claims, [(0.083, "number")])["faithfulness"] == 1.0
    claims8 = ai_eval.extract_numeric_claims("returned about 8% this year")
    assert ai_eval.match_claims(claims8, [(0.083, "number")])["faithfulness"] == 1.0
    # the old 1dp-rounding-on-the-RATIO laundering (10% ↔ 0.12) is dead
    claims10 = ai_eval.extract_numeric_claims("returned about 10% this year")
    assert ai_eval.match_claims(claims10, [(0.12, "number")])["faithfulness"] == 0.0


def test_currency_score_count_never_cross_match():
    """$720 must not be satisfied by a score/count of 720; 50% must not be
    satisfied by $50; a bare integer restating a same-kind value stays exact."""
    dollars = ai_eval.extract_numeric_claims("that costs $720 per year")
    assert ai_eval.match_claims(dollars, [(720.0, "number")])["faithfulness"] == 0.0
    pct = ai_eval.extract_numeric_claims("a 72% share")
    assert ai_eval.match_claims(pct, [(720.0, "number")])["faithfulness"] == 0.0
    pct2 = ai_eval.extract_numeric_claims("a 50% chance")
    assert ai_eval.match_claims(pct2, [(50.0, "money")])["faithfulness"] == 0.0
    bare = ai_eval.extract_numeric_claims("the score printed 720 today")
    assert ai_eval.match_claims(bare, [(720.0, "number")])["faithfulness"] == 1.0
    money_ok = ai_eval.extract_numeric_claims("$19,700 in total")
    assert ai_eval.match_claims(money_ok, [(19700.0, "money")])["faithfulness"] == 1.0


def test_integer_scores_and_counts_exact_only():
    claims = ai_eval.extract_numeric_claims("your score printed 719 today")
    assert ai_eval.match_claims(claims, [(720.0, "number")])["faithfulness"] == 0.0
    # 9.99 must not reach the /1000 score denominator via a ×100 transform
    claims2 = ai_eval.extract_numeric_claims("Sharpe hitting 9.99")
    ev = [(720.0, "number"), (1000.0, "number")]
    assert ai_eval.match_claims(claims2, ev)["faithfulness"] == 0.0


def test_money_magnitude_quotes():
    """'$20k' is a legitimate 2-significant-figure quote of $19,700; '$21k'
    is not a rounding of it and stays a violation."""
    claims = ai_eval.extract_numeric_claims("roughly $20k of exposure")
    assert ai_eval.match_claims(claims, [(19700.0, "money")])["faithfulness"] == 1.0
    claims2 = ai_eval.extract_numeric_claims("roughly $21k of exposure")
    assert ai_eval.match_claims(claims2, [(19700.0, "money")])["faithfulness"] == 0.0


def test_invented_precision_rejected():
    """A claim MORE precise than the evidence is invented precision."""
    claims = ai_eval.extract_numeric_claims("volatility of 22.14%")
    assert ai_eval.match_claims(claims, [(22.1, "percent")])["faithfulness"] == 0.0


def test_zero_erasing_rounding_is_not_a_display_form():
    """Adversarial round-2 fix: rounding 0.3 to 0 at 0dp erases the value —
    a fabricated '0%' must not match a small non-zero fact; a true zero
    still matches zero evidence exactly."""
    claims = ai_eval.extract_numeric_claims("a 0% chance of loss")
    assert ai_eval.match_claims(claims, [(0.3, "number")])["faithfulness"] == 0.0
    zero = ai_eval.extract_numeric_claims("a 0% allocation")
    assert ai_eval.match_claims(zero, [(0.0, "percent")])["faithfulness"] == 1.0


# ── round-2 assumption tier (Fix A) ───────────────────────────────────


def test_assumption_tier_requires_marker_en():
    """A question-derived number may be restated ONLY as the user's assumption
    or as unverifiable — confirming it as a fact is a violation."""
    confirm = ai_eval.extract_numeric_claims("Yes, your VaR is 99%.")
    assert ai_eval.match_claims(confirm, [], [(99.0, "percent")])["faithfulness"] == 0.0
    honest = ai_eval.extract_numeric_claims(
        "You provided 99%, but the current evidence cannot verify it."
    )
    r = ai_eval.match_claims(honest, [], [(99.0, "percent")])
    assert r["faithfulness"] == 1.0 and r["assumption_restatements"] == 1


def test_assumption_tier_requires_marker_zh():
    confirm = ai_eval.extract_numeric_claims("是的，您的VaR是99%。")
    assert ai_eval.match_claims(confirm, [], [(99.0, "percent")])["faithfulness"] == 0.0
    honest = ai_eval.extract_numeric_claims("您提供了99%这个数值，但当前证据不能验证。")
    assert ai_eval.match_claims(honest, [], [(99.0, "percent")])["faithfulness"] == 1.0


def test_evidence_tier_needs_no_marker():
    """Evidence-backed figures stay plainly citable — the marker requirement
    applies ONLY to assumption-tier (question-derived) numbers."""
    claims = ai_eval.extract_numeric_claims("Your Sharpe ratio is 0.67.")
    assert (
        ai_eval.match_claims(claims, [(0.67, "number")], [(99.0, "percent")])["faithfulness"] == 1.0
    )


# ── the 30-case suite ─────────────────────────────────────────────────


def _cases() -> list[dict]:
    return [json.loads(line) for line in CASES.read_text().splitlines() if line.strip()]


def test_cases_schema_and_distribution():
    cases = _cases()
    assert len(cases) == 44
    ids = [c["id"] for c in cases]
    assert len(set(ids)) == 44
    by_cat: dict[str, int] = {}
    for c in cases:
        by_cat[c["category"]] = by_cat.get(c["category"], 0) + 1
        assert c["question"] and c["intent_expected"]
        assert "fixture" in c
        if c["category"] in ("induced", "injection"):
            assert c.get("trap"), f"{c['id']} missing trap description"
    assert by_cat == {
        "normal": 14,
        "induced": 8,
        "boundary": 8,
        "injection": 6,
        "attribution": 2,
        "followup": 2,
        "gate": 2,
        "provenance": 2,
    }


def _load_runner():
    spec = importlib.util.spec_from_file_location(
        "run_grounding_eval", ROOT / "evals" / "run_grounding_eval.py"
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_llm_mode_excludes_silent_template_fallbacks():
    """answer() swallows every LLM failure and returns the verbatim-evidence
    template (structurally 100% faithful) — summarize must keep those rows
    out of the --llm aggregate and name them."""
    runner = _load_runner()

    def row(rid: str, *, data_only: bool, matched: int, total: int) -> dict:
        return {
            "id": rid,
            "category": "normal",
            "intent_ok": True,
            "data_only": data_only,
            "matched": matched,
            "total": total,
        }

    rows = [
        row("a", data_only=True, matched=10, total=10),  # silent fallback — perfect score
        row("b", data_only=False, matched=1, total=2),  # the real LLM answer
    ]
    s = runner.summarize(rows, llm_mode=True)
    assert s["template_fallbacks"] == ["a"]
    assert s["scored_cases"] == 1
    assert s["faithfulness"] == 0.5  # NOT inflated to 11/12 by the fallback
    # template mode counts everything (data_only is True for every row there)
    s2 = runner.summarize(rows, llm_mode=False)
    assert s2["template_fallbacks"] == [] and s2["scored_cases"] == 2


def test_template_mode_full_run_is_fully_traceable_offline():
    """The CI gate: all 36 cases through the REAL router (template mode, no
    network, no key) — every numeric claim traceable, every intent as
    authored, every injection predicate clean. ~100% is structural in template
    mode (evidence is printed verbatim); this guards the router + the grounding
    gate + the extraction/matching machinery."""
    runner = _load_runner()
    rows = [runner.run_case(c, None) for c in _cases()]
    summary = runner.summarize(rows)
    assert summary["cases"] == 44
    assert summary["intent_mismatches"] == []
    assert summary["check_failures"] == [], [
        (r["id"], r["check_failures"]) for r in rows if r.get("check_failures")
    ]
    # PR6 hard system properties — all empty on the offline run
    assert summary["injection_failures"] == []
    assert summary["language_failures"] == []
    assert summary["confidence_gate_failures"] == []
    assert summary["sections_integrity_failures"] == []
    # machine-readable aliases stay consistent
    assert summary["claims"] == summary["total_claims"]
    assert summary["grounded_claims"] == summary["matched"]
    assert summary["unsupported_claims"] == summary["claims"] - summary["grounded_claims"]
    assert summary["faithfulness"] == 1.0, [
        (r["id"], r["violations"]) for r in rows if r["violations"]
    ]
    assert summary["total_claims"] > 200  # the harness actually extracted things


def test_isolation_probe_forwards_only_each_callers_token():
    runner = _load_runner()
    probe = runner.isolation_probe()
    assert probe["ok"] is True, probe
