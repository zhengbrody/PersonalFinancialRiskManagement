# CI hardening — backend coverage, types, dependency scanning

Phase 3 of the contract-hardening arc. The **config + code** ships now
(committable); the **CI job wiring** is staged because pushing anything under
`.github/workflows/` needs a token with the `workflow` scope
(`gh auth refresh -h github.com -s workflow`), the same block as
`ml-health.yml` / `weekly-digest.yml` / `contract.yml`.

Run every gate locally before pushing:

```bash
PY=/opt/anaconda3/bin/python scripts/ci_checks.sh --all
```

## Measured baselines (2026-07)

| Gate | Current | Chosen threshold | Enforcement |
|------|---------|------------------|-------------|
| Backend coverage (`backend/app`) | **87.3%** | `--cov-fail-under=85` | blocking |
| mypy — trust boundary (`schemas` + `core`, 32 files) | **0 errors** (strict, `disallow_untyped_defs`) | 0 | blocking |
| mypy — `services` (~130 err) / `api` (~140 err) | dirty | — | advisory, incremental |
| mypy — legacy root (`risk_engine.py`, `data_provider.py`) | dirty | — | advisory (unchanged) |
| `pip-audit` backend runtime deps | 7 findings (see below) | — | advisory |

85% is deliberately a hair under the current 87.3% — a real floor that won't
flap on a one-test swing, not an aspirational 90%.

## Config shipped now

- `backend/.coveragerc` — measures `backend/app` (the root `pyproject`
  `[tool.coverage.run]` omits `backend/*`, so the backend needs its own).
- `backend/mypy.ini` — the blocking trust-boundary config; documents the
  incremental roadmap for `services`/`api`.
- `requirements-dev.txt` — `pip-audit` added (`pytest-cov`/`mypy` already there).
- `scripts/ci_checks.sh` — local mirror of all gates.
- Two type fixes to keep the boundary strict-clean: `deps_auth._jwk_client`
  return type + `public_risk._no_duplicate_tickers` return type.

## Staged `ci.yml` changes (apply after `gh auth refresh -s workflow`)

**1. backend-tests job — add the coverage gate.** Install `pytest-cov` and swap
the test step:

```yaml
    - name: Install backend dependencies
      run: |
        python -m pip install --upgrade pip
        pip install -r requirements.txt
        pip install -r backend/requirements-backend.txt
        pip install pytest pytest-cov mypy        # + pytest-cov, mypy

    - name: Run backend tests + coverage gate
      run: |
        pytest backend/tests -q -o "addopts=" \
          --cov=backend/app --cov-config=backend/.coveragerc \
          --cov-report=term-missing:skip-covered --cov-fail-under=85

    - name: Type check — backend trust boundary (blocking)
      run: mypy --config-file backend/mypy.ini backend/app/schemas backend/app/core
```

(The blocking mypy lives here because this job already installs the app deps, so
mypy sees real pydantic types rather than `Any`.)

**2. code-quality job — keep the legacy mypy advisory as-is.** The
`mypy risk_engine.py data_provider.py` step with `continue-on-error: true` stays;
the trust boundary is the *blocking* one above. No permanent `continue-on-error`
on the gated set.

**3. New advisory `dep-scan` job.** Non-blocking until the starlette findings are
resolved (below), then flip to blocking:

```yaml
  dep-scan:
    runs-on: ubuntu-latest
    continue-on-error: true
    steps:
    - uses: actions/checkout@v4
    - uses: actions/setup-python@v5
      with: { python-version: "3.12" }
    - run: pip install pip-audit
    - name: Audit backend deps
      run: pip-audit -r requirements.txt -r backend/requirements-backend.txt
    - uses: actions/setup-node@v4
      with: { node-version: "20" }
    - name: Audit frontend deps
      working-directory: frontend
      run: npm audit --omit=dev || true
```

## Dependency audit findings (owner decision)

`pip-audit` flags **7 CVEs in starlette 0.48.0** (PYSEC-2026-161/248/249/1942,
CVE-2026-48817/48818), fixed in starlette ≥ 0.49.1 / 1.x. starlette is pulled by
`fastapi>=0.115,<0.120`, so the fix is to **bump the fastapi/starlette ceilings**
— a prod-dependency change deliberately kept out of this contract PR (the ceilings
were set in the 2026-07-01 hardening). Track as a follow-up: bump fastapi past
0.120, re-run the backend suite, and (because the contract codegen toolchain is
pinned) regenerate `openapi.json` + `api-types.ts` and re-pin `contract.yml`.

## Grounding eval — keep lean

`copilot-eval` (the staged ci.yml job) runs the 30-case grounding eval in
offline-template mode, but `backend/tests/test_ai_eval_grounding.py` already
hard-gates the same run inside `backend-tests`. To avoid paying for it twice,
either drop the standalone `copilot-eval` job or keep it purely for the visible
faithfulness report — don't gate on it.
