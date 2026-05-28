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

const DEFAULT_BASE = "http://localhost:8000";

function getBaseUrl(): string {
  // Browser bundles read NEXT_PUBLIC_* at build time; server reads at
  // runtime. Both code paths fall back to the dev default.
  if (typeof process !== "undefined" && process.env.NEXT_PUBLIC_API_BASE_URL) {
    return process.env.NEXT_PUBLIC_API_BASE_URL.replace(/\/+$/, "");
  }
  return DEFAULT_BASE;
}

function mintRequestId(): string {
  // Lightweight UUID-ish for log correlation; the backend echoes it
  // through `meta.request_id` so devtools→server logs are joinable.
  if (typeof crypto !== "undefined" && crypto.randomUUID) {
    return crypto.randomUUID();
  }
  return Math.random().toString(36).slice(2) + Date.now().toString(36);
}

export type ApiFetchOptions = Omit<RequestInit, "body"> & {
  body?: unknown;
  /** Bearer token for protected routes. Phase 2: usually undefined. */
  authToken?: string;
  /** Override the auto-minted request id. */
  requestId?: string;
};

export async function apiFetch<T>(
  path: string,
  opts: ApiFetchOptions = {},
): Promise<T> {
  const { body, authToken, requestId, headers, ...rest } = opts;
  const url = path.startsWith("http") ? path : `${getBaseUrl()}${path}`;
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
  let envelope: ApiEnvelope<T>;
  try {
    envelope = (await response.json()) as ApiEnvelope<T>;
  } catch {
    throw new ApiError(
      response.status,
      "bad_response",
      "Server returned a non-JSON response.",
      { status: response.status },
      id,
    );
  }

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
      envelope.meta?.request_id ?? id,
    );
  }

  // Success envelopes promise `data !== null` for endpoints that
  // declare a payload. If a route legitimately returns null, callers
  // should type T as `null` — we don't second-guess here.
  return envelope.data as T;
}
