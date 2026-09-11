# CI hardening — backend coverage, types, dependency scanning

Phase 3 of the contract-hardening arc. **All of it has shipped** — the config,
the code, and the CI job wiring. The workflow files were briefly blocked on a
token with the `workflow` scope (`gh auth refresh -h github.com -s workflow`);
that was resolved, and `git ls-files .github/workflows/` now lists **12**
workflows including `ci.yml`, `contract.yml`, `ml-health.yml` and
`weekly-digest.yml`. `.git/info/exclude` holds no staged workflow entries.
The YAML quoted below is kept as documentation of what each gate does — read
`.github/workflows/ci.yml` for the authoritative version.

Run every gate locally before pushing:

```bash
PY=/opt/anaconda3/bin/python scripts/ci_checks.sh --all
```

## Measured baselines (re-measured 2026-09-10)

| Gate | Current | Chosen threshold | Enforcement |
|------|---------|------------------|-------------|
| Backend coverage (`backend/app`) | **89%** | `--cov-fail-under=85` | blocking |
| mypy — trust boundary (`schemas` + `core`, **43 files**) | **0 errors** (strict, `disallow_untyped_defs`) | 0 | blocking |
| mypy — `services` (~130 err) / `api` (~140 err) | dirty | — | advisory, incremental |
| mypy — legacy root (`risk_engine.py`, `data_provider.py`) | dirty | — | advisory (unchanged) |
| `pip-audit` backend runtime deps | the 7 starlette findings are **closed** (see below) | — | advisory (`dep-scan` job, `continue-on-error`) |

85% is deliberately under the measured 89% — a real floor that won't flap on a
one-test swing, not an aspirational 90%.

## Config shipped now

- `backend/.coveragerc` — measures `backend/app` (the root `pyproject`
  `[tool.coverage.run]` omits `backend/*`, so the backend needs its own).
- `backend/mypy.ini` — the blocking trust-boundary config; documents the
  incremental roadmap for `services`/`api`.
- `requirements-dev.txt` — `pip-audit` added (`pytest-cov`/`mypy` already there).
- `scripts/ci_checks.sh` — local mirror of all gates.
- Two type fixes to keep the boundary strict-clean: `deps_auth._jwk_client`
  return type + `public_risk._no_duplicate_tickers` return type.

## `ci.yml` gates (all live — quoted here for reference)

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

**3. The advisory `dep-scan` job.** Live, with `continue-on-error: true`. The
starlette findings that originally justified the non-blocking setting are now
resolved (below), so this can be flipped to blocking whenever the owner wants
a dependency CVE to stop a merge:

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

## Dependency audit findings — starlette CVEs: DONE

`pip-audit` originally flagged **7 CVEs in starlette 0.48.0**
(PYSEC-2026-161/248/249/1942, CVE-2026-48817/48818), pulled in by the old
`fastapi>=0.115,<0.120` ceiling. **That bump has shipped.**
`backend/requirements-backend.txt` now pins exactly:

```
fastapi==0.139.0
starlette==1.3.1
```

starlette is pinned explicitly because fastapi 0.139 only requires
`starlette>=0.46.0` with no ceiling — without the exact pin a fresh install
could still resolve a vulnerable version. The follow-ups that rode with it are
also done: the backend suite was re-run, `openapi.json` + `api-types.ts` were
regenerated on the new toolchain, and `contract.yml` no longer carries a
separate codegen override — the exact-pinned requirements **are** the codegen
toolchain, so the two cannot drift apart.

## Grounding eval — live and BLOCKING

`copilot-eval` is a committed job in `.github/workflows/ci.yml`. It runs the
**50-case** grounding eval in offline-template mode
(`python evals/run_grounding_eval.py --threshold 0.98 --json
copilot-eval-report.json`) and uploads the machine-readable report as an
artifact. It has **no `continue-on-error`, so it is blocking** — grounding
faithfulness, six-section integrity, injection predicates, the language
contract, the confidence gate and the isolation probe are all hard failures.

The duplication with `backend/tests/test_ai_eval_grounding.py` (which
independently hard-gates the same run inside `backend-tests`) is deliberate and
kept: the standalone job additionally surfaces the faithfulness report as its
own visible check and as a downloadable artifact. See
`evals/copilot/README.md`.
