# MindMarket Frontend (Next.js)

> Last updated: Phase 3 (2026-05-29). Phase 2 = scaffold + `/score`,
> Phase 3 = Supabase login + protected `/portfolios`.

The Next.js App Router shell that will replace the Streamlit UI page-
by-page. Still **local-only** — talks to the FastAPI backend on
`localhost:8000` and is not deployed. Streamlit at `mindmarket.app`
continues to serve real users unchanged.

## Quick start

```bash
# Terminal 1 — backend (from repo root)
uvicorn backend.app.main:app --reload --port 8000

# Terminal 2 — frontend
cd frontend
npm install        # first run only
cp .env.example .env.local  # optional — defaults work for the public /score page
npm run dev        # http://localhost:3000
```

Routes available out of the box:

| Route | Auth | Notes |
|-------|------|-------|
| `/` | Public | Phase 2 landing |
| `/score` | Public | `POST /api/v1/risk/score` demo. Works without Supabase config. |
| `/login` | Public | Email + password against Supabase. Needs Supabase env. |
| `/portfolios` | Required | Lists the signed-in user's portfolios from `/api/v1/portfolios/me`. |

## Environment

`.env.example` is the template; copy to `.env.local` (gitignored).

| Variable | Purpose | Required |
|----------|---------|----------|
| `NEXT_PUBLIC_API_BASE_URL` | Backend URL the browser calls. | No — defaults to `http://localhost:8000` |
| `NEXT_PUBLIC_SUPABASE_URL` | Supabase project URL. | For `/login` + `/portfolios` |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Supabase anon key (safe to ship to the browser). | For `/login` + `/portfolios` |

`lib/env.ts` zod-validates these once at module load — a misconfigured
build fails at `next build` time, not at first request.

Without the Supabase vars, `/login` shows a setup notice and
`/portfolios` redirects to `/login`; the public `/score` page keeps
working so contributors can still smoke-test the backend without a
Supabase project.

## Layout

```
src/
├── app/
│   ├── layout.tsx          # dark fintech shell, mounts <Providers>
│   ├── providers.tsx       # QueryClientProvider + AuthProvider
│   ├── page.tsx            # landing
│   ├── error.tsx           # root error boundary
│   ├── not-found.tsx       # branded 404
│   ├── score/page.tsx      # public /score demo
│   ├── login/page.tsx      # email + password sign-in
│   └── portfolios/page.tsx # protected list, useQuery → /portfolios/me
├── components/
│   ├── site-shell.tsx      # sticky header + auth pill
│   └── ui/                 # shadcn-style primitives
├── lib/
│   ├── api.ts              # apiFetch<T> + ApiError
│   ├── api-types.ts        # GENERATED — see `npm run gen:api`
│   ├── auth-context.tsx    # AuthProvider + useAuth hook
│   ├── env.ts              # zod-validated NEXT_PUBLIC_* reader
│   ├── queries.ts          # typed React Query hooks
│   ├── schemas.ts          # response-type mirror until backend declares response_model
│   ├── supabase.ts         # lazy Supabase singleton + getAccessToken()
│   └── utils.ts            # cn() class-name merger
└── test-utils.tsx          # renderWithQuery() helper for component tests
```

## Conventions

### Talking to the backend

- **Every backend call goes through `apiFetch<T>(path, opts)`.** It
  unwraps the `{data, error, meta}` envelope and throws `ApiError`
  on failure (envelope error, non-2xx, network failure, or non-JSON
  body — see `src/lib/api.test.ts` for the matrix). Do not call
  `fetch` directly; the typed wrapper is the contract.
- For protected routes, pass `apiFetch({ authToken })`. In practice
  you go through a React Query hook in `lib/queries.ts` which already
  threads `useAuth().accessToken` through for you.
- **Never read `process.env.NEXT_PUBLIC_*` outside `lib/env.ts`.**
  One zod schema, one fail-fast surface.

### Auth

- `useAuth()` from `lib/auth-context.tsx` is the single source of
  truth in the browser bundle. Returns `{user, accessToken, loading,
  configured, signIn, signOut}`. Null-safe when Supabase env is
  unset (`configured === false` → render the public/signed-out
  branch instead of crashing).
- Page-level guards are client-side (`useEffect` + `router.replace`).
  When we add server-side RSC fetching in Phase 4 the guard moves
  into a Next.js middleware.

### Data fetching

- React Query manages caches. Use the hooks in `lib/queries.ts` —
  query keys are short stable tuples (`["portfolios", "me", userId]`),
  not derived from the access token.
- Default `staleTime` is 30 s and `refetchOnWindowFocus` is on so a
  freshly-signed-in tab doesn't stay stale.

### Components

- Server components by default. Flip to `"use client"` only when you
  need state, effects, or the auth/query context.
- Primitives live in `components/ui/`; one component per file; styled
  via `cn()` + class-variance-authority.

## Scripts

```bash
npm run dev          # dev server with HMR
npm run build        # production build (used for type-check + bundle)
npm run lint         # next lint (ESLint)
npm test             # vitest run — 20 tests
npm run test:watch   # vitest watch mode
npm run test:coverage  # vitest run --coverage
npm run gen:api      # regenerate src/lib/api-types.ts (needs backend at :8000)
```

CI mirrors these. See `.github/workflows/ci.yml` → job `frontend`.

## What's intentionally still deferred

- **No production deploy.** No Caddy / Docker / EC2 changes. Phase 5
  ships the frontend behind `mindmarket.app/`.
- **No port of the Streamlit Overview page yet.** Needs a
  `/api/v1/risk/score_from_active` endpoint that fetches the user's
  real DB holdings + market prices server-side. Phase 4.
- **No sign-up flow.** Users register via the existing Streamlit
  `/Login` page; the same Supabase user works in both apps.
- **No Google OAuth.** Needs a redirect URL configured on the Supabase
  project. Lands once Phase 5's deploy URL is stable.
- **No Sentry.** Adds in Phase 4 alongside `app/error.tsx`'s digest
  logging.
