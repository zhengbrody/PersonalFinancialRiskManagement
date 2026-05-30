/**
 * Browser-side Supabase client singleton.
 *
 * This is the browser auth client for the SaaS frontend. It owns the
 * persisted Supabase session, auto-refreshes access tokens, and exposes
 * the current JWT to FastAPI calls that need Row-Level Security.
 *
 * The client is lazy: when the Supabase env vars are missing,
 * `getSupabase()` returns null instead of crashing at module load.
 * That keeps public pages renderable on a contributor's machine that
 * has no `.env.local`. Read the live access token from
 * `useAuth().accessToken`, which is sourced from the same client.
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
