# Copilot: explicitly confirmed comparison drafts

2026-09-06 — local implementation, PostgreSQL and local Supabase HTTP acceptance.
**Production default OFF; no production migration, key provisioning or deployment.**

## User experience

Within the existing single Copilot window:

1. Test a stock/ETF reduction against keeping the entire account unchanged.
2. Open **Save as draft plan**. Opening it makes no request.
3. Read the hypothetical assumption and check explicit confirmation.
4. **Confirm and save draft** sends only the original opaque receipt, expected
   portfolio ID and `confirmed: true`. No client financial result is accepted.
5. A successful response replaces the displayed calculation with its original
   server-authenticated result and supplies a stable draft-plan ID. **Open saved
   risk plans** leads to the existing `/analyze?view=plan` panel.
6. Retry/check the same result after an uncertain response. Aborting the browser
   request means *stopped waiting*, not cancellation of a committed transaction.
   Reload never automatically saves again. Restored saved status must be checked
   against the server before being presented as current confirmation.

This does not change holdings, execute orders, modify option legs, suggest a
candidate automatically, or start a background worker. Plan title/status/notes
remain editable through the existing plan flow; they do not rewrite evidence.
The legacy client-metric “Review” action is not offered for these captures:
their baseline/impact are namespaced to avoid falsely comparing unlike score
windows or account methodologies. Matched-method outcome review remains future
work, explicitly disclosed in the saved-plan panel.

## API and trust boundaries

| Endpoint | Purpose | Trust |
| --- | --- | --- |
| `POST /api/v1/copilot/compare-change` | Capture both sides, data and portfolio revision | JWT, active book, existing comparison validation |
| `POST /api/v1/copilot/compare-change/{id}/confirm` | Explicitly save one draft | Exact receipt signature, ownership, source/runtime replay, revision guard |
| `GET /api/v1/copilot/compare-change/{id}/saved?expected_portfolio_id=…` | Read authenticated original evidence | JWT/RLS plus confirmation HMAC and all owner/book/result bindings |
| Existing `/risk/plans` routes | Editable plan management | User-authored content, never implicitly verified by `source=copilot` |

`comparison_replay` remains the only calculation replay implementation.
`comparison_save` adds a separately domain-separated confirmation HMAC derived
from the existing root key. Confirmation signs owner, portfolio, plan/result ID,
confirmation time and the exact original signed receipt. New saves require a
capture at most 15 minutes old and an identical calculation implementation.
This capture limit is **not** a claim that provider quotes are fresh.

Historical reads authenticate the original record without running changed code
or fetching prices. A retry of a successfully stored result returns that same
record even if time, account inputs or implementation subsequently changed.
Key rotation without an old-key verification mechanism invalidates old proofs;
that operational limitation remains explicit.

The receipt's `save_available` field is a UI hint, not authorization. The revision
is inside signed snapshot bytes. Old receipts without a captured revision cannot
save even if a client forges that hint. Extra client calculation fields and
non-boolean confirmation values are rejected.

RLS is ownership, **not server provenance**: owners can call PostgREST themselves.
The evidence table is insert/select only for authenticated users, with no direct
update/delete permission. Even a directly inserted fake record is untrusted;
the authenticated read/retry path verifies its HMAC and all row bindings before
display. Database administrators are not treated as an immutable-ledger threat
model. No privileged credential is given to the browser or model.

## Atomic persistence — migration 0015

- Adds an opaque `portfolios.comparison_revision` UUID. A trigger replaces it on
  every insert/update, ignoring any caller-supplied old value. Editing and then
  restoring inputs cannot revive a stale capture (ABA).
- Reads the revision before collecting the comparison's active account context.
  No account mutation between that read and confirmation can preserve its
  captured revision. Existing optimistic scope checking remains as early UX
  feedback, not the storage correctness boundary.
- `confirm_copilot_comparison` is a JWT/RLS **security-invoker** RPC. A per-result
  transaction advisory lock plus unique plan ID serializes retries. A per-owner
  portfolio-write lock plus captured-row lock covers edits, deletes, active-book
  switches and concurrent insertion of a newer default portfolio.
- A statement trigger obtains the owner lock before normal JWT-scoped portfolio
  writes acquire row locks. An additional row trigger covers administrative
  writes without a user claim; such writers must retry normal PostgreSQL
  deadlock/serialization errors. No global lock across all users is introduced.
- Rechecks revision, active selection, capture expiry and confirmation time inside
  the database transaction. Creates the existing `risk_plans` draft and a separate
  `comparison_confirmations` proof row together, or neither. SQL projects plan
  fields from the captured result; it does not take an independent client impact.
- Deleting the parent plan/account cascades evidence deletion. No standalone
  evidence-delete policy that could silently detach the original from its plan.
- Migration rerun is covered. Adding a non-null generated revision populates
  existing rows and takes schema locks: assess table size/maintenance window
  before production. Financial balances/holdings are not changed.

