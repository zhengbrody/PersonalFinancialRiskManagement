import { z } from "zod";
const httpsUrl = z.string().url().refine(value => {
  const url = new URL(value);
  return url.protocol === "https:" && !url.username && !url.password;
});
export const copilotResearchSchema = z.object({
  version: z.literal(1), ticker: z.string(), captured_at: z.string(),
  status: z.enum(["available", "partial", "unavailable"]),
  observations: z.array(z.object({
    id: z.string(), ticker: z.string(), metric: z.string(), value: z.number().finite().nullable(),
    unit: z.enum(["ratio", "fraction"]), source: z.string(), source_as_of: z.string().nullable(),
    reporting_period: z.null(), provenance: z.enum(["block_only", "unavailable"]),
    status: z.enum(["available", "missing", "stale", "undated"]), scope: z.literal("company_research"),
    basis: z.enum(["provider_projection", "computed_from_series"]),
  })).max(4),
  questions: z.array(z.object({
    method_id: z.string(), hypothesis: z.string(), observation_ids: z.array(z.string()),
    counterpoint: z.string(), invalidation_check: z.string(), status: z.literal("not_tested"),
  })).max(2),
  leads: z.array(z.object({
    title: z.string(), publisher: z.string().nullable(), author: z.null(), published_at: z.string().nullable(),
    url: httpsUrl, conflicts: z.literal("not_disclosed_in_feed"), verification: z.literal("metadata_only"),
  })).max(3),
  methods: z.array(z.object({
    id: z.string(), title: z.string(), author: z.string(), url: httpsUrl,
    reviewed_at: z.string(), version: z.string(), summary: z.string(), checks: z.array(z.string()),
    counterpoint: z.string(), applicability: z.string(),
  })),
  limitations: z.array(z.string()), can_rank_candidates: z.literal(false),
}).superRefine((data, ctx) => {
  const ids = new Set(data.observations.map(row => row.id));
  if (ids.size !== data.observations.length ||
      data.observations.some(row => row.ticker !== data.ticker || row.id !== `${row.ticker}:${row.metric}`) ||
      data.questions.some(q => q.observation_ids.some(id => !ids.has(id)))) {
    ctx.addIssue({ code: "custom", message: "Research observation scope mismatch" });
  }
});
export type CopilotResearch = z.infer<typeof copilotResearchSchema>;
