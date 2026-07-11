/**
 * Compile-time contract alignment.
 *
 * Responses are now typed in OpenAPI (backend routes use
 * `response_model=Envelope[X]`), so the generated `api-types.ts` is the
 * authoritative contract. The hand-written zod schemas in `schemas.ts` stay as
 * the RUNTIME guard; these type-level assertions pin them to the generated
 * contract so a backend type change (e.g. `overall_score` → string) fails `tsc`
 * here until the zod schema follows. The CI regen-diff gate catches undocumented
 * BACKEND drift; this catches FRONTEND (zod) drift. Extend as more schemas
 * migrate onto the generated types.
 */

import type { components } from "./api-types";
import type { ScoreResponse } from "./schemas";

type Eq<A, B> = [A] extends [B] ? ([B] extends [A] ? true : never) : never;
type Assert<T extends true> = T;

type ApiScoreResponse = components["schemas"]["ScoreResponse"];

// Load-bearing scalars must match the generated contract exactly.
export type ScoreOverallAligned = Assert<
  Eq<ScoreResponse["overall_score"], ApiScoreResponse["overall_score"]>
>;
export type ScoreVersionAligned = Assert<
  Eq<
    NonNullable<ScoreResponse["score_version"]>,
    NonNullable<ApiScoreResponse["score_version"]>
  >
>;
export type RiskPreferenceAligned = Assert<
  Eq<ScoreResponse["risk_preference"], ApiScoreResponse["risk_preference"]>
>;
