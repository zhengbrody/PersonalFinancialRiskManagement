/** Educational, local-only arithmetic. Not the production risk engine or live data. */
export const SAMPLE_BOOK = Object.freeze({ growth: 40_000, other: 60_000, margin: 20_000 });
export type ProceedsUse = "cash" | "repay";

export function sampleComparison(reductionPct: number, shockPct: number, proceedsUse: ProceedsUse) {
  if (!Number.isFinite(reductionPct) || reductionPct < 0 || reductionPct > 50 ||
      !Number.isFinite(shockPct) || shockPct > 0 || shockPct < -30 ||
      !["cash", "repay"].includes(proceedsUse)) {
    throw new RangeError("Unsupported educational scenario");
  }
  const proceeds = SAMPLE_BOOK.growth * reductionPct / 100;
  const repaid = proceedsUse === "repay" ? Math.min(proceeds, SAMPLE_BOOK.margin) : 0;
  const describe = (growth: number, cash: number, margin: number) => {
    const stocks = growth + SAMPLE_BOOK.other;
    const equity = stocks + cash - margin;
    // Fixed illustrative sensitivities, not estimated betas or return forecasts.
    const loss = -(growth * 1.5 + SAMPLE_BOOK.other) * shockPct / 100;
    return { growth, stocks, cash, margin, equity, loss, concentration: growth / stocks };
  };
  return {
    before: describe(SAMPLE_BOOK.growth, 0, SAMPLE_BOOK.margin),
    after: describe(SAMPLE_BOOK.growth - proceeds, proceeds - repaid, SAMPLE_BOOK.margin - repaid),
    proceeds,
  };
}