Locking rationale follows PostgreSQL's [explicit locking documentation](https://www.postgresql.org/docs/current/explicit-locking.html).

## Shared resolver correction

The real active-account normalization dropped option strike/expiry/underlying,
side, multiplier and adjustment flags while older route fixtures already supplied
them. It now preserves raw contract metadata before normalizing common fields;
the existing strict option validators still accept/reject supported instruments.
A regression uses the actual resolver and real option metadata to assert all six
spread legs and signs survive, and adjusted contracts remain rejected.

## Activation and remaining scope

Both flags must be enabled explicitly after staging acceptance:

| Configuration | Default / prerequisite |
| --- | --- |
| `MINDMARKET_COMPARISON_REPLAY_ENABLED` | false; dedicated root key configured securely |
| `MINDMARKET_COMPARISON_SAVE_ENABLED` | false; replay enabled and migration 0015 applied |
| `MINDMARKET_RISK_RUN_SIGNING_SECRET` | Server-only, at least 32 bytes; never output/log |

No new frontend flag. Missing infrastructure fails closed, not to an unsigned
save. Deploy disabled code first; validate migration and credentials in staging;
exercise the real Supabase JWT/PostgREST boundary and rollback; then separately
authorize production migration, activation and smoke checks. Disabling the save
flag stops confirmation/read actions without deleting existing plans. Do not
automatically drop the new table/column/triggers when rolling back application
code.

Still outside this slice: general multi-candidate planning, option-leg edits,
cross-device conversation/history UI, scheduled review and a durable multi-step
worker. The complete Risk Agent plan is **not finished** merely because this
explicit comparison-save path now exists.

## Independent pre-release review (2026-09-06)

Three read-only reviewers (financial integrity, security/DB/concurrency, frontend)
ran against this tree; the security reviewer stopped early on a session limit and
that lane was completed by the integrating engineer. Every claim below was
reproduced by running code, not by reading it. Fixes landed in this branch.

### Fixed — financial

- **An explicit `liquidity_class: "risk_asset"` override was ignored by the
  stress.** `comparison_options.mixed_stresses` chose the shock by ticker
  membership alone, so a treasury fund the user had explicitly refused to have
  auto-classified still received the −1% treasury shock instead of −20%. On a
  $100k position that understated the modelled sell-off loss by $19,000 — the
  unsafe direction, and the headline number of the mixed path. It now routes
  through the canonical `financing_resilience.classify_holding`; option
  underlyings, which have no holding record, keep the registry default.
- **`largest_position_weight` mixed two bases.** The numerator was stock-only
  while the denominator was gross assets including cash and long option marks,
  so it always read smaller than the concentration `/risk` reports for the same
  account — 0.10 against a canonical 0.60 on a cash-heavy book, and 3.4% on an
  option-dominated one whose real largest exposure was 96.6%. On a mixed book it
  is the only concentration figure returned, because vol/VaR are deliberately
  null there. It is now computed on the invested basis (cash excluded) with long
  option legs as candidate positions.

Both fixes carry regression tests that were confirmed to fail against the
pre-fix code and pass after.

### Fixed — frontend

- Post-commit server rejections were reported as definite failure. `confirm()`
  validates the stored row *after* the RPC commits, so `untrusted_saved_comparison`
  and `comparison_conflict` can arrive with the draft already created. The
  uncertainty classifier is now a deny-list: everything is treated as unknown
  except codes that provably precede the write.
- A definite `saved_comparison_missing` (the plan was deleted) left the card
  permanently asserting a saved plan with no way back; it now clears the
  remembered save and restores the save action.
- Evicting a receipt to bound tab storage silently removed Verify/Save from
  older comparisons; the card now says so.
- One unparseable stored turn discarded the whole thread, including the only
  local pointer to a saved draft; restore is now per-item.
- Opening the consent step dropped keyboard focus to the document body, and
  cancelling did not restore it.
- The plan card told users to inspect the original "in Copilot" without saying
  that the signed original is reachable only from the tab session that saved it.
- The account-switch test passed because the scope key remounts the tree, not
  because of the guard it claimed to cover; it now switches back and asserts.

### Deployment defect found outside the reviewed code

`compose.split.yml` did not forward `MINDMARKET_COMPARISON_REPLAY_ENABLED` or
`MINDMARKET_COMPARISON_SAVE_ENABLED` to the backend container, so setting them in
the server `.env` would have had no effect and the feature would have stayed off
with nothing in the logs. Both are now forwarded, and
`tests/unit/test_deploy_config.py` guards every backend flag and key against the
same omission.

### Disclosed, not fixed

A stock close up to seven days old may be paired with a fresher option quote,
and the implied volatility solved from that pair silently absorbs the mismatch
(a measured 3.5× inflation in a constructed case). The stress remains internally
consistent because it is anchored to the same model at zero shock, and the close
date is shown on the card. Banding the solved value against the chain's own
quoted volatility is not reliable — real chains carry placeholder values there —
so tightening this needs its own change rather than a release-time patch.

