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

## Cross-source agreement (wired 2026-07-17)
`services/source_agreement.py` classifies per-field pairs into
`exact | within_tolerance | disagreement | incomparable | only_one_source`
with field-specific tolerances (price 1% · market cap 3% · statements 2% + an
absolute EPS epsilon). Unit or fiscal-period mismatch → `incomparable`, never a
silent conversion. Both raw values ride `FieldAgreement.observations` verbatim —
a disagreement lowers the confidence float (−0.10/field, cap −0.20, reason code
`cross_source_disagreement`) but never overwrites either side's number.

**Capture point**: `research_factpack._cross_checks` — the ONE place both
providers' raw values coexist before the `_pref` merge discards the loser.
Independence guard: when the FMP profile was itself yfinance-backfilled
(`source == "fmp+yfinance"` / `"yfinance"`), per-field origin can't be
attributed → `only_one_source`, never a yfinance-vs-yfinance self-agreement.
Production dual-source fields today: `last_price` + `market_cap` (the yfinance
enrichment always runs alongside FMP). `revenue / net_income / eps` ride a
fallback LADDER (one source at a time) → honestly `only_one_source`; the
machinery + tests are ready if a second simultaneous source ever exists.
`build_coverage` lifts the checks into `DataConfidence.agreement_checks`;
`<DataConfidence>` renders each verdict with both raw values.

## Research provenance UI (unified 2026-07-17)
`ResearchTrustSummary` (the unified `<DataConfidence>` fed by the coverage
endpoint) is the ONE research-level confidence block, at the top of /research.
Deleted as true duplicates: the hand-rolled `TrustStrip` line and the header
`DataQualityBadge` popover, plus the coverage card's embedded copy. KEPT with
distinct business meaning: `SourcesCard` (per-figure provenance table), the
coverage card's dataset matrix, and the verdict panel's own `<DataConfidence>`
(the AI verdict's directional gate).

## Dataset health diagnostics (2026-07-17)
`metrics.record_dataset(name, *outcomes)` — aggregate per-DATASET counters
(requests / present / empty / stale / fallback / provider_error / rate_limited)
recorded by the bundle endpoint; closed dataset set (a ticker can never become
a bucket). Surfaces in the owner `/admin` Live-activity card. Distinguishes
provider-reality gaps (empty / rate_limited) from code faults (provider_error).

## Known follow-ups
- `copilot_router._factpack_evidence` hardcodes `source="fmp"` for price/PE/
  margin/ROE even when the FactPack filled them from the yfinance FALLBACK
  (`_pref`) — so those show a "primary" badge. Pre-existing; the honest fix is to
  thread the FactPack's per-field source through the compact merge. The verdict's
  own provenance (`_verdict_confidence`) is already correct.
- EPS dual-source capture at the earnings merge (`_merge_earnings_estimates`
  has FMP + yfinance EPS for matched quarters when FMP carries actuals) —
  a clean future extension of the same machinery.
