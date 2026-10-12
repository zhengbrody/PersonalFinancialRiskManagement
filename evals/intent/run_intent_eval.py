"""Offline intent-routing eval: current deterministic classifier vs (optional) Jev.

Gold labels in evals/intent/cases.jsonl are PROVISIONAL human labels (written
by the research engineer, pending owner review) over the router's closed
intent set. See docs/jev-intent-experiment.md for the labelling rules.

    python evals/intent/run_intent_eval.py            # current classifier only
    python evals/intent/run_intent_eval.py --jev      # also Jev, IF a key exists
    python evals/intent/run_intent_eval.py --json out.json

With no ``TYPESAFE_API_KEY`` the Jev column is reported as
"not run — no key". Results are never mocked or estimated.

Calibration: Jev's own ``confidence`` is NOT used as a threshold by fiat.
When Jev runs, the report bins its confidence against correctness on THIS
gold set (reliability) and picks the lowest confidence cut-off whose accepted
subset has a Wilson 95% LOWER bound on accuracy >= --target-precision; below
the cut-off the deterministic classifier stays authoritative.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.app.services import copilot_router, jev_intent  # noqa: E402

CASES = Path(__file__).with_name("cases.jsonl")
LABELS = sorted(jev_intent.INTENT_LABELS)


def load_cases(path: Path = CASES) -> list[dict]:
    cases = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    for c in cases:
        if c["gold"] not in jev_intent.INTENT_LABELS:
            raise SystemExit(f"{c['id']}: gold {c['gold']!r} not in closed label set")
    return cases


def current_label(question: str) -> str:
    return copilot_router.classify(question, copilot_router.extract_tickers(question))


def metrics(pairs: list[tuple[str, str]]) -> dict:
    """pairs = [(gold, pred)]; pred may be None (abstain)."""
    n = len(pairs)
    correct = sum(1 for g, p in pairs if g == p)
    per_class = {}
    for lab in LABELS:
        tp = sum(1 for g, p in pairs if g == lab and p == lab)
        fp = sum(1 for g, p in pairs if g != lab and p == lab)
        fn = sum(1 for g, p in pairs if g == lab and p != lab)
        prec = tp / (tp + fp) if tp + fp else None
        rec = tp / (tp + fn) if tp + fn else None
        per_class[lab] = {"support": tp + fn, "precision": prec, "recall": rec}
    confusion: dict[str, Counter] = defaultdict(Counter)
    for g, p in pairs:
        confusion[g][p or "<none>"] += 1
    return {
        "n": n,
        "correct": correct,
        "accuracy": correct / n if n else None,
        "abstained": sum(1 for _, p in pairs if p is None),
        "per_class": per_class,
        "confusion": {g: dict(c) for g, c in confusion.items()},
    }


def wilson_lower(k: int, n: int, z: float = 1.96) -> float:
    if n == 0:
        return 0.0
    p = k / n
    den = 1 + z * z / n
    centre = p + z * z / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (centre - margin) / den


def reliability(records: list[tuple[float, bool]], bins: int = 5) -> list[dict]:
    out = []
    for b in range(bins):
        lo, hi = b / bins, (b + 1) / bins
        rows = [ok for c, ok in records if (lo <= c < hi) or (b == bins - 1 and c == 1.0)]
        out.append(
            {
                "bin": f"[{lo:.1f},{hi:.1f}{']' if b == bins - 1 else ')'}",
                "n": len(rows),
                "accuracy": (sum(rows) / len(rows)) if rows else None,
            }
        )
    return out


def choose_threshold(records: list[tuple[float, bool]], target: float) -> dict:
    """Lowest cut-off whose accepted subset's Wilson-95 lower bound >= target."""
    for cut in sorted({c for c, _ in records}):
        acc = [ok for c, ok in records if c >= cut]
        lb = wilson_lower(sum(acc), len(acc))
        if lb >= target:
            return {
                "threshold": cut,
                "accepted": len(acc),
                "coverage": len(acc) / len(records),
                "accepted_accuracy": sum(acc) / len(acc),
                "wilson95_lower": lb,
            }
    return {"threshold": None, "reason": "no cut-off reaches the target on this set"}


