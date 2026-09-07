import { z } from "zod";

/** Public projection contract. No browser-side financial calculations. */
export const riskCheckSchema = z.object({
  portfolio_id: z.string(),
  result_id: z.string(),
  methodology_version: z.literal("risk-check-v1"),
  computed_at: z.string(),
  price_history_as_of: z.string().nullable(),
  status: z.enum(["ready", "limited"]),
  summary: z.string(),
  metrics: z.array(
    z.object({
      key: z.string(),
      label: z.string(),
      value: z.number().finite().nullable(),
      unit: z.enum(["usd", "fraction", "multiple", "days"]),
      horizon: z.string(),
      basis: z.string(),
      explanation: z.string(),
      source_field: z.string(),
    }),
  ),
  findings: z
    .array(
      z.object({
        key: z.string(),
        title: z.string(),
        severity: z.enum(["high", "elevated", "info"]),
        explanation: z.string(),
      }),
    )
    .max(3),
  limitations: z.array(z.string()),
  strategies: z
    .array(
      z.object({
        underlying: z.string(),
        expiry: z.string(),
        name: z.string(),
        leg_count: z.number(),
        premium_basis: z.enum([
          "entry",
          "current_mark",
          "mixed",
          "unavailable",
        ]),
        max_loss: z.number().finite().nullable(),
        max_gain: z.number().finite().nullable(),
        loss_status: z.enum(["bounded", "unbounded", "unavailable"]),
        gain_status: z.enum(["bounded", "unbounded", "unavailable"]),
      }),
    )
    .default([]),
});

export type RiskCheck = z.infer<typeof riskCheckSchema>;

/** Only explicit check requests trigger the heavier risk computation. */
export function isRiskCheckRequest(text: string): boolean {
  return /^(check (my|this) portfolio( risk)?|run (a |my )?risk check|检查我的(投资)?组合(风险)?|检查组合风险)[.!。！]?$/i.test(
    text.trim(),
  );
}

export function formatCheckValue(metric: RiskCheck["metrics"][number]): string {
  if (metric.value === null) return "Unavailable";
  switch (metric.unit) {
    case "usd":
      return new Intl.NumberFormat("en-US", {
        style: "currency",
        currency: "USD",
        maximumFractionDigits: 0,
      }).format(metric.value);
    case "fraction":
      return new Intl.NumberFormat("en-US", {
        style: "percent",
        maximumFractionDigits: 1,
      }).format(metric.value);
    case "multiple":
      return `${metric.value.toFixed(2)}×`;
    case "days":
      return `${metric.value.toFixed(1)} days`;
  }
}
