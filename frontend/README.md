# MindMarket Frontend

Next.js App Router frontend for the MindMarket SaaS product.

## Stack

- Next.js 14 App Router
- TypeScript
- Tailwind CSS
- shadcn-style UI primitives
- React Query
- Zod
- Supabase Auth
- Sentry and PostHog client instrumentation

## Run Locally

Start the backend first from the repository root:

```bash
uvicorn backend.app.main:app --reload --port 8000
```

Then start the frontend:

```bash
cd frontend
npm install
cp .env.example .env.local
npm run dev
```

Open:

```text
http://localhost:3000
```

## Environment

`.env.local` is gitignored. `NEXT_PUBLIC_*` values are safe to ship to the
browser, but still should be configured through environment variables rather
than hard-coded in feature code.

| Variable | Notes |
| --- | --- |
| `NEXT_PUBLIC_API_BASE_URL` | Backend URL. Use `http://localhost:8000` locally or `https://mindmarket.app` in production. |
| `NEXT_PUBLIC_SUPABASE_URL` | Supabase project URL. |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Supabase publishable anon key. |
| `NEXT_PUBLIC_SENTRY_DSN` | Public frontend Sentry DSN. |
| `NEXT_PUBLIC_POSTHOG_KEY` | Public PostHog project key. |
| `NEXT_PUBLIC_POSTHOG_HOST` | PostHog ingest host. |

## Routes

| Route | Purpose |
| --- | --- |
| `/` | Landing and macro snapshot. |
| `/signup`, `/login` | Auth flows. |
| `/portfolios` | Saved portfolios. |
| `/score` | Portfolio health score. |
| `/risk`, `/portfolios/[id]/risk` | Risk report. |
| `/scenarios` | Scenario simulation. |
| `/research` | Ticker research. |
| `/markets` | Market dashboard. |
| `/quant` | Quant lab. |
| `/institutions` | Institutional ownership and 13F context. |
| `/copilot` | Streaming AI copilot. |
| `/pricing`, `/settings`, `/admin` | Billing, account, and owner operations. |

## Commands

```bash
npm run dev
npm run lint
npm run test -- --run
npx tsc --noEmit
npm run build
npm run gen:api
```

## Conventions

- Use `src/lib/api.ts` for backend calls. It unwraps the `{data,error,meta}`
  envelope and throws typed `ApiError`s.
- Use React Query hooks in `src/lib/queries.ts` rather than raw component
  fetches.
- Validate external shapes with Zod.
- Keep browser analytics free of tickers, portfolio ids, position sizes, and
  dollar values.
- Prefer server components unless local state, auth context, or client effects
  are required.