def _fmt(x):
    return "  -  " if x is None else f"{x:.3f}"


def print_block(title: str, m: dict) -> None:
    print(f"\n== {title} ==")
    print(f"n={m['n']}  accuracy={_fmt(m['accuracy'])}  abstained={m['abstained']}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jev", action="store_true", help="also query Jev if a key is set")
    ap.add_argument("--json", type=Path, help="write a machine-readable report")
    ap.add_argument("--target-precision", type=float, default=0.90)
    args = ap.parse_args(argv)

    cases = load_cases()
    for c in cases:
        c["current"] = current_label(c["question"])

    report: dict = {"cases": len(cases), "current": {}, "jev": None}
    subsets = {
        "overall": cases,
        "ambiguous": [c for c in cases if c["ambiguous"]],
        "clear": [c for c in cases if not c["ambiguous"]],
        "en": [c for c in cases if c["lang"] == "en"],
        "zh": [c for c in cases if c["lang"] == "zh"],
    }
    for name, rows in subsets.items():
        m = metrics([(c["gold"], c["current"]) for c in rows])
        report["current"][name] = m
        print_block(f"current classifier — {name}", m)

    print("\nper-class (overall, current):")
    for lab, pc in report["current"]["overall"]["per_class"].items():
        print(
            f"  {lab:22s} support={pc['support']:3d}  P={_fmt(pc['precision'])}  R={_fmt(pc['recall'])}"
        )

    print("\nambiguous-subset confusion (gold -> predicted, current):")
    for g, row in sorted(report["current"]["ambiguous"]["confusion"].items()):
        print(f"  {g:22s} {dict(sorted(row.items(), key=lambda kv: -kv[1]))}")
    misses = [c for c in subsets["ambiguous"] if c["current"] != c["gold"]]
    report["current"]["ambiguous_misses"] = [
        {"id": c["id"], "gold": c["gold"], "pred": c["current"]} for c in misses
    ]

    key = os.environ.get("TYPESAFE_API_KEY", "").strip()
    if not args.jev:
        report["jev"] = {"status": "not requested (pass --jev)"}
    elif not key:
        report["jev"] = {"status": "not run — no key"}
    else:
        settings = SimpleNamespace(jev_intent_enabled=True, typesafe_api_key=key)
        jev_intent.reset_budget_for_tests(per_minute=len(cases), per_hour=len(cases))
        recs = []
        models = Counter()
        lat = []
        for c in cases:
            r = jev_intent.classify_intent(c["question"], settings=settings)
            c["jev"] = r.label if r else None
            c["jev_conf"] = r.confidence if r else None
            if r:
                recs.append((r.confidence, r.label == c["gold"]))
                models[r.model] += 1
                lat.append(r.latency_ms)
        jev_rep = {"status": "run", "models": dict(models)}
        for name, rows in subsets.items():
            jev_rep[name] = metrics([(c["gold"], c.get("jev")) for c in rows])
            print_block(f"jev — {name}", jev_rep[name])
        if lat:
            lat.sort()
            jev_rep["latency_ms"] = {
                "p50": lat[len(lat) // 2],
                "p95": lat[int(len(lat) * 0.95) - 1],
            }
        jev_rep["reliability"] = reliability(recs)
        jev_rep["threshold"] = choose_threshold(recs, args.target_precision)
        # Shadow policy: Jev only where it clears the eval-derived cut-off.
        cut = jev_rep["threshold"].get("threshold")
        hybrid = []
        for c in cases:
            use_jev = cut is not None and c.get("jev") and c["jev_conf"] >= cut
            hybrid.append((c["gold"], c["jev"] if use_jev else c["current"]))
        jev_rep["hybrid_overall"] = metrics(hybrid)
        print_block(
            "hybrid (jev above eval-derived cut-off, else current)", jev_rep["hybrid_overall"]
        )
        print("reliability:", jev_rep["reliability"])
        print("threshold:", jev_rep["threshold"])
        report["jev"] = jev_rep
    print(f"\nJev: {report['jev']['status']}")

    if args.json:
        args.json.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
