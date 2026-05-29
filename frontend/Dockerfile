# MindMarket Next.js frontend — production image.
#
# Multi-stage:
#   1. `deps`     : install node_modules cleanly from package-lock.
#   2. `builder`  : `npm run build` — bakes in NEXT_PUBLIC_* env vars.
#   3. `runner`   : minimal runtime, copies standalone server output.
#
# Why standalone:
#   `next.config.mjs` sets `output: "standalone"`. The build emits
#   `.next/standalone/server.js` plus only the node_modules it needs.
#   Final runtime image is ~200 MB vs ~1 GB if we copied the whole
#   build dir.
#
# Why NEXT_PUBLIC_* are build args:
#   Next.js inlines these into the client bundle at compile time. Once
#   the image is built the values are frozen. That is the entire point
#   of the `NEXT_PUBLIC_` prefix — anything else stays server-side.
#
# Secrets policy:
#   NO server-side secrets (Stripe, Supabase service key, Anthropic
#   keys) appear in this image. The frontend never needs them.

# ── Stage 1: deps ─────────────────────────────────────────────────
FROM node:20-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
# `npm ci` is reproducible: it fails if package.json and the lockfile
# disagree. That's what we want for a production image.
RUN npm ci --no-audit --no-fund

# ── Stage 2: builder ──────────────────────────────────────────────
FROM node:20-alpine AS builder
WORKDIR /app

# Build args declared up front so they can be set via
# `docker compose build --build-arg ...` or `--build-arg X=$Y` in a
# CI runner. Empty defaults so a bare `docker build .` doesn't fail —
# the runtime will fall back to localhost:8000 (see frontend/src/lib/env.ts).
ARG NEXT_PUBLIC_API_BASE_URL=
ARG NEXT_PUBLIC_SUPABASE_URL=
ARG NEXT_PUBLIC_SUPABASE_ANON_KEY=

# Expose the args as env vars so `next build` picks them up and inlines
# them into the static bundle.
ENV NEXT_PUBLIC_API_BASE_URL=$NEXT_PUBLIC_API_BASE_URL \
    NEXT_PUBLIC_SUPABASE_URL=$NEXT_PUBLIC_SUPABASE_URL \
    NEXT_PUBLIC_SUPABASE_ANON_KEY=$NEXT_PUBLIC_SUPABASE_ANON_KEY \
    NEXT_TELEMETRY_DISABLED=1

COPY --from=deps /app/node_modules ./node_modules
COPY . .

RUN npm run build

# ── Stage 3: runner ───────────────────────────────────────────────
FROM node:20-alpine AS runner
WORKDIR /app

ENV NODE_ENV=production \
    PORT=3000 \
    HOSTNAME=0.0.0.0 \
    NEXT_TELEMETRY_DISABLED=1

# Non-root user — matches what Next.js documents for the standalone
# example. UID 1001 is conventional ("nextjs") and helps tooling that
# inspects file ownership in the image.
RUN addgroup --system --gid 1001 nodejs \
 && adduser  --system --uid 1001 nextjs

# `public/` for static assets; `.next/static` for the compiled chunks;
# the standalone bundle for the server itself.
COPY --from=builder --chown=nextjs:nodejs /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs

EXPOSE 3000

# Healthcheck hits the root page — Next.js serves it directly without
# touching the backend, so this stays green even when the API is down.
# wget is in busybox on the alpine base.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=5 \
    CMD wget --spider --quiet http://127.0.0.1:3000/ || exit 1

CMD ["node", "server.js"]
