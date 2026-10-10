"""Classify the daily ML health probe into independent alert kinds.

Used by .github/workflows/ml-health.yml. Pure: takes the /api/v1/ml/health
response body (or nothing, when the probe failed) and the latest COMPLETED
train-regime run, and prints one JSON object

    {"<kind>": {"state": "firing"|"ok"|"unknown", "title": ..., "detail": ...}}

The workflow keeps ONE open issue per kind: firing → open or comment;
ok → close the open issue with a recovery comment; unknown → leave alone (a
kind we cannot judge today must neither page nor auto-resolve).

The serving box cannot know the training pipeline's outcome, so the pipeline
kind is judged here from the Actions API, not from the health payload.

    python scripts/ml_health_alerts.py --health health.json --train-run run.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Optional

TITLES = {
    # Kept identical to the pre-dedupe title so an already-open issue is reused.
    "drift": "ML drift monitor FAILED (/api/v1/ml/health)",
    "endpoint": "ML health endpoint unreachable (/api/v1/ml/health)",
    "freshness": "ML model is stale (/api/v1/ml/health freshness)",
    "artifact": "ML serving artifact does not match the approved hash",
    "train_pipeline": "Train regime model workflow failed",
}


def _kind(state: str, kind: str, detail: str) -> dict[str, str]:
    return {"state": state, "title": TITLES[kind], "detail": detail}


def classify(health: Optional[dict[str, Any]], train_run: Optional[dict[str, Any]]) -> dict:
    out: dict[str, dict[str, str]] = {}
    data = (health or {}).get("data") if isinstance(health, dict) else None

    if not isinstance(data, dict):
        out["endpoint"] = _kind("firing", "endpoint", "probe failed or envelope had no data")
        for k in ("drift", "freshness", "artifact"):
            out[k] = _kind("unknown", k, "endpoint unavailable")
    else:
        out["endpoint"] = _kind("ok", "endpoint", "endpoint answered")
        status, overall = data.get("status"), data.get("overall_status")
        if status == "ok" and overall == "drift":
            out["drift"] = _kind("firing", "drift", "overall_status=drift")
        elif status == "ok" and overall in ("healthy", "watch"):
            out["drift"] = _kind("ok", "drift", f"overall_status={overall}")
        else:
            out["drift"] = _kind("unknown", "drift", f"status={status} overall={overall}")

        fresh = data.get("freshness") or {}
        fstate = fresh.get("status")
        fdetail = (
            f"age_days={fresh.get('age_days')} threshold_days={fresh.get('threshold_days')} "
            f"trained_at={fresh.get('trained_at')}"
        )
        if fstate == "stale":
            out["freshness"] = _kind("firing", "freshness", fdetail)
        elif fstate == "fresh":
            out["freshness"] = _kind("ok", "freshness", fdetail)
        else:
            out["freshness"] = _kind("unknown", "freshness", fdetail)

        art = data.get("approved_artifact") or {}
        match = art.get("match")
        adetail = (
            f"loaded={art.get('loaded_sha256')} approved={art.get('approved_sha256')} "
            f"source={art.get('approved_source')}"
        )
        if match is False:
            out["artifact"] = _kind("firing", "artifact", adetail)
        elif match is True:
            out["artifact"] = _kind("ok", "artifact", adetail)
        else:
            out["artifact"] = _kind("unknown", "artifact", adetail)

    if not isinstance(train_run, dict) or not train_run.get("conclusion"):
        out["train_pipeline"] = _kind("unknown", "train_pipeline", "no completed run found")
    else:
        conclusion = train_run["conclusion"]
        detail = f"latest completed run: {conclusion} {train_run.get('url', '')}".strip()
        state = "ok" if conclusion == "success" else "firing"
        out["train_pipeline"] = _kind(state, "train_pipeline", detail)
    return out


def _load(path: Optional[str]) -> Optional[Any]:
    if not path:
        return None
    try:
        text = Path(path).read_text().strip()
        return json.loads(text) if text else None
    except (OSError, ValueError):
        return None


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--health")
    parser.add_argument("--train-run")
    args = parser.parse_args(argv)
    train = _load(args.train_run)
    if isinstance(train, list):  # `gh run list --json` returns a list
        train = train[0] if train else None
    print(json.dumps(classify(_load(args.health), train)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
