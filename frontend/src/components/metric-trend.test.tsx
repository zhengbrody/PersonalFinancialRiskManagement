/**
 * MetricTrend: renders a sparkline once there are ≥2 snapshots; renders nothing
 * with fewer (not enough history). Self-fetches via useSnapshotHistory.
 */

import { afterEach, describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import { renderWithQuery } from "@/test-utils";

vi.mock("@/lib/auth-context", () => ({
  useAuth: () => ({ user: { id: "u-1" }, accessToken: "jwt", configured: true, loading: false }),
}));
// Stub the recharts wrapper (needs a sized parent jsdom lacks).
vi.mock("@/components/ui/chart-line", () => ({
  TimeSeriesChart: ({ data, ariaLabel }: { data: unknown[]; ariaLabel?: string }) => (
    <div data-testid="trend-chart" aria-label={ariaLabel}>
      {data.length} pts
    </div>
  ),
}));

import { MetricTrend } from "./metric-trend";

function mockJson(snapshots: unknown[]) {
  return new Response(JSON.stringify({ data: { snapshots }, error: null, meta: { request_id: "r" } }), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => vi.restoreAllMocks());

describe("MetricTrend", () => {
  it("renders the sparkline with ≥2 snapshots", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      mockJson([
        { as_of: "2026-05-20", overall_score: 540 },
        { as_of: "2026-05-28", overall_score: 612 },
      ]),
    );
    renderWithQuery(<MetricTrend metric="overall_score" title="Health score over time" kind="score" />);
    expect(await screen.findByText("Health score over time")).toBeInTheDocument();
    expect(screen.getByTestId("trend-chart")).toHaveTextContent("2 pts");
  });

  it("renders nothing with a single snapshot", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      mockJson([{ as_of: "2026-05-28", overall_score: 612 }]),
    );
    const { container } = renderWithQuery(
      <MetricTrend metric="overall_score" title="Health score over time" kind="score" />,
    );
    await new Promise((r) => setTimeout(r, 20));
    expect(container.querySelector('[data-testid="trend-chart"]')).toBeNull();
  });
});
