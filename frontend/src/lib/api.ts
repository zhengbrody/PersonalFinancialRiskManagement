/**
 * `apiFetch<T>` — the single entry point to the MindMarket backend.
 *
 * Wraps `fetch()` and unwraps the response envelope defined in
 * ADR-0004:
 *
 *   { data: T | null, error: ApiErrorBody | null, meta: { ... } }
 *
 * On success it returns just the `data`. On HTTP failure OR an
 * envelope where `error !== null`, it throws `ApiError` carrying the
 * server-supplied `code` and `details` so React Query can surface a
 * targeted UI.
 *
 * One wrapper, one contract — every page/feature uses this; nothing
 * is allowed to talk to the backend with raw `fetch` because that's
 * how envelope-shape drift starts.
 */

import { z, type ZodType } from "zod";
import { env } from "./env";

export type ApiErrorBody = {
  code: string;
  message: string;
  details?: Record<string, unknown>;
};

export type ApiMeta = {
  request_id: string;
  elapsed_ms?: number;
};

export type ApiEnvelope<T> = {
  data: T | null;
  error: ApiErrorBody | null;
  meta: ApiMeta;
};

/**
 * Runtime guard for the envelope WRAPPER itself — `{ data, error, meta }`.
 *
 * We validate the wrapper on every response (cheap) so a misbehaving
 * proxy or a backend shape-drift surfaces as a clean `invalid_response`
 * ApiError instead of an `undefined` that blows up three components
 * deep. The `data` payload is left as `unknown` here; callers opt into
 * payload validation by passing a `schema` (see `apiFetch`).
 *
 * `looseObject` keeps unknown keys instead of stripping them, so adding
 * a field server-side never silently drops data the client reads.
 */
const envelopeSchema = z.looseObject({
  data: z.unknown().nullable(),
  error: z
    .looseObject({
      code: z.string(),
      message: z.string(),
      details: z.record(z.string(), z.unknown()).optional(),
    })
    .nullable(),
  meta: z.looseObject({
    request_id: z.string(),
    elapsed_ms: z.number().optional(),
  }),
});

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: Record<string, unknown>;
  readonly requestId?: string;

  constructor(
    status: number,
    code: string,
    message: string,
    details: Record<string, unknown> = {},
    requestId?: string,
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
    this.requestId = requestId;
  }
}

/**
 * True when an error is the "user has no usable active portfolio yet" class
 * (signed in but no holdings / nothing priceable / no market data). The
 * active-portfolio endpoints (score/risk/scenarios) all share these 422 codes,
 * so pages can show one "create a portfolio" CTA instead of re-listing codes.
 */
export function isNoPortfolioError(error: unknown): boolean {
  if (!(error instanceof ApiError)) return false;
  return (
    error.code === "no_active_portfolio" ||
    error.code === "no_priced_holdings" ||
    error.code === "no_market_data"
  );
}

function mintRequestId(): string {
  // Lightweight UUID-ish for log correlation; the backend echoes it
  // through `meta.request_id` so devtools→server logs are joinable.
  if (typeof crypto !== "undefined" && crypto.randomUUID) {
    return crypto.randomUUID();
  }
  return Math.random().toString(36).slice(2) + Date.now().toString(36);
}

export type ApiFetchOptions<T = unknown> = Omit<RequestInit, "body"> & {
  body?: unknown;
  /** Bearer token for protected routes. Phase 2: usually undefined. */
  authToken?: string;
  /** Override the auto-minted request id. */
  requestId?: string;
  /**
   * Zod schema for the `data` payload. When supplied, a success
   * response is parsed through it and a mismatch throws an
   * `invalid_response` ApiError — turning backend shape-drift into a
   * clean, attributable error instead of an `undefined` crash inside a
   * component. Strongly recommended for every typed endpoint.
   */
  schema?: ZodType<T>;
  /**
   * Endpoints that legitimately return `null` on success (rare) set
   * this. Otherwise a `{ data: null, error: null }` 200 is treated as a
   * contract violation and throws `empty_response`, rather than handing
   * the caller a `null` typed as `T`.
   */
  allowNull?: boolean;
};

export async function apiFetch<T>(
  path: string,
  opts: ApiFetchOptions<T> = {},
): Promise<T> {
  const { body, authToken, requestId, headers, schema, allowNull, ...rest } =
    opts;
  const url = path.startsWith("http") ? path : `${env.apiBaseUrl}${path}`;
  const id = requestId ?? mintRequestId();

  const finalHeaders: Record<string, string> = {
    "Content-Type": "application/json",
    "X-Request-Id": id,
    ...((headers as Record<string, string>) ?? {}),
  };
  if (authToken) {
    finalHeaders.Authorization = `Bearer ${authToken}`;
  }

  let response: Response;
  try {
    response = await fetch(url, {
      ...rest,
      headers: finalHeaders,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch (err) {
    // Network-level failure (CORS, DNS, offline) — surface as ApiError
    // so callers handle one error shape end-to-end.
    throw new ApiError(
      0,
      "network_error",
      err instanceof Error ? err.message : "Network request failed.",
      {},
      id,
    );
  }

  // The backend always returns JSON, but a misbehaving proxy might not.
  let rawJson: unknown;
  try {
    rawJson = await response.json();
  } catch {
    throw new ApiError(
      response.status,
      "bad_response",
      "Server returned a non-JSON response.",
      { status: response.status },
      id,
    );
  }

  // Validate the envelope WRAPPER shape before trusting any field on it.
  // A 200 that isn't `{ data, error, meta }` is contract drift, not data.
  const parsedEnvelope = envelopeSchema.safeParse(rawJson);
  if (!parsedEnvelope.success) {
    throw new ApiError(
      response.status,
      "invalid_response",
      "Server response did not match the API envelope contract.",
      { status: response.status, issues: parsedEnvelope.error.issues },
      id,
    );
  }
  const envelope = parsedEnvelope.data;
  const envRequestId = envelope.meta.request_id ?? id;

  if (envelope.error || !response.ok) {
    const e = envelope.error ?? {
      code: "http_error",
      message: `Request failed with status ${response.status}`,
    };
    throw new ApiError(
      response.status,
      e.code,
      e.message,
      e.details ?? {},
      envRequestId,
    );
  }

  // Caller opted into payload validation: parse `data` through their
  // schema so shape-drift surfaces here, not as `undefined` in the UI.
  if (schema) {
    const parsed = schema.safeParse(envelope.data);
    if (!parsed.success) {
      throw new ApiError(
        response.status,
        "invalid_response",
        "Server response payload failed validation.",
        { issues: parsed.error.issues },
        envRequestId,
      );
    }
    return parsed.data;
  }

  // No schema: a success envelope still promises a non-null payload for
  // endpoints that declare one. Hand back `null` only when the caller
  // explicitly allows it; otherwise treat it as a contract violation so
  // the bug is one clean error, not a downstream property-access crash.
  if (envelope.data === null || envelope.data === undefined) {
    if (allowNull) return envelope.data as T;
    throw new ApiError(
      response.status,
      "empty_response",
      "Server returned an empty payload for an endpoint that should return data.",
      {},
      envRequestId,
    );
  }

  return envelope.data as T;
}
