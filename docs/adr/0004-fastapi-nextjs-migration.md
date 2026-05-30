# ADR-0004 — Progressive migration from Streamlit to FastAPI + Next.js

**Status**: Accepted (Phase 1 begins 2026-05-27)
**Owner**: zhengbrody
**Supersedes**: none
**Related**: ADR-0001 (VPC), ADR-0002 (Phase-2 compute)

---

## Context

MindMarket today is a single Streamlit application
(`app.py` + ~16 pages, ~14k LOC of Python under `libs/`, `engine/`,
`agents/`, `domain/`). Streamlit has carried us cleanly from MVP
through paid-tier billing and an institutional-grade equity research
flow. We don't want to throw it away.

But four limits have become product blockers:

1. **No public landing pages with SEO.** Streamlit renders all pages
   as authenticated dashboards; we can't ship statically-rendered
   marketing pages, blog posts, or shareable report URLs that
   search engines index.
2. **Mobile feel.** Streamlit's column primitive is desktop-first.
   We added `@media` overrides in `ui/components.inject_global_css`
   to claw back acceptable mobile behaviour, but real native fintech
   UX (touch targets, sheet modals, swipe gestures) is out of reach.
3. **UI primitives gap.** Modern fintech UX (shadcn/ui, framer-motion,
   radix dialogs, command palettes) is a React ecosystem. Replicating
   each via `unsafe_allow_html` HTML is slow and fragile.
4. **No headless API surface.** A future iOS / Android client, a
   partner integration, or a CI bot that wants to "score this
   portfolio" all need a typed HTTP API. Streamlit's only callable
   surface is its own HTML.

Throwing away the Python quant + AI layer is **not** an option —
that's the differentiator. So we split:

* **Frontend** moves to Next.js (App Router) + TypeScript + Tailwind +
  shadcn/ui.
* **Backend** stays in Python but lifts out of Streamlit as a
  **FastAPI** service that re-uses every existing module under
  `libs/`, `engine/`, `agents/`, `domain/` verbatim — no math
  rewrites.
* **Supabase** stays as-is: source of truth for auth, portfolios,
  snapshots, saved insights, billing.

## Decision

Adopt a five-phase progressive migration. Streamlit stays deployable
and feature-flagged ON throughout every phase. The new stack only
takes over a URL once it's at parity with the equivalent Streamlit
page on:

1. functional coverage,
2. error rate (≤ 0.5% over 100 production calls),
3. p95 latency (≤ 1.2× the Streamlit baseline).

If any phase fails the gate, we route DNS back to the old surface on
the same EC2 instance with no code change.

### Phases

| Phase | Scope | Streamlit fate | Done when |
|-------|-------|----------------|-----------|
| **1** *(this ADR)* | FastAPI skeleton + 3 real endpoints + JWT dep + ADR | Untouched | `/api/v1/health` returns 200; `/api/v1/risk/score` echoes a `PortfolioScore` for explicit holdings without touching Supabase; black/ruff/pytest green |
| 2 | Next.js shell (Tailwind + shadcn + Supabase client) | Untouched | landing page + login route work end-to-end against Phase-1 backend |
| 3 | Port Overview / Health Score to Next.js, behind feature flag | Streamlit `/Overview` remains the default | flag flip + a/b shows new UI at parity |
| 4 | Port AI chat (server-sent events for streaming) | Streamlit chat stays | new chat handles 50 concurrent sessions without falling behind |
| 5 | Caddy: `/` → Next.js, `/api/v1` → FastAPI, `/legacy` → Streamlit | Demoted to `/legacy` | DNS + Caddy update; one-week monitor; then sunset |

### Non-decisions (explicitly NOT changing in Phase 1)

* No math is rewritten. FastAPI imports `engine.quant`,
  `libs.risk.*`, `libs.analysis.*`, `libs.auth.snapshots` directly.
* No new auth system. The frontend will use the Supabase JS client
  for sign-in; the backend will verify the resulting JWT.
* No new database. All persistence remains Supabase Postgres + RLS.
* Streamlit is not deleted, renamed, or feature-flagged off.

## Security posture

* LLM API keys, Stripe secret keys, Supabase service-role keys
  stay in the FastAPI process environment. They are NEVER returned
  to the frontend.
* FastAPI reads secrets exclusively from environment variables
  (or, locally, `.env` outside the repo).
