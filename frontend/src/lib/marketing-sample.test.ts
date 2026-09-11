import { describe, expect, it } from "vitest";
import { sampleComparison, SAMPLE_BOOK } from "./marketing-sample";

describe("educational comparison accounting", () => {
  it("computes the documented numbers independently of UI", () => {
    const result = sampleComparison(25, -20, "cash");
    expect(result.proceeds).toBe(10000);
    expect(result.before.loss).toBe(24000);
    expect(result.after).toEqual({ growth: 30000, stocks: 90000, cash: 10000, margin: 20000, equity: 80000, loss: 21000, concentration: 1 / 3 });
  });
  it("conserves equity for every supported step and never treats debt repayment as extra stress protection", () => {
    for (let reduction = 0; reduction <= 50; reduction += 5) {
      for (const shock of [-10, -20, -30]) {
        const cash = sampleComparison(reduction, shock, "cash");
        const repay = sampleComparison(reduction, shock, "repay");
        for (const result of [cash, repay]) {
          expect(result.before.equity).toBe(80000);
          expect(result.after.equity).toBe(80000);
          expect(result.after.loss).toBeLessThanOrEqual(result.before.loss);
          expect(result.after.margin).toBeGreaterThanOrEqual(0);
        }
        expect(repay.after.loss).toBe(cash.after.loss);
        expect(cash.after.cash - repay.after.cash).toBe(cash.after.margin - repay.after.margin);
      }
    }
    expect(SAMPLE_BOOK).toEqual({ growth: 40000, other: 60000, margin: 20000 });
  });
  it("zero reduction leaves the portfolio unchanged", () => {
    const result = sampleComparison(0, -20, "repay");
    expect(result.after).toEqual(result.before);
  });
  it.each([NaN, Infinity, -1, 51])("rejects invalid reduction %s", (value) => {
    expect(() => sampleComparison(value, -20, "cash")).toThrow(RangeError);
  });
  it.each([NaN, Infinity, 1, -31])("rejects invalid shock %s", (value) => {
    expect(() => sampleComparison(25, value, "cash")).toThrow(RangeError);
  });
});
