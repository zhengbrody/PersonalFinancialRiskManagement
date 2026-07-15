import { describe, expect, it } from "vitest";
import { computePrimaryAction, computeSecondary, journeySteps, type TodayInputs } from "./today-priority";

const base: TodayInputs = {
  hasPortfolio: true,
  hasHoldings: true,
  dataStale: false,
  dueReviewCount: 0,
  hasMaterialInsight: false,
  scoreDropped: false,
  hasStressTest: true,
  hasPlan: true,
  activePortfolioId: "pf1",
};

describe("computePrimaryAction — fixed priority order", () => {
  it("no portfolio → create", () => {
    expect(computePrimaryAction({ ...base, hasPortfolio: false }).kind).toBe("create_portfolio");
  });
  it("no holdings → add holdings (deep-links to the active book edit)", () => {
    const a = computePrimaryAction({ ...base, hasHoldings: false });
    expect(a.kind).toBe("add_holdings");
    expect(a.href).toBe("/portfolios/pf1/edit");
  });
  it("stale data outranks a due review", () => {
    expect(computePrimaryAction({ ...base, dataStale: true, dueReviewCount: 3 }).kind).toBe("fix_data");
  });
  it("due review outranks a material insight", () => {
    expect(
      computePrimaryAction({ ...base, dueReviewCount: 2, hasMaterialInsight: true }).kind,
    ).toBe("review_plan");
  });
  it("material insight outranks a score drop", () => {
    expect(
      computePrimaryAction({ ...base, hasMaterialInsight: true, scoreDropped: true }).kind,
    ).toBe("investigate_insight");
  });
  it("score drop outranks the first-stress-test nudge", () => {
    expect(computePrimaryAction({ ...base, scoreDropped: true, hasStressTest: false }).kind).toBe(
      "explain_change",
    );
  });
  it("no stress test → first stress test", () => {
    expect(computePrimaryAction({ ...base, hasStressTest: false }).kind).toBe("first_stress_test");
  });
  it("no plan → first plan", () => {
    expect(computePrimaryAction({ ...base, hasPlan: false }).kind).toBe("first_plan");
  });
  it("all done → review changes", () => {
    expect(computePrimaryAction(base).kind).toBe("review_changes");
  });
});

describe("computeSecondary", () => {
  it("never duplicates the primary and caps at 2", () => {
    const s = computeSecondary(base, "review_changes");
    expect(s.length).toBeLessThanOrEqual(2);
    expect(s.every((a) => a.kind !== "review_changes")).toBe(true);
  });
  it("is empty when there's no portfolio (the primary is create)", () => {
    expect(computeSecondary({ ...base, hasPortfolio: false }, "create_portfolio")).toEqual([]);
  });
});

describe("journeySteps", () => {
  it("marks the next incomplete step and reports allDone", () => {
    const r = journeySteps({ hasPortfolio: true, hasScore: true, hasDriverView: false, hasStressTest: false, hasPlan: false });
    expect(r.steps[2].done).toBe(false);
    expect(r.nextIndex).toBe(2);
    expect(r.allDone).toBe(false);
  });
  it("allDone when every step is complete", () => {
    const r = journeySteps({ hasPortfolio: true, hasScore: true, hasDriverView: true, hasStressTest: true, hasPlan: true });
    expect(r.allDone).toBe(true);
    expect(r.nextIndex).toBe(-1);
  });
});