* CORS is environment-aware: dev allows `http://localhost:3000`;
  production allows only the deployed Next.js origin(s) from
  `MINDMARKET_ALLOWED_ORIGINS` (comma-separated).
* Authentication uses **per-route FastAPI dependencies**, not a
  global middleware. `/health`, `/openapi.json`, `/docs`, and the
  testable `/api/v1/risk/score` endpoint stay public; anything that
  reads or mutates user data requires a valid Supabase JWT.
* JWT verification accepts Supabase HS256 legacy tokens via
  `SUPABASE_JWT_SECRET` and asymmetric RS256/ES256 tokens through
  the project's JWKS endpoint. Audience is pinned to Supabase's
  `authenticated` value.
* Production deploy gets a new Caddy `route` for `/api/v1/*` — the
  FastAPI container is reachable from Caddy only, never from the
  public network directly.

## API response contract

Every endpoint returns a JSON envelope:

```json
{
  "data": ...,
  "error": null,
  "meta": { "request_id": "...", "elapsed_ms": 12 }
}
```

On error, `data` is null and `error` is `{ "code", "message",
"details" }`. HTTP status code matches the error class (400 / 401
/ 403 / 404 / 422 / 500). This contract is enforced via
`backend/app/core/responses.py` helpers; routers never construct
raw dicts.

## Rollback

Every phase preserves the equivalent Streamlit surface. To roll
back from any phase:

1. Update Caddy to route the affected path back to the Streamlit
   container.
2. `sudo systemctl restart mindmarket`.
3. Investigate offline.

No data migration is needed because Supabase is the only state
store and the schema doesn't change in any phase.

## Consequences

**Wins**
* Real fintech UI (mobile-responsive, SEO-able, shadcn primitives).
* Headless JSON API reusable by future iOS / Android / partner
  integrations.
* Math + AI layer untouched → zero regression risk during UI work.
* Streamlit remains a safety net at every phase.

**Costs**
* Two deploy artifacts to keep in sync (Next.js + FastAPI).
* CI/CD complexity (test matrix grows: Python + TypeScript + e2e).
* Tighter discipline required around the API contract — every new
  page becomes a new endpoint, no more "import a function in
  Streamlit".

**Risks we're explicitly taking**
* Streamlit and Next.js share Supabase RLS; a schema change has to
  consider both clients.
* FastAPI ships under a different runtime than the Streamlit
  container — secrets must be duplicated until we unify on a single
  ECS task or container.

## Open items (resolved in later ADRs)

* ADR-0005 (Phase 2): Next.js auth bootstrap + Supabase SSR.
* ADR-0006 (Phase 4): SSE / WebSocket strategy for the chat.
* ADR-0007 (Phase 5): Caddy routing + final domain layout.

## Implementation status (live)

| Phase | Status | Shipped commit(s) | Notes |
|-------|--------|-------------------|-------|
| 1 — FastAPI backend scaffold | Done | `8e71b84` | 4 endpoints, envelope, JWT dep, CORS, 26 tests |
| 2 — Next.js frontend shell | Done | `886fe30` | App Router, Tailwind, shadcn-style primitives, `/score` demo |
| 2-hardening — OpenAPI gen + Vitest + CI | Done | `ab2ccf4` | `npm run gen:api`, env validation, error boundary, dual-job CI |
| 3 — Auth + `/portfolios/me` wiring | Done | `8a9f526` | Explicit-token Supabase, RLS-filtered list, `/login` + `/portfolios` |
| 4 — Market-data layer + scoring active portfolio | Deferred | — | Needs `data_provider` exposure + `/api/v1/risk/score_from_active` + Overview port |
| 5 — Caddy reroute + production deploy | Deferred | — | New stack stays local until Phase 4 lands |

**Production state (2026-05-29):** `mindmarket.app` still serves the
Streamlit container. The new stack runs only at `localhost`. All
changes from Phases 1–3 are merged on `origin/main` and pass CI but
are not exposed to users.

**Non-breaking guarantees verified after Phase 3:**
* `pytest tests/unit -k "auth or portfolio"` — 181 passed. The
  `libs.auth.client.get_supabase(access_token=...)` and
  `libs.auth.portfolios.list_portfolios(access_token=...)` refactors
  are signature-compatible with every Streamlit call-site.
* No changes to `Dockerfile`, `docker-compose.yml`, `Caddyfile`,
  systemd unit, Supabase migrations, or `.streamlit/secrets.toml`.
