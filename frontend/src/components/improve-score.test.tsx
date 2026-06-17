import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { buildLevers, ImproveScore } from "./improve-score";
import type { ScoreResponse } from "@/lib/schemas";

/** Minimal score fixture — only the fields the levers read (cast loosely; the
 * unit under test is the deterministic derivation, not schema validation). */
function makeScore(over: {
  metrics?: Record<string, number>;
  concentration?: Record<string, unknown> | null;
  target?: Record<string, unknown>;
  options?: { flags: string[] } | null;
}): ScoreResponse {
  return {
    overall_score: 600,
    risk_preference: 3,
    risk_target: over.target ?? { label: "Balanced growth", annual_volatility: 0.14, beta: 0.8 },
    metrics: {
      annual_volatility: 0.12,
      beta_to_benchmark: 0.8,
      max_drawdown: -0.12,
      sharpe_ratio: 1.1,
      leverage: 1.0,
      ...(over.metrics ?? {}),
    },
    dimensions: {},
    concentration: over.concentration === undefined ? null : over.concentration,
    options: over.options ?? null,
  } as unknown as ScoreResponse;
}

describe("buildLevers (deterministic)", () => {
  it("a high-risk, concentrated, over-target book surfaces ranked levers", () => {
    const levers = buildLevers(
      makeScore({
        metrics: { annual_volatility: 0.28, max_drawdown: -0.41, sharpe_ratio: 0.3, beta_to_benchmark: 1.6 },
        concentration: {
          num_holdings: 5,
          top_holding_ticker: "NVDA",
          top_holding_weight: 0.42,
          top_sector: "Information Technology",
          top_sector_weight: 0.6,
        },
      }),
    );
    expect(levers.length).toBe(3); // capped at top-3
    // Biggest lever first (volatility 28% vs 14% target → severity 3).
    expect(levers[0].sev).toBe(3);
    // The concentrated name shows up grounded in its real weight.
    const joined = levers.map((l) => `${l.title} ${l.detail}`).join(" ");
    expect(joined).toMatch(/NVDA/);
    expect(joined).toMatch(/42%/);
  });

  it("a balanced book at/under target yields NO levers", () => {
    expect(buildLevers(makeScore({}))).toEqual([]);
  });

  it("margin shows up as a lever", () => {
    const levers = buildLevers(makeScore({ metrics: { leverage: 1.8 } }));
    expect(levers.some((l) => l.key === "margin")).toBe(true);
  });
});

describe("ImproveScore", () => {
  it("renders levers with a prefilled Ask-Copilot deep link; nothing for a healthy book", () => {
    const { rerender, container } = render(
      <ImproveScore
        score={makeScore({
          concentration: { num_holdings: 3, top_holding_ticker: "TSLA", top_holding_weight: 0.5 },
        })}
      />,
    );
    expect(screen.getByText(/How to improve this score/i)).toBeInTheDocument();
    const ask = screen.getAllByRole("link", { name: /ask copilot/i })[0];
    expect(ask.getAttribute("href")).toMatch(/^\/copilot\?q=/);

    rerender(<ImproveScore score={makeScore({})} />);
    expect(container).toBeEmptyDOMElement(); // healthy → renders nothing
  });
});
