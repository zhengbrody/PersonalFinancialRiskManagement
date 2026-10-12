"""Run an allowlisted local verification matrix; never deploy or enable features.

Default is a plan (all executable checks skipped). Child output is suppressed so
provider tokens, JWTs and local development credentials cannot enter the report.
Supabase uses the existing exclusively owned, loopback-only acceptance harness.
"""

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Check:
    name: str
    command: tuple[str, ...]
    cwd: str = "."
    prerequisite: str | None = None
    timeout: int | None = 1200


def checks(python):
    return (
        Check(
            "backend",
            (
                python,
                "-m",
                "pytest",
                "backend/tests",
                "-q",
                "-o",
                "addopts=",
                "--cov=backend.app",
                "--cov-config=backend/.coveragerc",
                "--cov-fail-under=85",
            ),
        ),
        Check(
            "typing",
            (
                python,
                "-m",
                "mypy",
                "--config-file",
                "backend/mypy.ini",
                "backend/app/schemas",
                "backend/app/core",
            ),
        ),
        Check("format", (python, "-m", "black", "--check", ".")),
        Check("frontend", ("npm", "test", "--", "--reporter=dot"), "frontend", "npm"),
        Check("typescript", ("npx", "--no-install", "tsc", "--noEmit"), "frontend", "npx"),
        Check("lint", ("npm", "run", "lint"), "frontend", "npm"),
        Check("eval", (python, "evals/run_grounding_eval.py")),
        Check(
            "browser",
            (
                "npm",
                "run",
                "test:e2e",
                "--",
                "copilot-put.spec.ts",
                "copilot-funding.spec.ts",
                "--workers=1",
            ),
            "frontend",
            "npm",
        ),
        # No outer kill timeout: the owned harness must finish its finally cleanup.
        Check(
            "auth_migrations",
            (python, "scripts/run_comparison_supabase_acceptance.py"),
            prerequisite="supabase",
            timeout=None,
        ),
    )


def execute(check, runner=subprocess.run):
    if check.prerequisite and shutil.which(check.prerequisite) is None:
        return {
            "name": check.name,
            "status": "blocked",
            "reason": "Required local executable is unavailable.",
        }
    try:
        result = runner(
            check.command,
            cwd=ROOT / check.cwd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=check.timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {
            "name": check.name,
            "status": "blocked",
            "reason": "Local check could not finish; inspect the named check separately.",
        }
    return {
        "name": check.name,
        "status": "passed" if result.returncode == 0 else "blocked",
        "reason": (
            "Command succeeded (suite-level skips may remain)."
            if result.returncode == 0
            else "Command failed; inspect the named check separately."
        ),
    }


def main(argv=None):
    available = checks(sys.executable)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", nargs="+", choices=[item.name for item in available], default=[])
    parser.add_argument(
        "--soak-repeats",
        type=int,
        choices=range(1, 6),
        default=1,
        help="1–5 complete isolated Auth suites; bounded repetitions, not production soak certification",
    )
    args = parser.parse_args(argv)
    if args.soak_repeats > 1 and "auth_migrations" not in args.run:
        parser.error("--soak-repeats requires --run auth_migrations")
    results = []
    for check in available:
        if check.name not in args.run:
            results.append({"name": check.name, "status": "skipped", "reason": "Not selected."})
            continue
        count = args.soak_repeats if check.name == "auth_migrations" else 1
        for index in range(count):
            result = execute(check)
            result["iteration"] = index + 1
            results.append(result)
            if result["status"] != "passed":
                break
    for name, reason in (
        (
            "release_pair",
            "Requires named old/new artifacts, shared-key continuity and actual rollback acceptance.",
        ),
        (
            "live_provider_latency",
            "Synthetic fixtures do not establish provider latency, quotas or market-session behavior.",
        ),
        (
            "broker_permissions",
            "Requires verified broker account permissions and rules; no broker orders are authorized here.",
        ),
    ):
        results.append({"name": name, "status": "blocked", "reason": reason})
    print(
        json.dumps(
            {"deployment_performed": False, "production_flags_changed": False, "checks": results},
            indent=2,
        )
    )
    # External release gates always remain explicit; exit code concerns selected checks.
    return int(any(row["status"] == "blocked" and row["name"] in args.run for row in results))


if __name__ == "__main__":
    raise SystemExit(main())
