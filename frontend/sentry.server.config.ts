// Server/edge-side Sentry init (loaded via src/instrumentation.ts). Errors-only,
// production-only. Most server logic lives in the FastAPI backend (own Sentry);
// this catches Next.js SSR / route-handler errors.
import * as Sentry from "@sentry/nextjs";
import { SENTRY_DSN, SENTRY_ENABLED } from "@/lib/sentry";
import { scrubSentryEvent } from "@/lib/sentry-scrub";

Sentry.init({
  dsn: SENTRY_DSN,
  enabled: SENTRY_ENABLED,
  sendDefaultPii: false,
  beforeSend: scrubSentryEvent,
  tracesSampleRate: 0,
});