## Validation

Final local results: backend **1325 passed, 1 skipped**, coverage **89.06%**
(includes 8 actual PostgreSQL tests); legacy root **868 passed**; frontend
**584 passed**; full desktop/mobile Playwright **74 passed**, plus final focused
comparison browser rerun **10 passed**. Black/Ruff, schema/core mypy (43 files),
tsc/lint, production-like Next build, regenerated OpenAPI/TS and drift/whitespace
checks passed. Existing test JWT/deprecation, mocked chart sizing and deliberate
offline-data/LAPACK warnings remain; these are not claims of zero production
bugs. The isolated PostgreSQL cluster is stopped after acceptance; no production
connection or configuration was used.

- Unit/API tests cover explicit consent, signed scope, tampering and row rebinding,
  stale receipts, missing revisions, version drift, atomic rejection, default-off,
  lost response after commit, idempotent retry, retrieval and option metadata.
- Opt-in tests execute actual migrations and transactions on an isolated local
  PostgreSQL 17 cluster (Unix socket only). They cover RLS, forbidden evidence
  updates/deletes, parent cascade, concurrent duplicate confirmations, ABA,
  capture expiry/default switch, concurrent edit/switch/new-default insertion,
  and a signed Python service → real SQL → authenticated read roundtrip after
  mutable plan content is edited.
  Extension placement is also exercised outside `public`, matching common
  hosted layouts; the revision trigger uses `pg_catalog.gen_random_uuid()`.
- These are **not** hosted Supabase/PostgREST or production tests. The disposable
  test database uses the Supabase-style `auth.uid()` claim contract, not real
  remote JWT validation. API JWT checks and browser interactions are tested
  separately.

### Follow-up: real local Supabase acceptance

The user approved preparing an isolated staging environment. The authenticated
Supabase CLI could list projects, but creation of `mindmarket-staging` was rejected
by the organization's active-project limit. **No hosted project was created; no
existing project was paused, deleted, linked or migrated.** Hosted acceptance
still requires an available project slot or a designated isolated test project.

To make progress without using production, an independent local Supabase CLI
stack was prepared. Four additional tests passed using actual Auth password
login, a separate loopback Uvicorn application process, the application Supabase
client, PostgREST, real RPC execution and platform RLS:

- Confirm/save, identical retry and authenticated original-record retrieval;
  exactly one plan and unchanged portfolio row.
- Cross-user receipt rejection and empty RLS results; cross-user API read 404;
  signature tampering rejected, direct evidence update forbidden, anonymous
  access forbidden.
- Edit-and-restore invalidates the portfolio revision and produces no plan.
- Missing JWT and absent/incorrect explicit boolean confirmation are rejected.

The captured prices are deterministic synthetic fixtures, signed by the same
calculation module: this validates persistence/authentication, **not live market
data, hosted networking or an end-to-end browser journey**. Existing browser
tests remain a separate layer. Admin privileges are used only to create/delete
this run's synthetic local Auth users; all business reads/writes use the actual
password-login JWT and anon API key. Users are deleted in fixture cleanup.

Reproduce from the repository root with Docker running and the installed
[Supabase CLI](https://supabase.com/docs/reference/cli/getting-started):

```sh
python scripts/run_comparison_supabase_acceptance.py
```

The runner uses only `/tmp/mindmarket-staging-20260906`, refuses linked projects
and remote Docker endpoints, suppresses CLI secret output, and restricts both
published Supabase ports to `127.0.0.1` before creating fixtures. The CLI briefly
starts with its default network bindings; only empty/synthetic local data is
permitted in this stack. Tests independently verify loopback bindings. The runner
stops only its own containers on exit, retaining the local volume for repeat
runs. Existing Docker projects are untouched. It never provisions cloud
resources, runs production deployments or copies production data.

The related replay/save unit and API regression suite was rerun: **30 passed**.
Black, Ruff and whitespace checks passed for this follow-up. Existing short-key
test-fixture and Starlette deprecation warnings remain in that older suite; the
new real-auth acceptance does not mint test JWTs itself.

### Owner environment decision — supersedes the new-project prerequisite

On 2026-09-06 the owner explicitly chose the existing `mindmarket-ai` project
(`byfpmmfduteajblqpuuw`). Do not create another project or ask the owner to free
a project slot. The earlier isolated-cloud plan is no longer a release
prerequisite; it was not completed and must not be reported as a passed test.
Use local isolated acceptance plus a controlled incremental production rollout:
check backups/rollback and migration prerequisites, deploy disabled, then enable
and run authenticated smoke checks under the release authorization. Never run
the local test initializer against production. Choosing the target does not
itself record a completed migration or deployment.

Read-only verification after the owner's screenshot: Management API reported
`ACTIVE_HEALTHY`; the live application's deep health check reported Supabase REST
2xx and required configuration checks passed. This does not explain the earlier
dashboard `Unhealthy` label or prove every hosted subsystem healthy.
