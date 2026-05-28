# MindMarket Backend (FastAPI) — Phase 1

This is the new FastAPI service that wraps MindMarket's existing
quant / AI / portfolio logic as typed JSON APIs. It is the **first
phase** of the migration documented in
[`docs/adr/0004-fastapi-nextjs-migration.md`](../docs/adr/0004-fastapi-nextjs-migration.md).

**Streamlit is unchanged.** Every page under `pages/`, every helper
under `libs/`, every entry in `engine/` keeps working. This service
imports from those modules; it does not modify them.

---

## Quick start

```bash
# From the repo root
pip install -r requirements.txt
pip install -r backend/requirements-backend.txt

# Run the dev server (auto-reload on changes)
uvicorn backend.app.main:app --reload --port 8000

# Interactive docs
open http://localhost:8000/docs
```

## Environment

| Variable | Purpose | Required |
|----------|---------|----------|
| `MINDMARKET_ENV` | `dev` (default), `staging`, or `production`. Controls CORS defaults. | No |
| `MINDMARKET_ALLOWED_ORIGINS` | Comma-separated CORS allow-list. Required in production; optional in dev. | Prod only |
| `SUPABASE_URL` | Public Supabase project URL. | Phase 2+ |
| `SUPABASE_JWT_SECRET` | HS256 secret used to verify JWTs on protected routes. | For protected routes |
| `SUPABASE_ANON_KEY` | Public anon key (used by the frontend; surfaced for parity). | Phase 2+ |

LLM / Stripe / FMP keys are inherited from the existing process
environment when the backend runs on the same host as the Streamlit
container. No changes needed.

## Endpoint inventory (Phase 1)

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| `GET` | `/api/v1/health` | Public | Liveness + import sanity check |
| `POST` | `/api/v1/risk/score` | Public | Score an explicit-holdings portfolio. Stateless; no Supabase, no LLM. |
| `POST` | `/api/v1/equity/deep_analysis` | Public | Single-name research view. Phase 1 returns the deterministic placeholder analysis; Phase 4 will add billed LLM routing. |
| `GET` | `/api/v1/portfolios/me` | JWT (Supabase) | Returns the authed user's identity. Listing is wired in Phase 2 once `libs.auth.client.get_supabase` accepts an explicit token. |

## Response envelope

Every endpoint returns the contract defined in ADR-0004:

```json
{
  "data":  { "...": "..." } | null,
  "error": { "code": "...", "message": "...", "details": {} } | null,
  "meta":  { "request_id": "...", "elapsed_ms": 12 }
}
```

On error, HTTP status matches the error class (400 / 401 / 403 /
404 / 422 / 500). The frontend's `apiFetch<T>()` wrapper (Phase 2)
relies on this shape.

### Calling `/api/v1/risk/score`

```bash
curl -X POST http://localhost:8000/api/v1/risk/score \
  -H 'Content-Type: application/json' \
  -d '{
    "holdings": [
      {"ticker": "SPY", "market_value": 60000},
      {"ticker": "BND", "market_value": 40000}
    ],
    "risk_preference": 3
  }'
```

Returns a `PortfolioScore` JSON with `overall_score` (0..1000), three
dimension scores, and the full metrics block. No real market data
needed; the endpoint synthesises a 252-day returns matrix by default
so the response is fully reproducible. To use real data, pass `returns`
inline (`{ticker: [r1, r2, ...]}`).

### Calling protected routes

```bash
JWT=$(...)   # mint or obtain from Supabase
curl http://localhost:8000/api/v1/portfolios/me \
  -H "Authorization: Bearer $JWT"
```

Without a valid JWT this returns 401:
```json
{
  "data": null,
  "error": {"code": "unauthorized", "message": "Missing bearer token."},
  "meta": {"request_id": "...", "elapsed_ms": 0}
}
```

## Running the tests

```bash
pytest backend/tests -q
```

Tests run offline (no Supabase / no LLM / no yfinance). The JWT
fixture mints a test-signed HS256 token; CORS tests assert the
production allow-list path stays strict.

## What's intentionally NOT in Phase 1

- No frontend code. The Next.js shell lands in Phase 2.
- No LLM invocation. `/equity/deep_analysis` returns the deterministic
  placeholder analysis; Phase 4 plumbs billed LLM routing.
- `libs.auth.client.get_supabase` is not yet refactored to accept an
  explicit per-request token. Phase 2 wires this so `list_portfolios`
  can return RLS-filtered data for the JWT holder; today
  `/portfolios/me` returns only the verified identity.
- No new deployment surface. Phase 5 (Caddy reroute) ships the
  backend in front of users.

## Architecture pointers

- Adding a new endpoint? Create `backend/app/api/v1/<name>.py` with a
  router (`prefix="/api/v1/<name>"`) and include it in `main.py`.
  Add a `backend/app/schemas/<name>.py` for the Pydantic request /
  response models.
- Adding a cross-cutting concern? It goes under `backend/app/core/`.
  Today that folder has `config.py`, `cors.py`, `responses.py`,
  `deps_auth.py`.
- All envelope helpers live in `backend/app/core/responses.py`. Don't
  return raw dicts from routes — call `ok(...)` or raise an `APIError`.
- All auth lives in `backend/app/core/deps_auth.py`. Mount
  `Depends(require_user)` on a route to require a valid JWT; mount
  `Depends(optional_user)` if the route personalises but doesn't
  require auth.
