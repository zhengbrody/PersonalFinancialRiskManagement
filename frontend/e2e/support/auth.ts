/**
 * Test-only auth: make the browser look signed-in WITHOUT a real login.
 *
 * The app's AuthProvider derives the user from `supabase.auth.getSession()`,
 * which reads the session from localStorage and (with a far-future expiry)
 * resolves LOCALLY — no network. So we seed a fake Supabase session into
 * localStorage before the app boots and the whole app treats us as signed-in.
 *
 * There is no real password, no real token, and no personal session here. The
 * JWT is a structurally-valid but unsigned placeholder; the client never
 * verifies the signature, and every backend call is mocked (mock-api.ts).
 *
 * The storage key is `sb-<ref>-auth-token`; `<ref>` is the subdomain of
 * NEXT_PUBLIC_SUPABASE_URL, which playwright.config.ts pins to
 * `https://e2e.supabase.co` → ref `e2e`.
 */

import type { Page } from "@playwright/test";

export const E2E_USER = {
  id: "e2e00000-0000-4000-8000-000000000001",
  email: "e2e-user@mindmarket.test",
};

const STORAGE_KEY = "sb-e2e-auth-token";

function b64url(obj: unknown): string {
  return Buffer.from(JSON.stringify(obj)).toString("base64url");
}

/** A Supabase-v2-shaped session with a ~5-year expiry so getSession() never
 * triggers a (networked) refresh. */
export function buildSession() {
  const nowSec = Math.floor(Date.now() / 1000);
  const expSec = nowSec + 60 * 60 * 24 * 365 * 5;
  const accessToken = [
    b64url({ alg: "HS256", typ: "JWT" }),
    b64url({
      sub: E2E_USER.id,
      email: E2E_USER.email,
      role: "authenticated",
      aud: "authenticated",
      iat: nowSec,
      exp: expSec,
    }),
    "e2e-signature-not-verified-client-side",
  ].join(".");

  return {
    access_token: accessToken,
    refresh_token: "e2e-refresh-token",
    token_type: "bearer",
    expires_in: expSec - nowSec,
    expires_at: expSec,
    user: {
      id: E2E_USER.id,
      aud: "authenticated",
      role: "authenticated",
      email: E2E_USER.email,
      email_confirmed_at: new Date(0).toISOString(),
      phone: "",
      confirmed_at: new Date(0).toISOString(),
      app_metadata: { provider: "email", providers: ["email"] },
      user_metadata: {},
      identities: [],
      created_at: new Date(0).toISOString(),
      updated_at: new Date(0).toISOString(),
    },
  };
}

/** Seed the fake session so the next navigation boots signed-in. Call in a
 * test's beforeEach (before `page.goto`). */
export async function seedSession(page: Page): Promise<void> {
  const value = JSON.stringify(buildSession());
  await page.addInitScript(
    ([key, val]) => {
      try {
        window.localStorage.setItem(key, val);
      } catch {
        /* localStorage unavailable — nothing we can do; tests will surface it */
      }
    },
    [STORAGE_KEY, value] as [string, string],
  );
}
