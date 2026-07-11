#!/usr/bin/env bash
# Local mirror of the backend CI hardening gates (docs/ci-hardening.md). Run
# before pushing so the gates don't surprise you in CI. Each gate prints its
# own PASS/FAIL; the script exits non-zero if any BLOCKING gate fails.
#
#   scripts/ci_checks.sh            # blocking gates only
#   scripts/ci_checks.sh --all      # also run advisory gates (dep audit)
#
# PY overrides the interpreter (this repo's system python3 has a broken
# fastapi/starlette pair; use anaconda locally):
#   PY=/opt/anaconda3/bin/python scripts/ci_checks.sh
set -uo pipefail
cd "$(dirname "$0")/.."
PY="${PY:-python}"
rc=0

echo "== [blocking] backend coverage (>=85%) =="
"$PY" -m pytest backend/tests -q -o "addopts=" \
  --cov=backend/app --cov-config=backend/.coveragerc \
  --cov-report=term-missing:skip-covered --cov-fail-under=85 || rc=1

echo "== [blocking] mypy — backend trust boundary (schemas + core) =="
"$PY" -m mypy --config-file backend/mypy.ini backend/app/schemas backend/app/core || rc=1

echo "== [advisory] mypy — services/api (incremental; not gated) =="
"$PY" -m mypy backend/app/services backend/app/api --ignore-missing-imports \
  2>&1 | tail -1 || true

if [ "${1:-}" = "--all" ]; then
  echo "== [advisory] pip-audit — backend runtime deps =="
  "$PY" -m pip_audit -r requirements.txt -r backend/requirements-backend.txt \
    --progress-spinner off || true
fi

echo "== done (rc=$rc) =="
exit $rc
