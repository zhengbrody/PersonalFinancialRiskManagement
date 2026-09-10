# Background execution for Copilot analysis — design for review

**Status: proposal. Nothing implemented. Acceptance conditions at the end.**

## Why

Today every analysis runs synchronously inside one HTTP request while holding
`risk.py`'s `threading.BoundedSemaphore(1)`. That is one concurrent analysis
**for the whole site**, per backend process; a second request gets 429
`analysis_busy`. Stages 1 (multi-turn), 2 (up to three candidates) and 6
(cross-device, reliable execution) of the agent plan all press on that single
lane, and stage 2 presses hardest — three candidates is three serialised runs
on a t3.micro.

This design moves execution out of the request cycle. It is deliberately the
smallest thing that unblocks stages 1/2/6, **not** a general job platform.

## What already exists and is reused

`copilot_runs` (migration 0014, deployed but disabled, table never created) has
the two hardest parts right and they are kept as-is:

* **Idempotent reserve** — `upsert(on_conflict="id", ignore_duplicates=True)`
  with a client-minted UUID. A duplicate start returns the existing record and
  never replaces signed inputs.
* **Signed compare-and-swap** — every state write is
  `.eq("signature", old_signature).eq("state", "running")`, so concurrent
  cancel/complete races have exactly one winner.
* Signed `record` TEXT (not JSON, so Postgres numeric normalisation cannot
  change the signed bytes), owner-scoped RLS, and an HMAC that is checked on
  read because RLS is ownership, not provenance.

**No parallel implementation.** The extensions below are additive to that table
and those helpers; the existing tests must keep passing unchanged.

## What changes

### 1. State machine and step record

Current states: `running → completed | failed | cancelled | interrupted`, with
one `result` and `consistent_result` enforcing result-iff-completed. That is
kept. Added:

* `queued` before `running` — the row exists and is owned before any worker
  picks it up, so a crash between insert and pickup is visible rather than lost.
* `steps: [{seq, name, state, started_at, ended_at, evidence_ref?}]` **inside
  the signed record**, appended monotonically. Steps are progress, never
  authority: the answer's evidence still comes from the deterministic services,
  and a step row is not admissible as a result.
* `consistent_result` extends to: a `completed` run's last step must be
  terminal, and no run may carry a `result` unless `state == completed`.

### 2. Idempotency, versioning and signature

* **Idempotency key** stays the client-minted run UUID; a repeated start is a
  read, never a re-execution.
* **State version**: a monotonic `revision` inside the record, bumped on each
  transition, included in the signed bytes. A worker's write carries the
  revision it read; a mismatch loses the CAS.
* **Signature** covers `{run id, owner, portfolio, portfolio revision, state,
  revision, steps, result}`. Verified on every read before display, exactly as
  today. Tolerance is irrelevant here — this is bytes, not floats.

### 3. Claiming, leases, and keeping an expired worker out

* A worker claims by CAS `queued → running` with `lease_until = now + lease`.
  Losing the CAS means another worker owns it; the loser does nothing.
* **Lease renewal** while working. If a worker cannot renew, it must stop
  writing: renewal failure means someone else may already own the run.
* **Write fencing**: every worker write asserts `state == running AND
  revision == the revision it holds AND lease_until > now()`. An expired worker
  that wakes up therefore cannot write — its CAS fails on all three.
* Expired leases return the run to `queued` (bounded attempts) or to
  `interrupted`; the decision is recorded in the steps.

### 4. Retry, cancel, crash recovery

* **Retry** is per-run and bounded (`attempts`, hard cap). Each attempt appends
  steps; attempts never overwrite an earlier attempt's evidence.
* **Cancel** is a CAS to `cancelled`. It suppresses publication; it cannot
  preempt Python already running — the same honest limitation as today.
* **Crash** leaves `running` with a dead lease → reclaimed on expiry. Recovery
  resumes from the last completed step where the step is pure and repeatable;
  otherwise the attempt restarts. Which steps are resumable is declared per
  step, not assumed.

