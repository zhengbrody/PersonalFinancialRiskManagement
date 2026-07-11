/**
 * Documentation data for /methodology/health-score.
 *
 * These values MIRROR the backend single source of truth
 * (libs/mindmarket_core/score_version.py + portfolio_scoring.py). When the
 * backend methodology version is bumped, update `SCORE_METHODOLOGY_VERSION` and
 * add a `SCORE_CHANGELOG` entry here so the public page stays truthful. This
 * module carries NO math — it only describes the rules for the reader.
 */

export const SCORE_METHODOLOGY_VERSION = "mindmarket-score-v1.0.0";

export type ChangelogEntry = { version: string; date: string; summary: string };

export const SCORE_CHANGELOG: ChangelogEntry[] = [
  {
    version: "mindmarket-score-v1.0.0",
    date: "2026-07-10",
    summary:
      "First versioned methodology. No math change from the prior unversioned scores — this release only makes the methodology auditable and gates cross-version trend comparisons.",
  },
];

export type Dimension = { name: string; weight: number; blurb: string };

export const DIMENSIONS: Dimension[] = [
  {
    name: "Risk Match",
    weight: 0.35,
    blurb:
      "How closely your realized volatility and market beta sit to the target for your stated risk preference. A book far above (or below) your chosen risk band scores lower.",
  },
  {
    name: "Risk-adjusted Return",
    weight: 0.35,
    blurb:
      "Your Sharpe ratio — return earned per unit of volatility — measured on the underlying asset mix, so it is leverage- and cash-invariant (adding margin or cash does not flatter or punish this dimension).",
  },
  {
    name: "Downside Protection",
    weight: 0.3,
    blurb:
      "A blend of maximum drawdown (70%) and 1-day Value-at-Risk at 95% (30%) — how deep the book has fallen from a peak, and how large a normal bad day looks.",
  },
];

export type RiskTarget = { pref: number; label: string; vol: number; beta: number };

export const RISK_TARGETS: RiskTarget[] = [
  { pref: 1, label: "Capital preservation", vol: 0.06, beta: 0.25 },
  { pref: 2, label: "Conservative", vol: 0.1, beta: 0.55 },
  { pref: 3, label: "Balanced growth", vol: 0.14, beta: 0.8 },
  { pref: 4, label: "Growth", vol: 0.18, beta: 1.05 },
  { pref: 5, label: "Aggressive growth", vol: 0.25, beta: 1.3 },
];

/** Fixed inputs (documented; not the reader's to change). */
export const PARAMETERS = {
  historyWindowDays: 365, // ≈ 252 trading days of daily returns
  tradingDaysPerYear: 252,
  benchmark: "SPY",
  riskFreeRate: 0.045, // 4.5% annual, used as the Sharpe hurdle + cash/borrow proxy
};
