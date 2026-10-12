# Combined funding evidence before deployment

Combined sale / debt repayment / Put scenarios can issue a separately signed
receipt when `MINDMARKET_FUNDING_SCENARIOS_SAVE_ENABLED` is enabled and a signing
key is configured. It remains disabled by default. Apply migration `0019` only
through the normal reviewed deployment process; local tests do not migrate a
production database.

The receipt captures the authenticated owner, original account and revision,
original signed reduction receipt, explicitly confirmed scenario assumptions,
complete combined result and implementation fingerprint. First save requires
unchanged implementation and deterministic replay of the original reduction and
combined arithmetic. Only random presentation IDs are ignored during replay.
The 15-minute save window starts at the original reduction capture, not when the
user adds the Put assumptions. Database time, active account and revision are
checked again within the transaction.

`POST /api/v1/copilot/funding-plans/{result_id}/confirm` requires explicit consent.
The transaction writes a draft RiskPlan and immutable confirmation atomically,
with owner-scoped retry locking. The RiskPlan kind is `funding_scenarios`, with
`captured_funding` evidence; it must not use the legacy HealthScore review path.
An uncertain write can be retried using the identical original receipt.

`GET /api/v1/copilot/funding-plans/{result_id}` authenticates the historical
original without reinterpreting it under newer calculations. Manual
`POST .../{result_id}/review` checks current account values, revision,
implementation and expiry status. Even an unchanged account produces
`assumptions_need_confirmation`, never a claim of current suitability. Review
checks no live quote, verifies no broker rule, infers no execution and changes no
holdings. Original confirmed evidence remains unchanged.

Saving preserves analysis, not a transaction or an instruction to trade.
Financing permissions, current buying power, interest and option execution
quotes remain unknown. Changes to source data and model code require a fresh
calculation rather than rewriting previously confirmed evidence. Continuous
monitoring and automatic combined-plan notifications are outside this endpoint.

Verification is covered by `test_funding_plans.py` (actual deterministic replay,
signatures, scope, expiry, implementation, tampering, historical reads, review,
consent and capacity release) and `test_funding_plans_postgres.py` (real local
PostgreSQL transaction, concurrent retries, row isolation, clock and revision
fences). No external market requests are used by these checks.
