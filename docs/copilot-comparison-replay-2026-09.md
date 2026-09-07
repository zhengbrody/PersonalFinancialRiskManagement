# Copilot comparison snapshots and verification

2026-09-06. **Local implementation; default off, not deployed.** No database
changes, production configuration, credentials, holdings or plans were written.

## Delivered

When enabled, a comparison carries an opaque server-signed receipt containing
the complete calculation inputs: account holdings/cash/debt/capital, the price
matrix (including missing cells), option analytics, sources, capture clock,
assumptions and original result. This is separate from the unsigned input
fingerprint already displayed on comparisons.

In the same Copilot window, **Verify captured calculation** explicitly submits
the receipt to `/api/v1/copilot/compare-change/{result_id}/verify`. The server:

1. Requires a valid user JWT, feature configuration and the shared bounded lane.
2. Authenticates the exact receipt bytes before parsing or computing them.
3. Checks user, portfolio and result identities and the active account.
4. Checks the calculation-source/runtime fingerprint; version changes reject
   replay rather than silently reinterpreting old numbers.
5. Re-executes the existing comparison against the captured matrix and option
   rows, at the original clock. **No market fetch, LLM call or account write.**
6. Requires the result to reproduce (excluding the random presentation ID).
   Everything that is not a float must match exactly; floats must agree to 1e-9
   relative. Byte equality was tried first and is **wrong** here: IEEE-754
   reductions are not bit-reproducible run to run, and production refused an
   unmodified `proceeds="cash"` comparison whose `var_1d_95_usd` re-ran to the
   neighbouring double (468.8543564516835 against 468.85435645168354). The
   inputs are covered by the receipt HMAC, not by this comparison; what it
   catches is code or version drift, which moves results by far more than a
   nanodollar.
7. Rechecks active account identity/inputs and returns the reproduced result,
   checked time, input-match status and capture age. The frontend replaces its
   local summary with the server-reproduced result.

Historical reproducibility, current account input match and capture recency are
three different things. An hour-old receipt can reproduce correctly while its
account has changed. A capture less than 15 minutes old does **not** imply fresh
exchange quotes: the mixed-account timestamp and pricing limitations remain.

## Trust, storage and limits

- Root secret: existing independent `MINDMARKET_RISK_RUN_SIGNING_SECRET`, minimum
  32 bytes. HMAC derives a purpose-separated comparison key; a run-journal
  signature is not a comparison signature. No user JWT or root key is embedded.
- Feature: `MINDMARKET_COMPARISON_REPLAY_ENABLED=true`, default false. It is
  independent of `MINDMARKET_COPILOT_RUNS_ENABLED` and does not require or apply
  migration 0014. Missing configuration fails closed. There is no new frontend
  env variable; a verify button appears only when a receipt is present.
- HMAC authenticates; it does **not encrypt**. Receipts contain private portfolio
  inputs and prices and belong only in authenticated first-party transport/tab
  storage. Never log, put into URLs, analytics, shared cards or public exports.
  Existing HTTP/Sentry request-body suppression remains in place.
- Maximum 512,000 UTF-8 bytes; matrix bounded to 400 dates × 120 columns and at
  most 20 option rows. Frontend retains receipts only for the two latest
  comparison turns, within the existing user/book tab partition. Storage failure
  remains in-memory-only; closing the tab loses receipts. This is **not durable
  cross-device storage or an immutable audit ledger**.
- Source fingerprint includes comparison/option/quant implementations,
  constants, schema and numeric runtime versions, architecture and OS. Cache is
  process-local; deployment restarts processes. No promise to execute old code
  after deployment/key rotation; unsupported old receipts require a new comparison.
- Portfolio switches suppress late responses; refresh does not automatically
  verify or fetch market data. Stop waiting aborts browser IO, not running Python.

## Follow-on confirmation slice

The explicit confirmation/save implementation now exists locally, default off:
see [confirmation architecture and acceptance](copilot-comparison-confirmation-2026-09.md).
It adds migration 0015, revision-bound atomic save, signed evidence separate from
editable plans, and authenticated retrieval. The original replay-only acceptance
record below is retained as historical context.

## Original replay-only scope

This is the prerequisite for trustworthy confirmation, **not confirmation/save
itself**. There is no “Save verified plan” action, no exactly-once DB transaction,
no plan-save credential and no periodic execution. The existing generic risk-plan
endpoint accepts user-provided analysis blobs; those must never be mistaken for
server-authenticated calculation evidence merely because source is `copilot`.

Next slice must add version-bound explicit confirmation with atomic database
compare-and-insert, owner/result uniqueness for retry idempotency, immutable
signed evidence separated from editable plan notes/status, and authenticated
read verification. Portfolio edits/switches racing the write must be tested at
the DB boundary, not only mocked before/after reads. Preserve legacy user-authored
plans with honest provenance. Real PostgreSQL/RLS testing and staged activation
remain mandatory before claiming this is production-ready.

## Local verification

- Backend: **1302 passed, 1 skipped**, coverage **89.08%**, above 85% gate.
- Replay + comparison focused suite: **84 passed**, including 15 new tests for
  exact stock/mixed replay, null cells/numeric normalization, tampered prices,
  options, account inputs, assumptions/results, owner/book/result binding,
  key rotation/domain separation, version change, mismatch, size/configuration,
  authenticated read-only endpoint, stale inputs and capture age.
- Frontend: **580 passed**; tsc/lint passed. Browser production-like build:
  **72 passed** desktop/mobile, including explicit verify, reload without extra
  compute, stale-input warning, one composer and no horizontal overflow.
- Black/Ruff, schema/core mypy (43 files), regenerated OpenAPI/TS and whitespace
  checks passed. Fixtures are not real Supabase/RLS, live providers or deployment
  verification. Existing test-only JWT/deprecation warnings remain.
