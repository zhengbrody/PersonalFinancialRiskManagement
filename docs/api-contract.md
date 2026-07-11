# API contract — FastAPI → OpenAPI → TypeScript, single source

The backend contract is defined once, in the FastAPI route declarations, and
flows to the frontend as generated types. Nothing is hand-mirrored twice.

## The pipeline

```
FastAPI routes (response_model=Envelope[X])
        │  python scripts/export_openapi.py
        ▼
openapi.json                 ← committed; the bridge artifact
        │  cd frontend && npm run gen:api   (reads ../openapi.json, offline)
        ▼
frontend/src/lib/api-types.ts ← committed; components["schemas"][...]
        │
        ├─ request types      → schemas.ts re-exports them directly
        └─ response types     → zod schemas validate at runtime; contract.ts
                                 pins the zod shapes to the generated types
```

* **Envelope.** Every JSON endpoint returns `{data, error, meta}` via
  `core.responses.ok()`. Routes declare `response_model=Envelope[X]`
  (`backend/app/schemas/envelope.py`) so OpenAPI describes the real payload
  instead of `unknown`. This is **documentation only** — a route returns a
  `JSONResponse`, which FastAPI passes through untouched, so annotating a route
  never changes the wire payload (verified by the full backend suite).
* **Requests** are typed straight from `api-types.ts` (`schemas.ts`).
* **Responses** keep hand-written zod schemas for **runtime** validation at the
  network boundary (`apiFetch({ schema })`), because `looseObject` gives us
  additive-safe validation + NaN scrubbing that raw types can't. `contract.ts`
  asserts, at `tsc` time, that the zod shapes still agree with the generated
  contract.

## Regenerate after any backend contract change

```bash
python scripts/export_openapi.py          # → openapi.json
cd frontend && npm run gen:api            # → src/lib/api-types.ts
```

Commit both. Forgetting to is caught by the gates below.

## Drift gates

1. **`backend/tests/test_openapi_contract.py`** — runs in the existing
   `backend-tests` CI job. Structural (version-stable): every main endpoint's
   200 is `Envelope[<model>]`, nothing regresses to `response_model=None`, and
   the committed `openapi.json` matches the live app's contract map. **Live now.**
2. **`.github/workflows/contract.yml`** — byte-exact regen-diff: regenerates
   `openapi.json` + `api-types.ts` with a pinned codegen toolchain and fails on
   any `git diff`. **Staged locally** (`.git/info/exclude`) — pushing a workflow
   file needs `gh auth refresh -h github.com -s workflow`, same as
   `ml-health.yml` / `weekly-digest.yml`. Until pushed, gate (1) covers the
   backend side.

The `contract.yml` toolchain pins (`fastapi==0.128.5`, `pydantic==2.12.5`,
`pydantic-core==2.41.5`, `starlette==0.52.1`, `openapi-typescript` from the
lockfile) must match whatever produced the committed artifacts. Bump them
together when regenerating on a newer toolchain.
