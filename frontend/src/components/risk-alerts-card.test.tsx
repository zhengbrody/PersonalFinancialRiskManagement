import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

const { useRiskAlertsMock, useAlertStatesMock, upsertMock, trackMock, portfolioCtxMock } =
  vi.hoisted(() => ({
    useRiskAlertsMock: vi.fn(),
    useAlertStatesMock: vi.fn(),
    upsertMock: vi.fn(),
    trackMock: vi.fn(),
    portfolioCtxMock: vi.fn(),
  }));
vi.mock("@/lib/queries", () => ({
  useRiskAlerts: (input: unknown) => useRiskAlertsMock(input),
  useAlertStates: (id: unknown) => useAlertStatesMock(id),
  useUpsertAlertState: () => ({ mutate: upsertMock }),
}));
vi.mock("@/lib/analytics", () => ({ track: trackMock }));
vi.mock("@/lib/portfolio-context", () => ({
  usePortfolioContext: () => portfolioCtxMock(),
}));

import { RiskAlertsCard } from "./risk-alerts-card";

const ALERTS = [
  {
    type: "concentration",
    severity: "high",
    headline: "NVDA drives 55% of your risk",
    detail: "A single position concentrates much of your downside in NVDA.",
    metric: "55% of portfolio VaR",
    ask_copilot: "Why is NVDA the biggest risk in my portfolio?",
  },
  {
    type: "margin",
    severity: "elevated",
    headline: "You're running 1.8× leverage",
    detail: "Margin amplifies losses.",
    metric: "1.80× gross/equity",
    ask_copilot: "Am I over-leveraged?",
  },
  {
    type: "volatility",
    severity: "moderate",
    headline: "High volatility — 24%/yr",
    detail: "Bigger swings.",
    metric: "24% ann. vol",
    ask_copilot: "Why is my portfolio so volatile?",
  },
];

function setup({
  alerts = ALERTS as unknown,
  isPending = false,
  states = [] as unknown[],
  portfolioId = "p1" as string | null,
} = {}) {
  useRiskAlertsMock.mockReturnValue({ data: alerts, isPending });
  useAlertStatesMock.mockReturnValue({ data: { states } });
  portfolioCtxMock.mockReturnValue({ activePortfolioId: portfolioId });
}

describe("RiskAlertsCard", () => {
  it("renders the top alerts (default limit 2) with severity + Ask Copilot deep link", () => {
    setup();
    render(<RiskAlertsCard input={{ leverage: 1.8 }} source="score" />);

    expect(screen.getByText("What to watch")).toBeInTheDocument();
    expect(screen.getByText("NVDA drives 55% of your risk")).toBeInTheDocument();
    expect(screen.getByText("You're running 1.8× leverage")).toBeInTheDocument();
    // limited to 2 → the moderate vol alert is not shown as a row…
    expect(screen.queryByText("High volatility — 24%/yr")).not.toBeInTheDocument();
    // …but the "see all" link appears since there are more.
    expect(screen.getByText(/see all risks in copilot/i)).toBeInTheDocument();
    // each row deep-links the question into the Copilot.
    const link = screen.getAllByRole("link", { name: /ask copilot/i })[0];
    expect(link.getAttribute("href")).toContain("/copilot?q=");
    expect(decodeURIComponent(link.getAttribute("href") ?? "")).toContain("Why is NVDA");
  });

  it("renders nothing when there are no alerts, no input, or still loading", () => {
    setup({ alerts: [] });
    const { container: a } = render(<RiskAlertsCard input={{ leverage: 1 }} source="score" />);
    expect(a.firstChild).toBeNull();

    setup({ alerts: undefined, isPending: true });
    const { container: b } = render(<RiskAlertsCard input={{}} source="score" />);
    expect(b.firstChild).toBeNull();

    setup();
    const { container: c } = render(<RiskAlertsCard input={null} source="score" />);
    expect(c.firstChild).toBeNull();
  });

  it("hides a resolved alert and resolving one persists state per portfolio", () => {
    // The high concentration alert is already resolved → hidden; the next two show.
    setup({ states: [{ portfolio_id: "p1", alert_key: "concentration:high", state: "resolved" }] });
    render(<RiskAlertsCard input={{ leverage: 1.8 }} source="score" />);

    expect(screen.queryByText("NVDA drives 55% of your risk")).not.toBeInTheDocument();
    expect(screen.getByText("You're running 1.8× leverage")).toBeInTheDocument();

    // Resolve the margin alert → upsert with its type:severity key, value-free track.
    fireEvent.click(screen.getAllByRole("button", { name: /^resolve$/i })[0]);
    expect(upsertMock).toHaveBeenCalledWith(
      expect.objectContaining({ portfolio_id: "p1", alert_key: "margin:elevated", state: "resolved" }),
    );
    expect(trackMock).toHaveBeenCalledWith("alert_lifecycle_changed", { state: "resolved" });
  });

  it("shows no lifecycle buttons without an active portfolio", () => {
    setup({ portfolioId: null });
    render(<RiskAlertsCard input={{ leverage: 1.8 }} source="score" />);
    expect(screen.getByText("NVDA drives 55% of your risk")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^resolve$/i })).not.toBeInTheDocument();
  });
});
