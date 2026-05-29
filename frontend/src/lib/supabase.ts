/**
 * Browser-side Supabase client singleton.
 *
 * Phase 2 scope: we set up the client and expose a `getSession()` helper
 * so a later phase can call protected backend routes with a real JWT.
 * No login UI is wired in this phase — that lands when /portfolios is
 * ported (Phase 3). Anon access still works for /api/v1/risk/score.
 *
 * The client is lazy: when the Supabase env vars are missing,
 * `getSupabase()` returns null and `getAccessToken()` returns null
 * instead of crashing at module load. That keeps the public /score
 * page renderable on a contributor's machine that has no `.env.local`.
 */

import { createClient, SupabaseClient } from "@supabase/supabase-js";
import { env } from "./env";

let cached: SupabaseClient | null = null;

export function getSupabase(): SupabaseClient | null {
  if (cached) return cached;
  if (!env.supabaseConfigured) return null;
  cached = createClient(env.supabaseUrl!, env.supabaseAnonKey!, {
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
 * the user is signed out OR when Supabase env vars are missing. Use to
 * seed `apiFetch({ authToken })` on protected calls.
 */
export async function getAccessToken(): Promise<string | null> {
  const client = getSupabase();
  if (!client) return null;
  const { data } = await client.auth.getSession();
  return data.session?.access_token ?? null;
}
