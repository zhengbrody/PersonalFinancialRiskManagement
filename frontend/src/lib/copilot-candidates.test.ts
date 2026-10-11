import { describe, expect, it } from "vitest";
import { ApiError } from "./api";
import { classifyRunStartFailure } from "./copilot-candidates";

// Messages copied from backend/app/services/copilot_jobs.py (queue_full / too_many_active).
const SAVED = "Saved as queued but not started: the analysis queue is full. Retry this same request shortly; it will not be duplicated.";
const NOT_SAVED = "The analysis queue is full. Nothing was saved; try again shortly.";

describe("classifyRunStartFailure", () => {
  it("maps the one-active-job limit to 'another analysis is running', not a generic error", () => {
    const failure = classifyRunStartFailure(new ApiError(429, "too_many_active_runs", "You already have a background analysis queued or running."));
    expect(failure.kind).toBe("active_elsewhere");
  });
  it("separates 'nothing was saved' from 'saved as queued'", () => {
    expect(classifyRunStartFailure(new ApiError(429, "analysis_queue_full", NOT_SAVED)).kind).toBe("queue_full_not_saved");
    const saved = classifyRunStartFailure(new ApiError(429, "analysis_queue_full", SAVED));
    expect(saved).toMatchObject({ kind: "queued_not_started", certain: true });
    if (saved.kind === "queued_not_started") {
      expect(saved.message).toMatch(/not started/);
      expect(saved.message).not.toMatch(/(?<!nothing )is running|now running/);
    }
  });
  it("treats an unrecognised queue-full variant as possibly saved (same-id retry is safe either way)", () => {
    expect(classifyRunStartFailure(new ApiError(429, "analysis_queue_full", "Queue full."))).toMatchObject({ kind: "queued_not_started", certain: false });
  });
  it("reports a refused record as a definite conflict", () => {
    expect(classifyRunStartFailure(new ApiError(409, "run_conflict", "This analysis record cannot be reused.")).kind).toBe("run_conflict");
  });
  it("leaves everything else to the caller", () => {
    expect(classifyRunStartFailure(new ApiError(503, "jobs_unavailable", "Not configured.")).kind).toBe("other");
    expect(classifyRunStartFailure(new TypeError("Failed to fetch")).kind).toBe("other");
  });
});
