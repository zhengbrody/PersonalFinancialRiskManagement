// Server/edge-side Sentry init (loaded via src/instrumentation.ts). Errors-only,
// production-only. Most server logic lives in the FastAPI backend (which has its
// own Sentry); this catches Next.js SSR / route-handler errors.
import * as Sentry from "@sentry/nextjs";

Sentry.init({
  dsn:
    process.env.NEXT_PUBLIC_SENTRY_DSN ||
    "https://265bcf074c8503af969b63f4961dbfb2@o4511493492178944.ingest.us.sentry.io/4511494000803841",
  enabled: process.env.NODE_ENV === "production",
  tracesSampleRate: 0,
});
