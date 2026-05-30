/**
 * Central, validated read of `NEXT_PUBLIC_*` env vars.
 *
 * Why centralised:
 *
 *   * Every other module reads `env.apiBaseUrl` instead of
 *     `process.env.NEXT_PUBLIC_API_BASE_URL`. One typo, found once.
 *   * Zod surfaces "you forgot to set NEXT_PUBLIC_SUPABASE_URL" at
 *     module-load time instead of as a confusing runtime crash later.
 *
 * `NEXT_PUBLIC_*` is inlined at build time, so missing prod vars
 * surface at `next build` — not at first request. That's the right
 * place to fail.
 *
 * Server-only vars (no `NEXT_PUBLIC_` prefix) would go in a second
 * schema and a second exported object so a server import can never
 * accidentally leak into a client bundle. Phase 2 has none yet, so we
 * keep only the public side here.
 */

import { z } from "zod";

const publicSchema = z.object({
  /**
   * Backend base URL the browser bundle calls. Undefined in local dev
   * falls back to `http://localhost:8000`. Explicit empty string means
   * same-origin `/api/v1/*`, which is the safest production default
   * behind Caddy.
   */
  NEXT_PUBLIC_API_BASE_URL: z
    .union([z.string().url(), z.literal("")])
    .optional()
    .default("http://localhost:8000"),

  /** Supabase project URL — required once protected routes ship. */
  NEXT_PUBLIC_SUPABASE_URL: z
    .string()
    .url()
    .optional()
    .or(z.literal("").transform(() => undefined)),

  /** Supabase anon (publishable) key — safe to ship to the browser. */
  NEXT_PUBLIC_SUPABASE_ANON_KEY: z
    .string()
    .min(20)
    .optional()
    .or(z.literal("").transform(() => undefined)),
});

const parsed = publicSchema.safeParse({
  NEXT_PUBLIC_API_BASE_URL: process.env.NEXT_PUBLIC_API_BASE_URL,
  NEXT_PUBLIC_SUPABASE_URL: process.env.NEXT_PUBLIC_SUPABASE_URL,
  NEXT_PUBLIC_SUPABASE_ANON_KEY: process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY,
});

if (!parsed.success) {
  const issues = parsed.error.issues
    .map((i) => `  • ${i.path.join(".")}: ${i.message}`)
    .join("\n");
  throw new Error(
    `Invalid environment configuration. Check your .env.local:\n${issues}`,
  );
}

const raw = parsed.data;

/**
 * The public, validated env object. Import from here, never read
 * `process.env` directly elsewhere.
 */
export const env = {
  apiBaseUrl:
    raw.NEXT_PUBLIC_API_BASE_URL === ""
      ? ""
      : raw.NEXT_PUBLIC_API_BASE_URL.replace(/\/+$/, ""),
  supabaseUrl: raw.NEXT_PUBLIC_SUPABASE_URL,
  supabaseAnonKey: raw.NEXT_PUBLIC_SUPABASE_ANON_KEY,
  /** True iff both Supabase vars are configured. */
  supabaseConfigured:
    Boolean(raw.NEXT_PUBLIC_SUPABASE_URL) &&
    Boolean(raw.NEXT_PUBLIC_SUPABASE_ANON_KEY),
} as const;

export type Env = typeof env;
