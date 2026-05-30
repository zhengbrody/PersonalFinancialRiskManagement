# MindMarket Backend (FastAPI)

> Last updated: Phase 3 (2026-05-29). Phase 1 = scaffold, Phase 2 = OpenAPI
> + CI, Phase 3 = explicit-token auth + RLS-filtered `/portfolios/me`.

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
| `SUPABASE_URL` | Public Supabase project URL. Also used to fetch JWKS for ES256/RS256 JWT verification. | Phase 2+ |
| `SUPABASE_JWT_SECRET` | Legacy HS256 secret used only when the token header says `alg=HS256`. Modern Supabase projects can verify via JWKS with `SUPABASE_URL`. | HS256 projects only |
| `SUPABASE_ANON_KEY` | Public anon key (used by the frontend; surfaced for parity). | Phase 2+ |

LLM / Stripe / FMP keys are inherited from the existing process
environment when the backend runs on the same host as the Streamlit
container. No changes needed.

## Endpoint inventory

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| `GET` | `/api/v1/health` | Public | Liveness + import sanity check |
| `POST` | `/api/v1/risk/score` | Public | Score an explicit-holdings portfolio. Stateless; no Supabase, no LLM. |
| `POST` | `/api/v1/equity/deep_analysis` | Public | Single-name research view. Returns the deterministic placeholder analysis; Phase 4 will add billed LLM routing. |
| `GET` | `/api/v1/portfolios/me` | JWT (Supabase) | Returns `{user_id, email, portfolios: PortfolioOut[]}`. The list is fetched via `libs.auth.portfolios.list_portfolios(access_token=user.access_token)` so Supabase RLS filters every row to the JWT holder. |

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

### The access-token plumbing (Phase 3)

The dependency `require_user` returns an `AuthedUser` dataclass that
carries the **raw verified JWT** as `access_token`. Routes that hit
Supabase forward it verbatim:

```python
@router.get("/me")
def list_my_portfolios(user: AuthedUser = Depends(require_user)):
    rows = list_portfolios(access_token=user.access_token)
    ...
```

Why this matters: Supabase's Row-Level Security policies key off the
JWT's `sub` claim. If the route uses the server's anon key (or a
service-role key), RLS does NOT apply and every caller sees every
row. The contract test `test_forwards_caller_jwt_so_rls_filters_apply`
in `test_portfolios_me.py` asserts byte-for-byte that the same token
the client sent reaches `list_portfolios` — any refactor that breaks
this fails the build.

Never log `user.access_token`. It's a bearer credential.

## MCP server (Phase 4c)

A standalone Model Context Protocol server lives in
`backend/mcp_server/`. It exposes MindMarket's data + scoring as
typed tools any Claude-compatible client (Claude Desktop, Claude
Code, custom agents) can call.

Tools registered today:

| Tool | Backed by | Purpose |
|------|-----------|---------|
| `mindmarket_score_portfolio` | `engine.quant` + `services.market_data` | Score a hypothetical portfolio with real prices |
| `mindmarket_get_market_prices` | `services.market_data` | Latest adjusted close per ticker |
| `mindmarket_get_macro_series` | `services.macro_data` | FRED series (Fed Funds, CPI, unemployment, …) |
| `mindmarket_get_yield_curve` | `services.macro_data` | Latest US Treasury daily curve |

Every tool reuses the **same** service module the HTTP route uses —
an LLM agent and a browser user can never see different numbers.

Run from the repo root:

```bash
python -m backend.mcp_server
```

Add to Claude Desktop's `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "mindmarket": {
      "command": "python",
      "args": ["-m", "backend.mcp_server"],
      "cwd": "/path/to/RiskManagement"
    }
  }
}
```

Tool implementations are in `backend/mcp_server/tools.py`; the MCP
protocol wiring is in `backend/mcp_server/server.py`. Tests in
`backend/tests/test_mcp_server.py` cover the registry shape + each
handler's behaviour with the underlying services mocked.

## Running the tests

```bash
# Local — fast, offline, ~1.2s
pytest backend/tests -q -o "addopts="
```

The `-o "addopts="` wipes the inherited root `pytest.ini` options
(`--cov=. --cov-fail-under=60`) which target the Streamlit test suite,
not this one. The CI job uses the same flag.

Tests run offline (no Supabase / no LLM / no yfinance). The JWT
fixture mints test-signed HS256 tokens, and auth tests also generate
local RS256/ES256 keys to prove the JWKS path without reaching the
network. The `fake_portfolios` fixture in `conftest.py` monkeypatches
`libs.auth.portfolios.list_portfolios` so the `/portfolios/me` tests
never reach the real database.

## What's intentionally still deferred

- No LLM invocation. `/equity/deep_analysis` returns the deterministic
  placeholder analysis; Phase 4 plumbs billed LLM routing.
- No active-portfolio scoring endpoint (`POST /api/v1/risk/score_from_active`).
  Needs the market-data layer (yfinance / FMP) wrapped server-side so
  the endpoint can compute `market_value = shares × price`. Phase 4.
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
