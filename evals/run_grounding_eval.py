"""Copilot grounding eval — is every number in the answer traceable to evidence?

Runs the 30 cases in evals/copilot/cases.jsonl through the REAL router
(``copilot_router.answer``) with every evidence-source seam patched to the
case's fixture, extracts numeric claims from the answer, and tolerance-matches
them against the evidence packet (see ``ai_eval.extract_numeric_claims`` /
``match_claims``).

Modes
-----
default        deterministic template (llm_callable=None) — fully offline, no
               key, CI-runnable. HONEST FRAMING: the template prints evidence
               verbatim, so ~100% faithfulness here is a STRUCTURAL guarantee;
               the value is (a) a regression harness for the router + the
               extraction/matching machinery and (b) the measurement frame the
               live mode reuses.
--llm          real LLM via ANTHROPIC_API_KEY (services.llm_client) — the mode
               that produces a MEANINGFUL faithfulness number.

Exit codes: 0 ok · 1 faithfulness below --threshold or intent mismatch ·
2 setup error (cases unreadable, --llm without a key).
"""

from __future__ import annotations

import argparse
import json
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.services import ai_eval  # noqa: E402
from backend.app.services import copilot_router as cr  # noqa: E402
from backend.app.services import market_regime as mr  # noqa: E402
from backend.app.services import research_factpack as rf  # noqa: E402

CASES_PATH = ROOT / "evals" / "copilot" / "cases.jsonl"


# ── fixture → fake evidence sources ───────────────────────────────────


def _score_obj(d: dict):
    return SimpleNamespace(
        overall_score=d["overall_score"], metrics=SimpleNamespace(**d["metrics"])
    )


def _factpack_obj(ticker: str, d: dict):
    from backend.app.schemas import research as R

    return R.FactPack(
        ticker=ticker,
        price=d.get("price"),
        valuation=R.ValuationBlock(pe=d.get("pe"), band=d.get("band")),
        quality=R.QualityBlock(net_margin=d.get("net_margin"), roe=d.get("roe")),
        growth=R.GrowthBlock(revenue_cagr=d.get("revenue_cagr")),
        analyst=R.AnalystBlock(implied_upside_pct=d.get("implied_upside_pct")),
        drivers=d.get("drivers") or [],
        risk_flags=d.get("risk_flags") or [],
    )


@contextmanager
def patched_seams(fixture: dict):
    """Point every evidence-gathering seam at the case fixture; restore after.

    The subject under test is the ANSWER's faithfulness to evidence — the
    evidence builders themselves have their own unit tests, so patching at
    the source seams (the same ones the router's tests use) is the honest
    boundary. Desk-view/option evidence are pinned empty so the value set is
    exactly the fixture-derived packet."""
    fx = fixture or {}
    saved: dict[tuple, object] = {}

    def put(obj, name, val):
        saved[(id(obj), name)] = (obj, getattr(obj, name))
        setattr(obj, name, val)

    def no_portfolio(_user):
        raise RuntimeError("no active portfolio (fixture)")

    score_fx = fx.get("score")
    if score_fx:
        score = _score_obj(score_fx)
        put(cr, "_load_score_positions", lambda user, s=score: ([], s))
        put(cr, "_load_score", lambda user, s=score: s)
    else:
        put(cr, "_load_score_positions", no_portfolio)
        put(cr, "_load_score", no_portfolio)

    packs = fx.get("factpacks") or {}
    put(cr, "_institutional_evidence", lambda score, positions: [])
    put(cr, "_option_evidence", lambda message, user: [])
    put(cr, "_optimizer_scans", lambda score, positions: dict(fx.get("scans") or {}))
    put(rf, "build_fact_pack", lambda tk: _factpack_obj(tk, packs[tk]))

    macro = fx.get("macro")
    if macro:
        put(mr, "get_market_regime", lambda m=macro: dict(m))
    else:
        put(mr, "get_market_regime", lambda: (_ for _ in ()).throw(RuntimeError("no macro")))

    try:
        yield
    finally:
        for (_oid, name), (obj, original) in saved.items():
            setattr(obj, name, original)


# ── one case ──────────────────────────────────────────────────────────


def run_case(case: dict, llm_callable) -> dict:
    with patched_seams(case.get("fixture")):
        ans = cr.answer(case["question"], user=object(), llm_callable=llm_callable)

    evidence_values: list[float] = []
    for e in ans.evidence:
        evidence_values += ai_eval.numeric_values(f"{e.label}: {e.value}")
    evidence_values += ai_eval.numeric_values(case["question"])

    claims = ai_eval.extract_numeric_claims(ans.answer_markdown)
    result = ai_eval.match_claims(claims, evidence_values)
    return {
        "id": case["id"],
        "category": case["category"],
        "intent_expected": case["intent_expected"],
        "intent_actual": ans.intent,
        "intent_ok": ans.intent == case["intent_expected"],
        "evidence_count": len(ans.evidence),
        # answer() swallows EVERY llm_callable failure and falls back to the
        # verbatim-evidence template (structurally 100% faithful) — a live
        # run must not let those rows inflate the LLM's number.
        "data_only": bool(ans.data_only),
        "trap": case.get("trap"),
        **result,
        "violations": [
            {"raw": v["raw"], "kind": v["kind"], "context": v["context"]}
            for v in result["violations"]
        ],
    }


