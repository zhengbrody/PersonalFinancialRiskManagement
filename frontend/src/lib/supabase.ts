/**
 * Browser-side Supabase client singleton.
 *
 * This is the browser auth client for the SaaS frontend. It owns the
 * persisted Supabase session, auto-refreshes access tokens, and exposes
 * the current JWT to FastAPI calls that need Row-Level Security.
 *
 * The client is lazy: when the Supabase env vars are missing,
 * `getSupabase()` returns null and `getAccessToken()` returns null
 * instead of crashing at module load. That keeps public pages renderable
 * on a contributor's machine that has no `.env.local`.
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
