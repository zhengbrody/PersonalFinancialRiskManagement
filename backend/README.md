# MindMarket Backend

FastAPI service for portfolio scoring, risk reports, market data, AI analysis,
billing, Supabase-backed portfolios, and MCP tools.

## Stack

- FastAPI
- Pydantic schemas
- Supabase JWT verification with RLS-aware token forwarding
- Python quant engine (`engine/`, `libs/risk/`, `domain/`)
- Market data services with explicit provider provenance
- Anthropic-powered AI summaries with deterministic fallbacks
- Stripe billing endpoints
- Sentry instrumentation
- MCP server for AI clients

## Run Locally

From the repository root:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -r backend/requirements-backend.txt

uvicorn backend.app.main:app --reload --port 8000
```

Open:

```text
http://localhost:8000/docs
```

## Environment

| Variable | Notes |
| --- | --- |
| `MINDMARKET_ENV` | `dev`, `staging`, or `production`. |
| `MINDMARKET_ALLOWED_ORIGINS` | Comma-separated CORS allow-list. Required in production. |
| `SUPABASE_URL` | Supabase project URL and JWKS source. |
| `SUPABASE_JWT_SECRET` | Legacy HS256 verification secret when applicable. |
| `SUPABASE_ANON_KEY` | Public anon key for Supabase clients. |
| `ANTHROPIC_API_KEY` | Server-side LLM key. |
| `STRIPE_SECRET_KEY` | Stripe server key. |
| `FMP_API_KEY` | Fundamentals and equity research data. |
| `MASSIVE_API_KEY` | Optional fallback market-data provider. |
| `SENTRY_DSN` | Backend error reporting. |

## Endpoint Groups

| Prefix | Purpose |
| --- | --- |
| `/api/v1/health` | Liveness and import sanity checks. |
| `/api/v1/risk` | Score, active score, reports, scenarios, AI explanation. |
| `/api/v1/market` | Prices, movers, sentiment, market context. |
| `/api/v1/macro` | FRED series and Treasury yield curve. |
| `/api/v1/portfolios` | Supabase-backed portfolio CRUD. |
| `/api/v1/research` | Ticker research (FactPack) and AI verdict. |
| `/api/v1/copilot` | Streaming and non-streaming AI copilot. |
| `/api/v1/billing` | Plan, checkout, portal, usage. |
| `/api/v1/quant`, `/api/v1/institutions` | Quant lab and institutional data. |
| `/api/v1/feedback` | In-app product feedback. |

## Response Envelope

Every route returns the same shape:

```json
{
  "data": {},
  "error": null,
  "meta": {
    "request_id": "req_...",
    "elapsed_ms": 12
  }
}
```

Route code should return `ok(...)` or raise an `APIError` helper from
`backend/app/core/responses.py`. Avoid raw response dictionaries.

## Tests

```bash
python -m pytest backend/tests -q --no-cov
python -m black --check backend
python -m ruff check backend
```

Tests should stay offline. Patch provider calls, LLM calls, Supabase calls, and
Stripe calls at the service boundary.

## MCP Server

Run from the repository root:

```bash
python -m backend.mcp_server
```

The MCP server exposes the same scoring, market, and macro services used by the
HTTP API so AI clients and browser users see the same numbers.

## Conventions

- Add routers under `backend/app/api/v1/`.
- Add request/response models under `backend/app/schemas/`.
- Put reusable business logic under `backend/app/services/`.
- Keep quant math deterministic and tested.
- Do not let LLM output become the source of truth for numeric metrics.
- Never log bearer tokens or service-role credentials.
