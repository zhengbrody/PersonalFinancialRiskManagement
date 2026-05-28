# MindMarket Frontend (Next.js) — Phase 2

The Next.js App Router shell that will replace the Streamlit UI page-
by-page. Phase 2 is the **local-only** scaffold: it talks to the
Phase 1 FastAPI backend on `localhost:8000` and is not yet deployed.

Streamlit at `mindmarket.app` continues to serve users unchanged.

## Quick start

```bash
# Terminal 1 — backend (from repo root)
uvicorn backend.app.main:app --reload --port 8000

# Terminal 2 — frontend
cd frontend
npm install        # first run only
npm run dev        # http://localhost:3000
```

Then open `http://localhost:3000/score` and click "Run score". The
synthesised-returns warning in the result panel is expected — no real
market data is fetched in the Phase 1 backend.

## Environment

Copy `.env.example` to `.env.local` (gitignored by Next.js by default):

| Variable | Purpose | Required |
|----------|---------|----------|
| `NEXT_PUBLIC_API_BASE_URL` | Backend URL the browser calls. | No — defaults to `http://localhost:8000` |
| `NEXT_PUBLIC_SUPABASE_URL` | Supabase project URL. | Phase 3+ |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Supabase anon key. | Phase 3+ |

## Layout

```
src/
├── app/
│   ├── layout.tsx          # dark fintech shell (header + container)
│   ├── page.tsx            # marketing-ish landing for Phase 2
│   ├── score/page.tsx      # POST /api/v1/risk/score demo
│   └── globals.css         # tailwind + theme tokens
├── components/
│   ├── site-shell.tsx      # sticky header + nav
│   └── ui/                 # shadcn-style primitives (Button/Card/Input/Skeleton)
└── lib/
    ├── api.ts              # apiFetch<T> + ApiError (envelope unwrapper)
    ├── schemas.ts          # TS mirror of backend response shapes
    ├── supabase.ts         # lazy Supabase singleton (Phase 3 use-site)
    └── utils.ts            # cn() class-name merger
```

## Conventions

- Every backend call goes through `apiFetch<T>(path, opts)`. It
  unwraps the `{data, error, meta}` envelope and throws `ApiError`
  on failure. **Do not call `fetch` directly** — the typed wrapper
  is the contract.
- `apiFetch({ authToken })` accepts a bearer token for protected
  routes. Pair with `getAccessToken()` from `lib/supabase.ts` when
  Phase 3 lands.
- Components live under `components/`; UI primitives under
  `components/ui/`. Server components by default — flip to
  `"use client"` only when you need state/effects.

## Scripts

```bash
npm run dev       # dev server with HMR
npm run build     # production build (used for type-check + bundle)
npm run lint      # next lint (ESLint)
npm run start     # serve the production build (after `npm run build`)
```

## What Phase 2 intentionally does NOT do

- No production deploy. No Caddy / Docker / EC2 changes. Phase 5 ships
  the frontend behind `mindmarket.app/`.
- No port of any specific Streamlit page yet. `/score` exists only to
  prove the end-to-end envelope path.
- No protected auth flow — the Supabase client is wired but no login
  UI ships in Phase 2. `/portfolios` etc. land in Phase 3.
- No state management library, no React Query yet. Plain `useState`
  is enough for one demo page; we'll add React Query when we port the
  Overview page.
