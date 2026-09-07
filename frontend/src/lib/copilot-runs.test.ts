import { afterEach, describe, expect, it, vi } from "vitest";
import { loadSavedRun, savedRunSchema } from "./copilot-runs";

const id = "44444444-4444-4444-8444-444444444444";
const book = "33333333-3333-4333-8333-333333333333";
const running = { id, portfolio_id: book, state: "running", created_at: "2026-09-06T12:00:00Z", updated_at: "2026-09-06T12:00:00Z", expires_at: "2026-09-06T12:10:00Z", error_code: null, result: null };
const envelope = (data: unknown) => new Response(JSON.stringify({ data, error: null, meta: { request_id: "test" } }));

afterEach(() => { vi.restoreAllMocks(); vi.useRealTimers(); });

describe("saved check transport", () => {
  it("polls an existing running ID without repeating the start POST", async () => {
    vi.useFakeTimers();
    const fetch = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(envelope(running))
      .mockResolvedValueOnce(envelope({ ...running, state: "failed", error_code: "analysis_failed" }));
    const pending = loadSavedRun(id, book, "jwt", new AbortController().signal, "start");
    await vi.advanceTimersByTimeAsync(2500);
    expect((await pending).state).toBe("failed");
    expect(fetch.mock.calls.map((call) => call[1]?.method)).toEqual(["POST", "GET"]);
  });
  it("aborting a poll removes its timer and never starts another request", async () => {
    vi.useFakeTimers();
    const fetch = vi.spyOn(globalThis, "fetch").mockResolvedValue(envelope(running));
    const ac = new AbortController();
    const pending = loadSavedRun(id, book, "jwt", ac.signal, "retrieve");
    const rejected = expect(pending).rejects.toThrow("Aborted");
    await vi.advanceTimersByTimeAsync(1);
    ac.abort();
    await rejected;
    await vi.advanceTimersByTimeAsync(10_000);
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(0);
  });
  it("does not automatically retry a failed lookup as a new analysis", async () => {
    const fetch = vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("network"));
    await expect(loadSavedRun(id, book, "jwt", new AbortController().signal, "retrieve")).rejects.toThrow("network");
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch.mock.calls[0][1]?.method).toBe("GET");
  });
  it("rejects a completed state without an engine result", () => {
    expect(savedRunSchema.safeParse({ ...running, state: "completed" }).success).toBe(false);
  });
});