### 5. The commit-vs-dispatch gap

The dangerous window is between "row committed" and "worker told". Both
orderings fail differently and the design must pick one and state it:

**Commit first, then dispatch.** A lost dispatch leaves a `queued` row that a
sweeper picks up later — late, never lost. Dispatching first risks a worker
acting on a row that does not exist.

**This is at-least-once delivery. There is no exactly-once queue and this
design does not claim one.** A run may be delivered twice or executed twice.
Duplicate *side effects* are prevented by the same mechanisms that protect the
synchronous path today: the idempotent reserve, the CAS on every transition,
and the unique plan id in `confirm_copilot_comparison`. Correctness rests on
idempotence and state guards, not on delivery semantics.

### 6. Isolation

Every read and write filters on `user_id` explicitly **and** relies on RLS, as
today. A worker acts with the caller's token, never a service-role key, so a
worker cannot reach another user's book even if a run id leaks. Portfolio
binding stays the existing `portfolios.comparison_revision` check: a run whose
book changed underneath it fails its guard rather than producing a stale answer.

### 7. Three different clocks, kept apart

Conflating these is how "it says it saved but it did not" bugs are born:

| clock | meaning | today |
|---|---|---|
| **execution timeout** | how long one attempt may run | 2-minute client abort |
| **record retention** | how long the run is readable | 10-minute TTL |
| **signature validity** | how long a signed record is trusted | tied to key rotation |

They are set independently. A record must remain readable long after its
execution timeout, or "check what happened" stops working — which is precisely
the failure the interrupted-save path exists to avoid. Retention becomes hours
or days, not ten minutes; execution timeout stays short; signature validity is
a key-rotation question and is documented, not silently coupled.

### 8. Compatibility, flag, rollback

* The existing synchronous endpoints stay and stay default. The async path is a
  separate endpoint behind `MINDMARKET_ASYNC_ANALYSIS_ENABLED`, default off,
  fail-closed, and forwarded in `compose.split.yml` (guarded by
  `tests/unit/test_deploy_config.py`).
* Rollback is turning the flag off: in-flight runs finish or expire, stored
  records stay readable, no table is dropped.
* Migration is additive (new columns/states on `copilot_runs`); 0014 must be
  applied first, which it currently is not.

## Explicitly out of scope

Multi-tenant scheduling, priorities, a distributed queue, cross-service
orchestration, or a general worker framework. One lane per process becomes a
small pool; that is the whole ambition of this step.

## Acceptance conditions

Each must be demonstrated, and each mutation must fail for the stated reason:

1. **Duplicate dispatch produces one side effect.** Deliver the same run twice
   concurrently; exactly one plan/result exists. *Mutation:* drop the CAS →
   two results appear.
2. **An expired worker cannot write.** Hold a stale revision past the lease,
   then attempt every transition; all are refused. *Mutation:* remove the
   lease from the write predicate → the stale write lands.
3. **Lost dispatch is recovered, not lost.** Commit without dispatching; the
   sweeper reaches the run. *Mutation:* dispatch before commit → a worker sees
   a missing row.
4. **Crash mid-run resumes or restarts, never half-publishes.** Kill during a
   step; the run never reports `completed` with a partial result.
5. **Cancel suppresses publication** and is honest that running code is not
   preempted.
6. **Cross-user isolation** at the DB boundary on a real PostgreSQL, not mocks
   — the same bar the confirmation slice met.
7. **The three clocks are independent**: a run past its execution timeout is
   still readable; a run past retention is gone; a record signed under a
   rotated key fails verification.
8. **Flag off = no new behaviour**, and the synchronous path is byte-identical.
9. **Config chain proven end to end** — defined, forwarded by compose, and read
   inside the running container (value never printed, only presence/length).

Nothing here is implemented. Review the state machine, the commit-then-dispatch
choice and the retention numbers before any code is written.
