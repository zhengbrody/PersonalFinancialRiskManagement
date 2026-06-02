// Browser-side Sentry init (loaded by withSentryConfig). Captures client JS
// errors / unhandled rejections. Errors-only (no perf, no replay) for now to
// keep volume bounded. The DSN is public by design (it ships in the bundle).
// Only enabled in production so dev noise never reaches Sentry.
import * as Sentry from "@sentry/nextjs";

Sentry.init({
  dsn:
    process.env.NEXT_PUBLIC_SENTRY_DSN ||
    "https://265bcf074c8503af969b63f4961dbfb2@o4511493492178944.ingest.us.sentry.io/4511494000803841",
  enabled: process.env.NODE_ENV === "production",
  tracesSampleRate: 0,
  replaysSessionSampleRate: 0,
  replaysOnErrorSampleRate: 0,
});
