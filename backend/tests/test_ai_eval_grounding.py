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


def test_rtol_boundary():
    claims = ai_eval.extract_numeric_claims("about 22% volatility")
    assert ai_eval.match_claims(claims, [22.1])["faithfulness"] == 1.0  # 0.45% off
    assert ai_eval.match_claims(claims, [24.0])["faithfulness"] == 0.0  # 8.3% off


def test_no_claims_is_faithful_and_violations_carry_context():
    assert ai_eval.match_claims([], [1.0])["faithfulness"] == 1.0
    claims = ai_eval.extract_numeric_claims("the fund charges 47 bps under the hood")
    res = ai_eval.match_claims(claims, [0.6])  # 0.47 vs 0.6 is well past rtol
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
    # (×100 apart), and 2.4× must not match 240 — same-scale rtol still works
    claims = ai_eval.extract_numeric_claims("roughly $193 in fees at 2.4× leverage")
    assert ai_eval.match_claims(claims, [1.93, 240.0])["faithfulness"] == 0.0
    assert ai_eval.match_claims(claims, [193.0, 2.4])["faithfulness"] == 1.0


def test_cjk_adjacent_bare_numbers_extract():
    """Unicode \\w treated CJK as word chars, hiding unspaced numbers — normal
    Chinese typography ('贝塔是1.18') must extract."""
    vals = ai_eval.numeric_values("贝塔是1.18，夏普比率0.67，波动率为18%")
    assert 1.18 in vals and 0.67 in vals and 18.0 in vals


# ── the 30-case suite ─────────────────────────────────────────────────


def _cases() -> list[dict]:
    return [json.loads(line) for line in CASES.read_text().splitlines() if line.strip()]


def test_cases_schema_and_distribution():
    cases = _cases()
    assert len(cases) == 30
    ids = [c["id"] for c in cases]
    assert len(set(ids)) == 30
    by_cat: dict[str, int] = {}
    for c in cases:
        by_cat[c["category"]] = by_cat.get(c["category"], 0) + 1
        assert c["question"] and c["intent_expected"]
        assert "fixture" in c
        if c["category"] == "induced":
            assert c.get("trap"), f"{c['id']} missing trap description"
    assert by_cat == {"normal": 14, "induced": 8, "boundary": 8}


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
    """The CI gate: all 30 cases through the REAL router (template mode, no
    network, no key) — every numeric claim traceable, every intent as
    authored. ~100% is structural in template mode (evidence is printed
    verbatim); this guards the router + extraction/matching machinery."""
    runner = _load_runner()
    rows = [runner.run_case(c, None) for c in _cases()]
    summary = runner.summarize(rows)
    assert summary["cases"] == 30
    assert summary["intent_mismatches"] == []
    assert summary["faithfulness"] == 1.0, [
        (r["id"], r["violations"]) for r in rows if r["violations"]
    ]
    assert summary["total_claims"] > 200  # the harness actually extracted things
