"""Shape guards for the provisional intent eval set and its runner."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from backend.app.services import jev_intent

ROOT = Path(__file__).resolve().parents[2]
CASES = ROOT / "evals" / "intent" / "cases.jsonl"


def _load_runner():
    spec = importlib.util.spec_from_file_location(
        "run_intent_eval", ROOT / "evals" / "intent" / "run_intent_eval.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_eval_set_shape():
    rows = [json.loads(x) for x in CASES.read_text(encoding="utf-8").splitlines() if x]
    assert len(rows) >= 120
    assert sum(r["lang"] == "zh" for r in rows) >= 50
    assert sum(r["ambiguous"] for r in rows) >= 30
    assert len({r["id"] for r in rows}) == len(rows)
    assert len({r["question"] for r in rows}) == len(rows)
    for r in rows:
        assert r["gold"] in jev_intent.INTENT_LABELS, r["id"]
        assert r["notes"].strip(), r["id"]
    assert {r["gold"] for r in rows} == set(jev_intent.INTENT_LABELS)


def test_runner_never_fabricates_jev_results_without_a_key(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    runner = _load_runner()
    out = tmp_path / "r.json"
    assert runner.main(["--jev", "--json", str(out)]) == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["jev"] == {"status": "not run — no key"}
    assert report["current"]["overall"]["n"] == report["cases"]


def test_threshold_is_chosen_from_eval_reliability_not_raw_confidence():
    runner = _load_runner()
    # High raw confidence but wrong answers must NOT earn a threshold.
    assert runner.choose_threshold([(0.99, False)] * 20, 0.9)["threshold"] is None
    recs = [(0.95, True)] * 60 + [(0.5, False)] * 20
    t = runner.choose_threshold(recs, 0.9)
    assert t["threshold"] == 0.95 and t["accepted"] == 60
    assert t["wilson95_lower"] >= 0.9
