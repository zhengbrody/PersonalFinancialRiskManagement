// Browser-side Sentry init (loaded by withSentryConfig). Captures client JS
// errors / unhandled rejections. Errors-only (no perf, no replay) for now.
import * as Sentry from "@sentry/nextjs";
import { SENTRY_DSN, SENTRY_ENABLED } from "@/lib/sentry";

Sentry.init({
  dsn: SENTRY_DSN,
  enabled: SENTRY_ENABLED,
  tracesSampleRate: 0,
  replaysSessionSampleRate: 0,
  replaysOnErrorSampleRate: 0,
});
