/** Server-only resolver for signed portfolio share cards. */

import "server-only";

import { apiFetch } from "@/lib/api";
import { env } from "@/lib/env";
import { realShareCardSchema, type RealShareCard } from "@/lib/share-card";

function backendUrl(path: string): string {
  const internal = process.env.MINDMARKET_INTERNAL_API_BASE_URL?.replace(/\/+$/, "");
  if (internal) return `${internal}${path}`;
  if (env.apiBaseUrl) return `${env.apiBaseUrl}${path}`;
  // Canonical production topology: FastAPI is the `backend` compose service.
  return `http://backend:8000${path}`;
}

export async function resolveShareToken(token: string): Promise<RealShareCard> {
  const result = await apiFetch(backendUrl("/api/v1/share_cards/resolve"), {
    method: "POST",
    body: { token },
    schema: realShareCardSchema,
    cache: "no-store",
  });
  return result.card;
}
