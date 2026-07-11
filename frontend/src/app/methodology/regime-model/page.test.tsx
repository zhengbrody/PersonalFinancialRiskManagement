import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";

type AuthState = { user: { id: string } | null; configured: boolean; loading: boolean };
const authMock = vi.fn((): AuthState => ({ user: null, configured: true, loading: false }));
vi.mock("@/lib/auth-context", () => ({ useAuth: () => authMock() }));

import RegimeModelCardPage from "./page";

const CARD = {
  available: true,
  model_version: "regime-v1.1.0",
  trained_at: "2026-07-08T18:53:57.499427+00:00",
  estimator: "HistGradientBoostingClassifier",
  headline:
    "On 4-class regime accuracy the model (0.490) does not beat a persistence baseline (0.523) — classification is weak. Its validated value is ranking elevated-risk probability. It is a probability-ranking signal, not a classifier, and not a price or return forecast.",
  intended_use: "An experimental, probability-ranking signal for elevated-risk pressure.",
  not_for: ["Predicting prices, returns, or market direction."],
  limitations: ["On 4-class regime accuracy it loses to a persistence baseline."],
  excluded_signals: "CNN Fear & Greed is deliberately excluded from the model.",
  classes: ["risk_on", "neutral", "volatile", "stress"],
  class_definitions: [{ label: "Elevated", key: "volatile", definition: "between 18% and 28%" }],
  features: [{ name: "vol_63d", importance: 0.168 }],
  training_window: { start: "2012-06-12", end: "2026-06-22", rows: 3526 },
  class_distribution: { risk_on: 1860, neutral: 931, volatile: 554, stress: 181 },
  cv_accuracy: 0.4896,
  persistence_baseline_accuracy: 0.523,
  majority_baseline_cv_accuracy: 0.4995,
  holdout_accuracy: 0.5142,
  holdout_majority_baseline_accuracy: 0.5028,
  elevated_risk_auc: 0.7701,
  brier: 0.1042,
  brier_base_rate: 0.1133,
  elevated_base_rate: 0.1303,
  holdout_size: 706,
  calibration_bins: [
    { bin: "[0.0, 0.1)", n: 361, mean_predicted: 0.0393, observed_frequency: 0.0582 },
  ],
};

beforeEach(() => {
  authMock.mockReturnValue({ user: null, configured: true, loading: false });
  global.fetch = vi.fn(async () => ({ ok: true, json: async () => ({ data: CARD }) })) as never;
});
afterEach(() => vi.restoreAllMocks());

describe("regime model card page", () => {
  it("renders honest, artifact-sourced metrics and does not over-claim a classifier", async () => {
    render(await RegimeModelCardPage());
    expect(
      screen.getByRole("heading", { name: /Market risk-state model/i, level: 1 }),
    ).toBeInTheDocument();
    const body = document.body.textContent ?? "";
    expect(body).toContain("regime-v1.1.0");
    expect(body).toContain("0.523"); // the persistence baseline it loses to
    expect(body).toContain("0.770"); // elevated-risk ROC-AUC (the signal)
    expect(body).toContain("0.1042"); // Brier
    expect(body).toContain("does not beat a persistence baseline");
    expect(body).toContain("probability-ranking signal");
    // Must NOT frame it as a reliable/validated classifier.
    expect(body.toLowerCase()).not.toContain("reliable classifier");
    expect(body.toLowerCase()).not.toContain("accurate classifier");
  });

  it("falls back gracefully when the endpoint is down", async () => {
    global.fetch = vi.fn(async () => ({ ok: false })) as never;
    render(await RegimeModelCardPage());
    expect(screen.getAllByText(/temporarily unavailable/i).length).toBeGreaterThan(0);
  });
});
