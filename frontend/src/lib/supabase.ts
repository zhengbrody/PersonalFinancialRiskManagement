/**
 * Browser-side Supabase client singleton.
 *
 * Phase 2 scope: we set up the client and expose a `getSession()` helper
 * so a later phase can call protected backend routes with a real JWT.
 * No login UI is wired in this phase — that lands when /portfolios is
 * ported (Phase 3). Anon access still works for /api/v1/risk/score.
 *
 * The client is lazy: if the public env vars are missing we return a
 * stub that throws when used, instead of crashing at module load.
 * That way the public /score page renders cleanly when a contributor
 * forgets `.env.local`.
 */

import { createClient, SupabaseClient } from "@supabase/supabase-js";

let cached: SupabaseClient | null = null;

function readEnv(): { url: string; anonKey: string } | null {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  if (!url || !anonKey) return null;
  return { url, anonKey };
}

export function getSupabase(): SupabaseClient | null {
  if (cached) return cached;
  const env = readEnv();
  if (!env) return null;
  cached = createClient(env.url, env.anonKey, {
    auth: {
      persistSession: true,
      autoRefreshToken: true,
      detectSessionInUrl: true,
    },
  });
  return cached;
}

/**
 * Convenience: pull the current access token, if any. Returns null when
 * the user is signed out OR when Supabase env vars are missing.
 * Use this to seed `apiFetch({ authToken })` on protected calls.
 */
export async function getAccessToken(): Promise<string | null> {
  const client = getSupabase();
  if (!client) return null;
  const { data } = await client.auth.getSession();
  return data.session?.access_token ?? null;
}
