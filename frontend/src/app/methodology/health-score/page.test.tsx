import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";

// MarketingShell is auth-aware (useAuth) — drive it per test.
type AuthState = { user: { id: string } | null; configured: boolean; loading: boolean };
const authMock = vi.fn((): AuthState => ({ user: null, configured: true, loading: false }));
vi.mock("@/lib/auth-context", () => ({ useAuth: () => authMock() }));

import HealthScoreMethodologyPage from "./page";
import { SCORE_METHODOLOGY_VERSION } from "@/lib/score-methodology";

beforeEach(() => authMock.mockReturnValue({ user: null, configured: true, loading: false }));

describe("Health Score methodology page", () => {
  it("renders every required methodology section", () => {
    render(<HealthScoreMethodologyPage />);
    expect(
      screen.getByRole("heading", { name: /How the Health Score is calculated/i, level: 1 }),
    ).toBeInTheDocument();

    const body = document.body.textContent ?? "";
    // The version is shown (auditable).
    expect(body).toContain(SCORE_METHODOLOGY_VERSION);
    // All the required topics are covered.
    for (const needle of [
      "three dimensions",
      "risk preference",
      "History window",
      "SPY",
      "Risk-free rate",
      "Monte Carlo VaR", // the 21-day MC VaR vs historical daily VaR distinction
      "1-day VaR",
      "Leverage",
      "Options",
      "stabilization",
      "not a prediction of future returns",
      "Versioning and changelog",
    ]) {
      expect(body).toContain(needle);
    }
    // Weights are shown.
    expect(body).toContain("35%");
    expect(body).toContain("30%");
  });

  it("does NOT claim to be an 'industry standard score'", () => {
    render(<HealthScoreMethodologyPage />);
    const body = (document.body.textContent ?? "").toLowerCase();
    expect(body).not.toContain("industry standard");
  });

  it("links to the score + learn pages", () => {
    render(<HealthScoreMethodologyPage />);
    expect(screen.getByRole("link", { name: /See your Health Score/i })).toHaveAttribute(
      "href",
      "/score",
    );
  });
});
