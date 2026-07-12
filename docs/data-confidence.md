# Unified Data Confidence & Provenance layer

One contract for "how much should you trust this conclusion", carried on every
truth-bearing response and rendered by one component. Product-truthfulness, not
a visual redesign — no calculation changed, only assembled + enforced.

## Schema decision: no DB migration
Everything is additive: `data_confidence` on existing response models
(`ScoreResponse`, `RiskReportOut`, `ResearchVerdict`, `CopilotAnswer`) and the
`RiskExplainInput/Output` fields. AI-call telemetry already rides
`usage_events.metadata` (JSONB). A future "confidence history" trend would need a
column — flagged, not built.

## The contract — `backend/app/schemas/confidence.py`
`DataConfidence`: `label` (high/medium/low) · `confidence` 0–1 ·
`overall_coverage` · `critical_coverage` · `as_of` · `fetched_at` · `stale` ·
`fallback_used` · `cross_source_agreement` (optional, where ≥2 independent
sources cover the same field) · `conviction_cap` · `directional_allowed` ·
`sources[]` / `missing[]` (`FieldProvenance`) · `reason_codes[]`.

`FieldProvenance` normalises the four pre-existing provenance vocabularies into:
`source` · `source_type` (**primary / secondary / derived** — mapped from the
provider registry's primary/fallback/computed) · `as_of` · `fetched_at` ·
`stale` · `coverage` · `fallback_used` · `missing_reason` · `note`.

`MissingReason` is the typed enum that finally replaces the scattered strings
(`fmp_key_missing`, `massive_rate_limited`, `no_estimates`, …):
`unsupported | no_key | provider_error | rate_limited | insufficient_history |
not_applicable | stale_fallback | empty`.

## Enforcement (rule #3) — `backend/app/services/confidence.py::cap_conviction`
One place, applied on every surface:
- **critical_coverage < 40%** → `directional_allowed = False`, conviction `none`
  (research emits rating "Insufficient data" and skips the LLM; Copilot instructs
  the model to withhold a directional conclusion; risk_explain leads with a
  provisional caveat).
- **40–70%** → conviction capped at `low`.
- **stale or missing critical data** → conviction reduced.
- **derived estimates are never presented as provider-reported facts** — every
  `FieldProvenance.source_type` labels derived data, and the Copilot/verdict
  system prompts forbid dressing an estimate as a reported figure.

The data sets the conviction CEILING; the LLM can only lower it, never raise it.

## Surfaces (rule #5)
`score_from_active` · `report_from_active` · `risk/explain` (the AI verdict now
has a confidence input for the first time) · research `build_verdict` · Copilot
`/ask`.

## Frontend — `components/data-confidence.tsx`
One `<DataConfidence>` reading the contract: High/Med/Low badge, freshness +
stale, missing critical datasets with plain-English reasons, how missing data
caps the conclusion, and expandable per-source details (source · type ·
coverage · as-of). Reuses the existing design tokens (Badge tones + the pill
house-style + tabular-nums). It supersedes the score `ConfidenceBadge` and is
added to risk / research / Copilot.

## Tests (rule #6)
`test_confidence.py` (enforcement unit) + `test_confidence_surfaces.py`
(end-to-end per surface) prove low-quality data can't produce a high-confidence /
directional conclusion anywhere; `data-confidence.test.tsx` covers the UI states.
