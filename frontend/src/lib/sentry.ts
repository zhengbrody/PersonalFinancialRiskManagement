// Shared Sentry config for the client / server / edge runtimes so the DSN +
// enable-gate live in one place (the DSN is the public browser DSN; baking a
// default is fine, env-overridable via NEXT_PUBLIC_SENTRY_DSN).
export const SENTRY_DSN =
  process.env.NEXT_PUBLIC_SENTRY_DSN ||
  "https://c6ee4dd05a13fb3da4669a5a4db7ba08@o4511493492178944.ingest.us.sentry.io/4511494053560320";

// Errors-only, production-only — dev/test never emit.
export const SENTRY_ENABLED = process.env.NODE_ENV === "production";
