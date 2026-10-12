import { z } from "zod";
const httpsUrl = z.string().url().refine(value => {
  const url = new URL(value);
  return url.protocol === "https:" && !url.username && !url.password;
});
const hypothesisSchema = z.object({
  id: z.string(), origin: z.enum(["user_view", "method_question"]), claim: z.string(),
  claim_basis: z.enum(["user_assumption", "model_inference"]), subject: z.string(), scope: z.literal("company"),
  as_of: z.string(),
  sources: z.array(z.object({
    id: z.string(), source_type: z.enum(["user_statement", "provider_snapshot", "method_card"]),
    author: z.string().nullable(), publisher: z.string().nullable(), url: httpsUrl.nullable(),
    published_at: z.string().nullable(), retrieved_at: z.string().nullable(),
    usage_basis: z.enum(["user_provided", "provider_api", "public_page_paraphrase"]),
    quote_locator: z.string().nullable(), paraphrase: z.boolean(),
    verification: z.enum(["not_verified", "provider_snapshot", "reviewed_method"]),
  })),
  evidence_observation_ids: z.array(z.string()), inference: z.array(z.string()),
  test: z.object({
    observation_id: z.string(), comparator: z.enum(["gt", "ge", "lt", "le"]), threshold: z.number().finite(),
    unit: z.enum(["ratio", "fraction"]), threshold_basis: z.literal("user_assumption"),
  }).nullable(),
  counter_arguments: z.array(z.string()),
  invalidation_conditions: z.array(z.object({
    kind: z.enum(["observable_test", "qualitative_check", "not_defined"]), description: z.string(),
    observation_id: z.string().nullable(),
  })),
  status: z.enum(["unverified", "supported_by_evidence", "contradicted", "stale"]),
  missing: z.array(z.object({ item: z.string(), reason: z.string() })),
  can_authorize_tools: z.literal(false), comparison_input: z.literal("user_entered_price_change_only"),
});
export type ResearchHypothesis = z.infer<typeof hypothesisSchema>;
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
  hypotheses: z.array(hypothesisSchema).max(4).default([]),
}).superRefine((data, ctx) => {
  const ids = new Set(data.observations.map(row => row.id));
  if (ids.size !== data.observations.length ||
      data.observations.some(row => row.ticker !== data.ticker || row.id !== `${row.ticker}:${row.metric}`) ||
      data.questions.some(q => q.observation_ids.some(id => !ids.has(id))) ||
      data.hypotheses.some(h => h.subject !== data.ticker || h.evidence_observation_ids.some(id => !ids.has(id)))) {
    ctx.addIssue({ code: "custom", message: "Research observation scope mismatch" });
  }
});
export type CopilotResearch = z.infer<typeof copilotResearchSchema>;
