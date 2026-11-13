/**
 * Crisis replay and the published model validation — client contracts.
 * Every number is computed by the backend; this file validates shape only.
 */
import { useQuery } from "@tanstack/react-query";
import { z } from "zod";
import { apiFetch } from "./api";
import { useAuth } from "./auth-context";

const num = z.number();
const nnum = z.number().nullable();

const holdingSchema = z.looseObject({
  ticker: z.string(),
  weight: num,
  kind: z.enum(["observed", "reconstructed", "unavailable"]),
  return_pct: nnum,
  contribution_pct: nnum,
  loadings_source: z.string().nullable(),
  fit_r2: nnum,
});

const episodeSchema = z.looseObject({
  id: z.string(),
  label: z.string(),
  start: z.string(),
  end: z.string(),
  trading_days: num,
  coverage: z.looseObject({
    observed_weight: num,
    reconstructed_weight: num,
    unavailable_weight: num,
  }),
  portfolio: z.looseObject({
    return_pct: num,
    max_drawdown: num,
    trough_date: z.string(),
    worst_day: z.looseObject({ date: z.string(), return_pct: num }).nullable(),
    worst_week: z.looseObject({ start: z.string(), end: z.string(), return_pct: num }).nullable(),
  }),
  benchmark: z.looseObject({ ticker: z.string(), return_pct: num, max_drawdown: num }),
  excess_return_pct: num,
  beta_to_benchmark: nnum,
  holdings: z.array(holdingSchema),
  by_factor: z.array(z.looseObject({ factor: z.string(), contribution_pct: num })),
  factor_explained_pct: num,
  unexplained_pct: num,
  factor_moves: z.record(z.string(), nnum),
  factors_unavailable: z.array(z.string()),
  correlation: z.looseObject({
    episode_avg_pairwise: nnum,
    recent_avg_pairwise: nnum,
    assets_compared: num,
    stock_bond_episode: nnum,
    stock_bond_recent: nnum,
  }),
  path: z.array(
    z.looseObject({ date: z.string(), portfolio: num, benchmark: num, drawdown: num }),
  ),
});

export const crisisReplaySchema = z.looseObject({
  model_version: z.string(),
  as_of: z.string(),
  benchmark: z.string(),
  gross_long: num,
  unpriced: z.array(z.string()),
  loadings: z.array(z.looseObject({ ticker: z.string(), source: z.string() })),
  episodes: z.array(episodeSchema),
  data_source: z.string(),
  method: z.array(z.string()),
  warnings: z.array(z.string()),
});
export type CrisisReplay = z.infer<typeof crisisReplaySchema>;
export type ReplayEpisode = z.infer<typeof episodeSchema>;

export function useCrisisReplay(portfolioId: string | null | undefined) {
  const { accessToken, user } = useAuth();
  return useQuery<CrisisReplay>({
    queryKey: ["risk", "crisis_replay", user?.id ?? null, portfolioId ?? null],
    enabled: !!accessToken,
    staleTime: 5 * 60_000,
    retry: false,
    queryFn: () =>
      apiFetch<CrisisReplay>("/api/v1/risk/crisis_replay", {
        method: "POST",
        body: {},
        authToken: accessToken ?? undefined,
        schema: crisisReplaySchema,
      }),
  });
}

// ── published validation report ──────────────────────────────────────

const scoreSchema = z.looseObject({
  n: num,
  bias: nnum.optional(),
  mae: nnum.optional(),
  rmse: nnum.optional(),
  worst_abs_error: nnum.optional(),
  direction_hit_rate: nnum.optional(),
  calibration_slope: nnum.optional(),
  calibration_intercept: nnum.optional(),
  correlation: nnum.optional(),
});

const validationRowSchema = z.looseObject({
  episode: z.string(),
  episode_label: z.string(),
  start: z.string(),
  end: z.string(),
  portfolio: z.string(),
  portfolio_label: z.string(),
  selection: z.enum(["rule_based", "hindsight"]),
  outcome: z.string(),
  fit_cutoff: z.string(),
  factors_used: z.array(z.string()),
  realised: num,
  predicted: num,
  band_low: num,
  band_high: num,
  predicted_equity_only: num,
  predicted_beta_one: nnum,
  error: num,
});

const varLevelSchema = z.looseObject({
  level: num,
  expected_rate: num,
  breaches: num,
  breach_rate: nnum,
  windows: num.optional(),
  kupiec_p_value: nnum.optional(),
});

export const stressValidationSchema = z.looseObject({
  report_version: num,
  model_version: z.string(),
  generated_at: z.string(),
  data: z.looseObject({
    source: z.string(),
    first_date: z.string(),
    last_date: z.string(),
    tickers: z.array(z.string()),
    sha256: z.string(),
  }),
  method: z.looseObject({
    loadings: z.string(),
    lookback_weeks: num,
    embargo_trading_days: num,
    interval_level: num,
    code_sha256: z.string(),
  }),
  conditional: z.looseObject({
    rows: z.array(validationRowSchema),
    skipped: z.array(z.looseObject({ episode: z.string(), portfolio: z.string(), reason: z.string() })),
    models: z.record(z.string(), scoreSchema),
    interval: z.looseObject({
      n: num,
      nominal: num,
      inside: num.optional(),
      coverage: nnum.optional(),
      p_value: nnum.optional(),
    }),
    by_episode: z.array(scoreSchema.extend({ episode: z.string(), label: z.string() })),
    hindsight_rows: num,
  }),
  rolling_var: z.looseObject({
    portfolios: z.array(
      z.looseObject({
        portfolio: z.string(),
        portfolio_label: z.string(),
        windows: num,
        levels: z.array(varLevelSchema),
      }),
    ),
    pooled: z.array(varLevelSchema),
  }),
  caveats: z.array(z.string()),
  content_sha256: z.string(),
  hash_verified: z.boolean(),
  model_version_current: z.boolean(),
});
export type StressValidation = z.infer<typeof stressValidationSchema>;
export type ValidationRow = z.infer<typeof validationRowSchema>;

/** Public: the report holds no user data. */
export function useStressValidation() {
  return useQuery<StressValidation>({
    queryKey: ["risk", "stress_validation"],
    staleTime: 60 * 60_000,
    retry: false,
    queryFn: () =>
      apiFetch<StressValidation>("/api/v1/risk/stress_validation", {
        schema: stressValidationSchema,
      }),
  });
}
