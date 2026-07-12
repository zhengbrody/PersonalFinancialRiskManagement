import { withSentryConfig } from "@sentry/nextjs";

/** @type {import('next').NextConfig} */
const nextConfig = {
  // Standalone output bundles ONLY the files the production server
  // needs into `.next/standalone`. Drops the rest of node_modules,
  // shrinking the Docker image from ~1 GB (full Next + react + every
  // transitive) to ~200 MB. The runtime stage in `Dockerfile` copies
  // standalone + `.next/static` + `public/` and runs `node server.js`.
  //
  // Safe to keep on for dev too — `next dev` ignores this setting.
  // The E2E webServer serves with `next start`, which doesn't pair with
  // standalone output; `E2E_BUILD=1` (set only by playwright.config.ts) drops
  // standalone for that build. Production is unaffected (env unset → standalone).
  output: process.env.E2E_BUILD ? undefined : "standalone",

  // Don't advertise the framework in an X-Powered-By header (security
  // hygiene — pairs with the Caddyfile security-header block).
  poweredByHeader: false,

  // Next 15: `instrumentationHook` is stable — `src/instrumentation.ts`
  // (Sentry server init) is picked up automatically, so the experimental flag
  // is removed (it now warns as unrecognized).
};

// Sentry build wrapper. No auth token configured → source-map upload is
// skipped (stack traces stay minified, still actionable for a beta); runtime
// error capture works regardless. `silent` keeps the build log clean.
export default withSentryConfig(nextConfig, {
  silent: true,
  disableLogger: true,
  // We don't upload source maps (no auth token) → don't generate/serve them.
  sourcemaps: { disable: true },
});
