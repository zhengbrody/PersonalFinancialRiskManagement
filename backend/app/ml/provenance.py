"""Release gate + provenance record for a retrained regime artifact.

Used by .github/workflows/train-regime.yml, between "train" and "open a PR":

    python -m backend.app.ml.provenance gate   --out <gates.json>
    python -m backend.app.ml.provenance record --gates <gates.json> \
        --source-commit <sha> --run-id <id> --run-url <url> [--extra name=pass ...]

``gate`` is the release floor on the FRESHLY trained meta (it exits non-zero
when the model is below it, so nothing is proposed). ``record`` writes
``regime_provenance.json`` next to the artifacts: the commit the model was
trained from, the run that produced it, every gate result, and the sha256 of
each artifact. /api/v1/ml/health compares the serving model's bytes against
the recorded hash, so "production serves the approved artifact" is checkable
from the outside rather than assumed.

The gate thresholds are deliberately NOT ``holdout_accuracy >= baseline``: the
public model card says the model does not beat persistence on 4-class point
accuracy and that its value is probability ranking. That number is recorded
(informational) but never gates.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

ARTIFACT_DIR = Path(__file__).parent / "artifacts"
MODEL_PATH = ARTIFACT_DIR / "regime_model.joblib"
META_PATH = ARTIFACT_DIR / "regime_meta.json"
REFERENCE_PATH = ARTIFACT_DIR / "regime_reference.json"
PROVENANCE_PATH = ARTIFACT_DIR / "regime_provenance.json"

# The release floor. Unchanged from the inline gate it replaces.
MIN_ELEVATED_RISK_AUC = 0.70
MIN_HOLDOUT_SIZE = 500


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def quality_gate(meta: dict[str, Any]) -> dict[str, Any]:
    """Evaluate the release floor on a meta dict. Missing metrics FAIL (a
    malformed meta must never be proposed as a release)."""
    m = meta.get("metrics") or {}
    auc = m.get("elevated_risk_auc")
    size = m.get("holdout_size")
    checks = {
        f"elevated_risk_auc >= {MIN_ELEVATED_RISK_AUC}": (
            isinstance(auc, (int, float)) and auc >= MIN_ELEVATED_RISK_AUC
        ),
        f"holdout_size >= {MIN_HOLDOUT_SIZE}": (
            isinstance(size, (int, float)) and size >= MIN_HOLDOUT_SIZE
        ),
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "observed": {"elevated_risk_auc": auc, "holdout_size": size},
        "informational": {
            "holdout_accuracy": m.get("holdout_accuracy"),
            "baseline_accuracy": m.get("baseline_accuracy"),
        },
    }


def build_provenance(
    *,
    gates: dict[str, Any],
    source_commit: str,
    run_id: Optional[str],
    run_url: Optional[str],
    extra_gates: Optional[dict[str, bool]] = None,
    model_path: Path = MODEL_PATH,
    meta_path: Path = META_PATH,
    reference_path: Path = REFERENCE_PATH,
) -> dict[str, Any]:
    meta = json.loads(meta_path.read_text())
    checks = dict(gates.get("checks") or {})
    for name, passed in (extra_gates or {}).items():
        checks[name] = bool(passed)
    return {
        "schema": 1,
        "model_version": meta.get("model_version"),
        "trained_at": meta.get("trained_at"),
        "source_commit": source_commit,
        "run_id": run_id,
        "run_url": run_url,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "gates": {
            "passed": bool(gates.get("passed")) and all(checks.values()),
            "checks": checks,
            "observed": gates.get("observed") or {},
            "informational": gates.get("informational") or {},
        },
        "artifacts": {
            model_path.name: sha256_file(model_path),
            meta_path.name: sha256_file(meta_path),
            reference_path.name: sha256_file(reference_path),
        },
    }


def _parse_extra(items: list[str]) -> dict[str, bool]:
    out: dict[str, bool] = {}
    for item in items:
        name, _, value = item.partition("=")
        if not name or value not in ("pass", "fail"):
            raise SystemExit(f"--extra must be name=pass|fail, got {item!r}")
        out[name] = value == "pass"
    return out


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("gate")
    g.add_argument("--out", required=True)
    r = sub.add_parser("record")
    r.add_argument("--gates", required=True)
    r.add_argument("--source-commit", required=True)
    r.add_argument("--run-id", default=None)
    r.add_argument("--run-url", default=None)
    r.add_argument("--extra", action="append", default=[])
    args = parser.parse_args(argv)

    if args.cmd == "gate":
        result = quality_gate(json.loads(META_PATH.read_text()))
        Path(args.out).write_text(json.dumps(result, indent=2))
        for name, passed in result["checks"].items():
            print(("PASS  " if passed else "FAIL  ") + name)
        print(f"  observed={result['observed']}  informational={result['informational']}")
        if not result["passed"]:
            print("::error::freshly trained model is below the release floor — NOT proposing it")
            return 1
        return 0

    record = build_provenance(
        gates=json.loads(Path(args.gates).read_text()),
        source_commit=args.source_commit,
        run_id=args.run_id,
        run_url=args.run_url,
        extra_gates=_parse_extra(args.extra),
    )
    PROVENANCE_PATH.write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps(record["artifacts"], indent=2))
    if not record["gates"]["passed"]:
        print("::error::a recorded gate failed — NOT proposing this artifact")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
