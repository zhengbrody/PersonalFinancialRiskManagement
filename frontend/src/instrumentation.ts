// Next.js instrumentation hook — loads the server/edge Sentry init at runtime.
// (The client config is injected by withSentryConfig.)
export async function register() {
  if (process.env.NEXT_RUNTIME === "nodejs") {
    await import("../sentry.server.config");
  }
  if (process.env.NEXT_RUNTIME === "edge") {
    await import("../sentry.edge.config");
  }
}
