/**
 * Seven-factor stress engine — client contract for
 * `POST /api/v1/risk/factor_stress`. Every number is computed by the backend;
 * this file only validates the shape and exposes the query hook.
 */
import { useQuery } from "@tanstack/react-query";
import { z } from "zod";
import { apiFetch } from "./api";
import { useAuth } from "./auth-context";

export const FACTOR_IDS = ["equity", "rates", "credit", "usd", "oil", "vol", "gold"] as const;
export type FactorId = (typeof FACTOR_IDS)[number];

const num = z.number();
const nnum = z.number().nullable();

const marginSchema = z.looseObject({
  equity_after: num,
  requirement_after: num,
  utilisation_before: nnum,
  utilisation_after: nnum,
  breach: z.boolean(),
  breach_multiple: nnum,
});

const scenarioSchema = z.looseObject({
  id: z.string(),
  label: z.string(),
  kind: z.enum(["hypothetical", "historical", "custom"]),
  source: z.string(),
  shocks: z.record(z.string(), num),
  specified: z.array(z.string()),
  filled: z.array(z.string()),
  pnl_usd: num,
  pnl_pct: num,
  band_low_usd: num,
  band_high_usd: num,
  stock_pnl_usd: num,
  by_factor: z.array(z.looseObject({ factor: z.string(), pnl_usd: num })),
  options: z.looseObject({ pnl_usd: num, delta_usd: num, convexity_usd: num, vega_usd: num }),
  by_holding: z.array(
    z.looseObject({ ticker: z.string(), move_pct: num, pnl_usd: num, source: z.string() }),
  ),
  margin: marginSchema,
  ladder: z.array(
    z.looseObject({
      multiple: num,
      pnl_usd: num,
      pnl_pct: num,
      linear_pnl_usd: num,
      margin_utilisation: nnum,
      breach: z.boolean(),
    }),
  ),
  path: z
    .array(
      z.looseObject({ date: z.string(), equity: num, drawdown: nnum, margin_utilisation: nnum }),
    )
    .nullable(),
  realised: z
    .looseObject({ coverage: num, return_pct: num, model_return_pct: num })
    .nullable(),
});

const distributionSchema = z.looseObject({
  histogram: z.array(z.looseObject({ lo: num, hi: num, p: num })),
  tails: z.array(
    z.looseObject({ level: num, var: num, cvar: num, var_se: nnum, cvar_se: nnum }),
  ),
  mean_pct: num,
  worst_pct: num,
  prob_margin_call: nnum,
  n_sims: num,
  n_obs: num,
});

const decompositionSchema = z.looseObject({
  factor_share: z.record(z.string(), num),
  idio_share: num,
  weekly_vol: num,
});

export const factorStressSchema = z.looseObject({
  model_version: z.string(),
  as_of: z.string(),
  horizon_weeks: num,
  confidence: num,
  maintenance_requirement: num,
  account: z.looseObject({
    gross_long: num,
    option_value: nnum,
    cash: num,
    margin_loan: num,
    net_equity: num,
    leverage: nnum,
  }),
  factors: z.array(
    z.looseObject({
      id: z.string(),
      label: z.string(),
      proxy: z.string(),
      unit: z.string(),
      description: z.string(),
      available: z.boolean(),
      weekly_vol: num,
      crisis_weekly_vol: num,
      portfolio_loading: num,
    }),
  ),
  exposures: z.array(
    z.looseObject({
      ticker: z.string(),
      source: z.string(),
      betas: z.record(z.string(), num),
      t_stats: z.record(z.string(), nnum),
      r2: num,
      n_obs: num,
      resid_vol_weekly: num,
      unstable: z.boolean(),
      weight: num,
      value_usd: num,
    }),
  ),
  coverage: z.looseObject({
    modelled_weight: num,
    proxied: z.array(z.string()),
    unmodelled: z.array(z.looseObject({ ticker: z.string(), weight: num, reason: z.string() })),
    unpriced: z.array(z.string()),
    option_legs_repriced: num,
    option_legs_skipped: z.array(z.looseObject({ contract: z.string(), reason: z.string() })),
  }),
  concentration: z.looseObject({ top_weight: nnum, hhi: num, effective_holdings: nnum }),
  correlation: z.looseObject({
    calm: z.array(z.array(num)),
    crisis: z.array(z.array(num)),
    calm_n_obs: num,
    crisis_n_obs: num,
  }),
  decomposition: z.record(z.string(), decompositionSchema),
  distribution: z.record(z.string(), distributionSchema),
  scenarios: z.array(scenarioSchema),
  assumptions: z.array(z.string()),
  warnings: z.array(z.string()),
});

export type FactorStress = z.infer<typeof factorStressSchema>;
export type StressScenario = z.infer<typeof scenarioSchema>;
export type Regime = "calm" | "crisis";

export type FactorStressParams = {
  horizon_weeks: 1 | 2 | 4;
  confidence: 0.9 | 0.95 | 0.99;
  fill_unspecified: boolean;
  custom_shocks: Partial<Record<FactorId, number>> | null;
};

/** Runs the engine for the active portfolio. Keyed on the portfolio and every
 *  parameter, so changing a control refetches and switching back is instant. */
export function useFactorStress(
  portfolioId: string | null | undefined,
  params: FactorStressParams,
  enabled: boolean,
) {
  const { accessToken, user } = useAuth();
  return useQuery<FactorStress>({
    queryKey: ["risk", "factor_stress", user?.id ?? null, portfolioId ?? null, params],
    enabled: enabled && !!accessToken,
    staleTime: 60_000,
    retry: false,
    queryFn: () =>
      apiFetch<FactorStress>("/api/v1/risk/factor_stress", {
        method: "POST",
        body: {
          horizon_weeks: params.horizon_weeks,
          confidence: params.confidence,
          fill_unspecified: params.fill_unspecified,
          custom_shocks: params.custom_shocks ?? undefined,
        },
        authToken: accessToken ?? undefined,
        schema: factorStressSchema,
      }),
  });
}

/** How a factor's shock is shown and typed. `vol` is entered as a VIX multiple,
 *  rates as basis points of yield, everything else as a percentage. */
export const IEF_DURATION = 7.5;

export function shockToDisplay(factor: string, shock: number): string {
  if (factor === "vol") return `VIX ×${Math.exp(shock).toFixed(2)}`;
  if (factor === "rates") {
    const bp = (-shock / IEF_DURATION) * 10_000;
    return `${bp >= 0 ? "+" : "−"}${Math.abs(bp).toFixed(0)}bp`;
  }
  return `${shock >= 0 ? "+" : "−"}${Math.abs(shock * 100).toFixed(1)}%`;
}

/** User input (bp for rates, VIX multiple for vol, % otherwise) → engine unit. */
export function inputToShock(factor: FactorId, raw: number): number {
  if (factor === "vol") return Math.log(raw);
  if (factor === "rates") return (-IEF_DURATION * raw) / 10_000;
  return raw / 100;
}

export const INPUT_HINT: Record<FactorId, string> = {
  equity: "%",
  rates: "bp",
  credit: "%",
  usd: "%",
  oil: "%",
  vol: "× VIX",
  gold: "%",
};
