feat(risk): financing resilience — separate a margin-funded book from a cash-equivalent sleeve

Two accounts can carry the same gross leverage for entirely different reasons:
one is genuinely funded by borrowing against risk assets, the other holds a
Treasury cash-management sleeve alongside an offsetting margin loan. This adds a
deterministic, NON-SCORING block that says which is which, without letting a
low-volatility holding be rewarded twice.

## What it adds

`financing_resilience` on the active Score and Risk Report responses: gross
financing leverage, cash-equivalent market value, margin liquidation coverage,
residual margin and post-offset risk-asset leverage. SGOV/BIL/SHV/TBIL/TFLO/USFR
are auto-classified from a conservative registry; a holding can override that
with `risk_asset` / `cash_equivalent`, persisted in the holdings JSONB (no
migration).

## What it deliberately does NOT change

Score math and score version. A cash-equivalent stays a priced security with its
observed returns, volatility and drawdown in the engine — it is never converted
into the constant-return cash leg. A test now asserts that invariant directly
(same holdings, toggled `liquidity_class` → identical `overall_score`,
`score_version` and dimensions); the previous test only checked `cash_weight`,
which is a proxy.

## Review findings folded in

An adversarial review of the working draft found two defects that reached beyond
the stated scope, plus several smaller ones. All are fixed here:

- **The leverage dimension regressed for every book holding idle cash.**
  `post_offset = risk_assets / net_equity` drops below 1.0 whenever any cash
  exists, so an unlevered account reported "0.67x" while its own explanation
  said "unlevered" — and the historical percentile was silently suppressed,
  because that series is on the gross basis. The dimension is now re-based only
  when there is an actual loan to offset.
- **A self-attested classification could drive a risk status.** Marking one
  volatile name "cash-like" turned a 1.7x book into "calm"/"Covered", and
  `classification_source` — computed, typed and shipped — was rendered nowhere.
  The status now floors at the gross-leverage band whenever a counted offset is
  user-classified, and both surfaces name who classified each holding and say it
  is taken at the user's word, not verified.
- Leverage is clamped at the same 10x ceiling the score path uses, so one screen
  can't show "10.00x" beside "10000000.01x" for a near-wiped-out account.
- The override lookup normalises both sides; a lower-cased holdings key used to
  drop the override, and it failed toward MORE coverage.
- Unpriced holdings are counted and disclosed, so a book whose risk assets
  failed to price can't read "impaired" on the strength of missing data.
- The block is fail-soft: it degrades to null rather than failing the endpoint,
  matching the convention for additive response blocks.
- Coverage display is clamped at 100% (payload keeps the raw ratio), every
  status has a friendly label, and the card no longer renders empty tiles for a
  no-margin book.

Coverage is labelled throughout as a current-value, pre-tax/spread/settlement
estimate — not a broker maintenance guarantee — and modelled borrow drag is
never presented as a live broker APR.

Tests: backend 1122, legacy 839, frontend 531. black/ruff/mypy/tsc/eslint/build
clean; OpenAPI and generated types regenerated on the pinned toolchain.