# ── report ────────────────────────────────────────────────────────────


def summarize(rows: list[dict], *, llm_mode: bool = False) -> dict:
    """Aggregate. In --llm mode, rows where the router silently fell back to
    the deterministic template (data_only=True) are EXCLUDED from the
    faithfulness aggregate — the template is structurally 100% faithful, so
    counting fallbacks would inflate the live-LLM number — and reported in
    ``template_fallbacks`` instead."""
    fallbacks = [r["id"] for r in rows if r.get("data_only")] if llm_mode else []
    scored = [r for r in rows if r["id"] not in set(fallbacks)]
    cats: dict[str, dict] = {}
    for r in scored:
        c = cats.setdefault(r["category"], {"cases": 0, "total": 0, "matched": 0})
        c["cases"] += 1
        c["total"] += r["total"]
        c["matched"] += r["matched"]
    for c in cats.values():
        c["faithfulness"] = (c["matched"] / c["total"]) if c["total"] else 1.0
    total = sum(r["total"] for r in scored)
    matched = sum(r["matched"] for r in scored)
    return {
        "categories": cats,
        "total_claims": total,
        "matched": matched,
        "faithfulness": (matched / total) if total else 1.0,
        "intent_mismatches": [r["id"] for r in rows if not r["intent_ok"]],
        "cases": len(rows),
        "scored_cases": len(scored),
        "template_fallbacks": fallbacks,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--llm", action="store_true", help="run the real LLM (needs API key)")
    ap.add_argument("--threshold", type=float, default=None, help="min faithfulness (exit 1 below)")
    ap.add_argument("--json", type=Path, default=None, help="write the full report to this path")
    args = ap.parse_args()
    threshold = args.threshold if args.threshold is not None else (0.0 if args.llm else 0.98)

    llm_callable = None
    if args.llm:
        from backend.app.services.llm_client import get_llm_callable

        llm_callable = get_llm_callable()
        if llm_callable is None:
            print("ERROR: --llm requested but no LLM key/provider is configured", file=sys.stderr)
            return 2

    try:
        cases = [json.loads(line) for line in CASES_PATH.read_text().splitlines() if line.strip()]
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: cannot read {CASES_PATH}: {exc}", file=sys.stderr)
        return 2

    rows = [run_case(c, llm_callable) for c in cases]
    s = summarize(rows, llm_mode=args.llm)

    mode = "LIVE LLM" if args.llm else "deterministic template (offline)"
    print(f"Copilot grounding eval — {len(rows)} cases, mode: {mode}")
    if args.llm and s["template_fallbacks"]:
        print(
            f"WARNING: {len(s['template_fallbacks'])} case(s) silently fell back to the"
            f" deterministic template (LLM call failed) and are EXCLUDED from the"
            f" aggregate: {', '.join(s['template_fallbacks'])}"
        )
        if s["scored_cases"] == 0:
            print("ERROR: every case fell back — nothing measured the LLM", file=sys.stderr)
            return 2
    if not args.llm:
        print(
            "NOTE: the template prints evidence verbatim — ~100% here is structural;"
            " it regression-guards the router + extraction/matching. Run --llm for a"
            " meaningful faithfulness number."
        )
    print(f"{'category':<10} {'cases':>5} {'claims':>7} {'matched':>8} {'faithfulness':>13}")
    for name in ("normal", "induced", "boundary"):
        c = s["categories"].get(name)
        if c:
            print(
                f"{name:<10} {c['cases']:>5} {c['total']:>7} {c['matched']:>8}"
                f" {c['faithfulness']:>12.1%}"
            )
    print(
        f"{'TOTAL':<10} {s['cases']:>5} {s['total_claims']:>7} {s['matched']:>8} {s['faithfulness']:>12.1%}"
    )

    for r in rows:
        for v in r["violations"]:
            trap = f"  [trap: {r['trap']}]" if r.get("trap") else ""
            print(f"VIOLATION {r['id']}: {v['raw']} ({v['kind']}) …{v['context']}…{trap}")
    if s["intent_mismatches"]:
        for r in rows:
            if not r["intent_ok"]:
                print(
                    f"INTENT MISMATCH {r['id']}: expected {r['intent_expected']}, got {r['intent_actual']}"
                )

    if args.json:
        args.json.write_text(json.dumps({"summary": s, "rows": rows}, indent=2))
        print(f"report written: {args.json}")

    if s["intent_mismatches"] and not args.llm:
        return 1
    return 0 if s["faithfulness"] >= threshold else 1


if __name__ == "__main__":
    raise SystemExit(main())
