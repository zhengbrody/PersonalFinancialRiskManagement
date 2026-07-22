/**
 * Privacy-safe post-auth navigation.
 *
 * Only a tiny allowlist of internal product destinations may cross the auth
 * boundary. Portfolio holdings remain in browser storage and are never placed
 * in a URL, OAuth state, analytics event, or email link.
 */

const AUTH_REDIRECT_KEY = "mm:auth:next";

const ALLOWED_AUTH_REDIRECT_PATHS = new Set([
  "/",
  "/admin",
  "/analyze",
  "/copilot",
  "/institutions",
  "/portfolios",
  "/portfolios/new",
  "/quant",
  "/research",
  "/risk",
  "/scenarios",
  "/score",
  "/settings",
]);

const ANALYZE_VIEWS = new Set([
  "overview",
  "drivers",
  "stress",
  "plan",
  "history",
]);

function parseAllowedDestination(candidate: string): string | null {
  // Paths are parsed against a fixed local origin, then required to remain on
  // that origin. This rejects absolute URLs, protocol-relative URLs, hashes,
  // credentials, encoded host tricks and all non-allowlisted product routes.
  let url: URL;
  try {
    url = new URL(candidate, "https://mindmarket.local");
  } catch {
    return null;
  }
  if (
    !candidate.startsWith("/") ||
    candidate.startsWith("//") ||
    url.origin !== "https://mindmarket.local" ||
    url.hash ||
    !ALLOWED_AUTH_REDIRECT_PATHS.has(url.pathname)
  ) {
    return null;
  }

  // Query strings are rejected everywhere except the non-sensitive Analyze
  // stage selector. Holdings, tickers, questions and portfolio ids therefore
  // never cross the auth boundary through `next` or OAuth state.
  if (!url.search) return url.pathname;
  if (url.pathname !== "/analyze") return null;
  if (Array.from(url.searchParams.keys()).some((key) => key !== "view")) {
    return null;
  }
  const views = url.searchParams.getAll("view");
  if (views.length !== 1 || !ANALYZE_VIEWS.has(views[0])) return null;
  return `/analyze?view=${encodeURIComponent(views[0])}`;
}

export function safeAuthRedirect(
  candidate: string | null | undefined,
  fallback: string,
): string {
  const safeFallback = parseAllowedDestination(fallback) ?? "/";
  return candidate ? (parseAllowedDestination(candidate) ?? safeFallback) : safeFallback;
}

/** Read an allowlisted `next` query parameter, then fall back to the current
 * tab's remembered intent. Invalid query values override (rather than expose)
 * any stored value and fail closed to `fallback`. */
export function readAuthRedirect(fallback: string): string {
  if (typeof window === "undefined") return fallback;
  const params = new URLSearchParams(window.location.search);
  if (params.has("next")) {
    return safeAuthRedirect(params.get("next"), fallback);
  }
  try {
    return safeAuthRedirect(window.sessionStorage.getItem(AUTH_REDIRECT_KEY), fallback);
  } catch {
    return safeAuthRedirect(null, fallback);
  }
}

export function rememberAuthRedirect(candidate: string, fallback: string): string {
  const safe = safeAuthRedirect(candidate, fallback);
  if (typeof window !== "undefined") {
    try {
      window.sessionStorage.setItem(AUTH_REDIRECT_KEY, safe);
    } catch {
      // Storage may be disabled in a privacy-restricted browser. The safe
      // fallback still works; only cross-page intent persistence is lost.
    }
  }
  return safe;
}

export function consumeAuthRedirect(fallback: string): string {
  const safe = readAuthRedirect(fallback);
  if (typeof window !== "undefined") {
    try {
      window.sessionStorage.removeItem(AUTH_REDIRECT_KEY);
    } catch {
      // Unavailable storage is a safe degradation; nothing sensitive leaks.
    }
  }
  return safe;
}

export function authHref(page: "/login" | "/signup", next: string): string {
  const safe = safeAuthRedirect(next, "/");
  return `${page}?next=${encodeURIComponent(safe)}`;
}
