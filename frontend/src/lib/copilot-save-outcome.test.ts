import { describe, expect, it } from "vitest";
import { ApiError } from "./api";
import { classifySaveFailure, COMPARISON_SETTLED_CODES, FUNDING_PLAN_SETTLED_CODES, PUT_PLAN_SETTLED_CODES } from "./copilot-save-outcome";

const messages = { uncertainSave: "UNCERTAIN-SAVE", uncertainRead: "UNCERTAIN-READ", vanished: "VANISHED" };

describe("classifySaveFailure", () => {
  it("reports a pre-commit rejection as definite with the server's reason", () => {
    const failure = classifySaveFailure(new ApiError(409, "funding_plan_expired", "Capture new scenarios before saving."), {
      settled: FUNDING_PLAN_SETTLED_CODES, missing: "funding_plan_missing", retrieve: false, ...messages,
    });
    expect(failure).toEqual({ definite: true, vanished: false, message: "Capture new scenarios before saving." });
  });

  it.each([
    ["network failure", new ApiError(0, "network_error", "Failed to fetch")],
    ["post-commit authentication check", new ApiError(409, "untrusted_funding_plan", "Saved funding evidence could not be authenticated.")],
    ["server-declared unconfirmed write", new ApiError(503, "funding_save_unconfirmed", "Saving was not confirmed.")],
    ["unknown code", new ApiError(500, "server_error", "boom")],
    ["non-API error", new Error("Saved result does not match the original calculation.")],
  ])("keeps a %s uncertain and retryable instead of parroting its message", (_label, error) => {
    const failure = classifySaveFailure(error, { settled: FUNDING_PLAN_SETTLED_CODES, missing: "funding_plan_missing", retrieve: false, ...messages });
    expect(failure).toEqual({ definite: false, vanished: false, message: "UNCERTAIN-SAVE" });
  });

  it("uses the read wording when a read-back fails for an unknown reason", () => {
    const failure = classifySaveFailure(new ApiError(0, "network_error", "offline"), { settled: COMPARISON_SETTLED_CODES, missing: "saved_comparison_missing", retrieve: true, ...messages });
    expect(failure).toEqual({ definite: false, vanished: false, message: "UNCERTAIN-READ" });
  });

  it("treats a missing record on the read path as vanished, but never on the write path", () => {
    const missing = new ApiError(404, "saved_comparison_missing", "Not found.");
    expect(classifySaveFailure(missing, { settled: COMPARISON_SETTLED_CODES, missing: "saved_comparison_missing", retrieve: true, ...messages }))
      .toEqual({ definite: true, vanished: true, message: "VANISHED" });
    expect(classifySaveFailure(missing, { settled: COMPARISON_SETTLED_CODES, missing: "saved_comparison_missing", retrieve: false, ...messages }))
      .toEqual({ definite: true, vanished: false, message: "Not found." });
  });

  it("never lists a code that can follow the commit as settled", () => {
    for (const code of ["comparison_conflict", "untrusted_saved_comparison", "comparison_save_unconfirmed"]) expect(COMPARISON_SETTLED_CODES).not.toContain(code);
    for (const code of ["funding_plan_conflict", "untrusted_funding_plan", "funding_save_unconfirmed"]) expect(FUNDING_PLAN_SETTLED_CODES).not.toContain(code);
    for (const code of ["put_plan_conflict", "untrusted_put_plan", "put_save_unconfirmed"]) expect(PUT_PLAN_SETTLED_CODES).not.toContain(code);
  });
});
