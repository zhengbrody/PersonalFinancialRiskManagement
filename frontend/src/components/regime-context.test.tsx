import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { RegimeContext, RegimeContextLine } from "./regime-context";
import type { MlRegime } from "@/lib/queries";

const mockUse = vi.fn();
vi.mock("@/lib/queries", () => ({ useMlRegime: () => mockUse() }));

function regime(over: Partial<MlRegime> = {}): MlRegime {
  return {
    regime: "volatile",
    confidence: 0.72,
    class_probabilities: { volatile: 0.72, neutral: 0.2, stress: 0.05, risk_on: 0.03 },
    top_drivers: [
      { feature: "vix_level", label: "VIX level", value: 22, vs_normal: "above normal", importance: 0.2 },
    ],
    model_version: "regime-v1",
    trained_at: "2026-06-22T00:00:00Z",
    training_window: {},
    source: "model",
    last_updated: "2026-06-22",
    data_coverage: {},
    ...over,
  } as MlRegime;
}

describe("RegimeContext", () => {
  it("renders the risk state, confidence, drivers, and the not-advice provenance", () => {
    mockUse.mockReturnValue({ isLoading: false, data: regime() });
    render(<RegimeContext />);
    expect(screen.getByText("Risk-state model")).toBeInTheDocument();
    expect(screen.getByText("Elevated")).toBeInTheDocument(); // volatile -> "Elevated"
    expect(screen.getByText(/72% confidence/)).toBeInTheDocument();
    expect(screen.getByText("VIX level")).toBeInTheDocument();
    expect(screen.getByText(/does not change your Health Score/i)).toBeInTheDocument();
    expect(screen.getByText(/model regime-v1/)).toBeInTheDocument();
  });

  it("is hidden (null) when the model + data are unavailable", () => {
    mockUse.mockReturnValue({ isLoading: false, data: regime({ source: "unavailable", regime: null }) });
    const { container } = render(<RegimeContext />);
    expect(container.firstChild).toBeNull();
  });

  it("labels the heuristic fallback as such in the provenance", () => {
    mockUse.mockReturnValue({
      isLoading: false,
      data: regime({ source: "heuristic_fallback", model_version: null }),
    });
    render(<RegimeContext />);
    expect(screen.getByText(/current-vol estimate/)).toBeInTheDocument();
  });
});

describe("RegimeContextLine", () => {
  it("renders the compact context chip with the not-advice caveat", () => {
    mockUse.mockReturnValue({ isLoading: false, data: regime({ regime: "stress", confidence: 0.6 }) });
    render(<RegimeContextLine />);
    expect(screen.getByText("Stressed")).toBeInTheDocument();
    expect(screen.getByText(/does not change your Health Score/i)).toBeInTheDocument();
  });

  it("hides when unavailable", () => {
    mockUse.mockReturnValue({ isLoading: false, data: regime({ source: "unavailable", regime: null }) });
    const { container } = render(<RegimeContextLine />);
    expect(container.firstChild).toBeNull();
  });
});
