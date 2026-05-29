/**
 * `apiFetch` contract tests.
 *
 * We're not testing the backend here — we're pinning the envelope-
 * unwrap behaviour every page relies on. If a refactor breaks any of
 * these, every page is silently broken; these tests are the canary.
 */

import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, apiFetch } from "./api";

function mockFetchOnce(
  responseBody: unknown,
  init: { status?: number } = {},
) {
  return vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
    new Response(JSON.stringify(responseBody), {
      status: init.status ?? 200,
      headers: { "Content-Type": "application/json" },
    }),
  );
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("apiFetch", () => {
  it("unwraps the envelope and returns just `data`", async () => {
    mockFetchOnce({
      data: { hello: "world" },
      error: null,
      meta: { request_id: "rid-1", elapsed_ms: 12 },
    });

    const result = await apiFetch<{ hello: string }>("/api/v1/health");
    expect(result).toEqual({ hello: "world" });
  });

  it("sends X-Request-Id and Content-Type headers on POST", async () => {
    const spy = mockFetchOnce({
      data: { ok: true },
      error: null,
      meta: { request_id: "rid-2" },
    });

    await apiFetch("/api/v1/risk/score", {
      method: "POST",
      body: { holdings: [] },
      requestId: "custom-rid",
    });

    const [, init] = spy.mock.calls[0] as [string, RequestInit];
    const headers = init.headers as Record<string, string>;
    expect(headers["X-Request-Id"]).toBe("custom-rid");
    expect(headers["Content-Type"]).toBe("application/json");
    expect(init.body).toBe('{"holdings":[]}');
  });

  it("attaches Authorization header when authToken is supplied", async () => {
    const spy = mockFetchOnce({
      data: { ok: true },
      error: null,
      meta: { request_id: "rid-3" },
    });
    await apiFetch("/api/v1/portfolios/me", { authToken: "jwt-here" });
    const [, init] = spy.mock.calls[0] as [string, RequestInit];
    const headers = init.headers as Record<string, string>;
    expect(headers.Authorization).toBe("Bearer jwt-here");
  });

  it("throws ApiError with server code + details on envelope error", async () => {
    mockFetchOnce(
      {
        data: null,
        error: {
          code: "validation_failed",
          message: "Bad body",
          details: { field: "holdings" },
        },
        meta: { request_id: "rid-4" },
      },
      { status: 422 },
    );

    await expect(apiFetch("/api/v1/risk/score", { method: "POST" })).rejects
      .toMatchObject({
        status: 422,
        code: "validation_failed",
        message: "Bad body",
        details: { field: "holdings" },
        requestId: "rid-4",
      });
  });

  it("throws ApiError with code 'network_error' when fetch itself rejects", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValueOnce(
      new TypeError("Failed to fetch"),
    );

    try {
      await apiFetch("/api/v1/health");
      expect.fail("apiFetch should have thrown");
    } catch (err) {
      expect(err).toBeInstanceOf(ApiError);
      expect((err as ApiError).code).toBe("network_error");
      expect((err as ApiError).status).toBe(0);
    }
  });

  it("throws ApiError with code 'bad_response' on non-JSON body", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response("<html>500</html>", {
        status: 500,
        headers: { "Content-Type": "text/html" },
      }),
    );

    try {
      await apiFetch("/api/v1/health");
      expect.fail("apiFetch should have thrown");
    } catch (err) {
      expect(err).toBeInstanceOf(ApiError);
      expect((err as ApiError).code).toBe("bad_response");
      expect((err as ApiError).status).toBe(500);
    }
  });
});
