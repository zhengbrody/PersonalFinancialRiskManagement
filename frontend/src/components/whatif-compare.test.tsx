import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { WhatIfCompare } from "./whatif-compare";
import type { ScoreResponse } from "@/lib/schemas";

function score(overall: number, vol: number, topW: number | null = 0.3): ScoreResponse {
  return {
    overall_score: overall,
    metrics: {
      annual_volatility: vol,
      var_95_daily: 0.02,
      sharpe_ratio: 0.9,
      beta_to_benchmark: 1.1,
      max_drawdown: -0.2,
    },
    concentration: topW == null ? null : { top_holding_weight: topW },
  } as unknown as ScoreResponse;
}

describe("WhatIfCompare", () => {
  it("renders before → after with goodness-directed delta tones", () => {
    render(
      <WhatIfCompare
        baseline={score(700, 0.2, 0.4)}
        sandbox={score(724, 0.16, 0.28)}
        onReset={() => {}}
      />,
    );
    const strip = screen.getByTestId("whatif-compare");
    expect(strip).toHaveTextContent("700");
    expect(strip).toHaveTextContent("724");
    expect(strip).toHaveTextContent("+24"); // score up
    expect(strip).toHaveTextContent("20.0%");
    expect(strip).toHaveTextContent("16.0%");
    expect(strip).toHaveTextContent("-4.0%"); // vol down = good
    expect(strip).toHaveTextContent("不构成投资建议");
  });

  it("missing concentration renders an em dash, not a crash", () => {
    render(
      <WhatIfCompare baseline={score(700, 0.2, null)} sandbox={score(710, 0.19, null)} onReset={() => {}} />,
    );
    expect(screen.getByTestId("whatif-compare")).toHaveTextContent("最大单一持仓");
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
  });

  it("reset button hands control back to the real book", () => {
    const onReset = vi.fn();
    render(<WhatIfCompare baseline={score(700, 0.2)} sandbox={score(650, 0.25)} onReset={onReset} />);
    fireEvent.click(screen.getByRole("button", { name: /返回真实账本/ }));
    expect(onReset).toHaveBeenCalledTimes(1);
  });
});
