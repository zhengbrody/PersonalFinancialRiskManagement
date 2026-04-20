# MindMarket AI — Production Data Model Design

> Internal design document for migrating from single-user `portfolio_config.py`
> to a multi-user SaaS data model backed by Supabase/Postgres.
> Deferred implementation — requires answers to Q8 (auth method) + Q11 (DB choice).

**Scope**: Layered architecture, schema, migration plan, MVP slice, API surface,
UI changes. Target: one developer, 8-10 dev-days across 4 PRs.

---

## 1. Layered Architecture

| Layer | Responsibility | Files |
|-------|---------------|-------|
| **UI (Streamlit)** | Pages, forms, session_state, login widget | `pages/*.py`, `app.py`, `ui/components.py`, new `ui/auth.py`, `pages/0_Login.py`, `pages/11_Holdings.py` |
| **Domain models** | Plain Python dataclasses. No I/O. Cost-basis is a domain function taking `list[Lot]`. | `domain/models.py`, `domain/cost_basis.py`, `domain/pnl.py` |
| **Services (use cases)** | Orchestration: `add_transaction`, `run_risk_analysis(user_id)`. Takes `user_id`, returns domain objects. | `services/portfolio_service.py`, `services/risk_service.py`, `services/auth_service.py` |
| **Repository** | `SupabaseClient` + per-entity repos. Returns domain objects, not raw rows. Swap-point for tests (`InMemoryRepo`). | `repo/supabase_client.py`, `repo/accounts.py`, etc. |
| **DB (Postgres/Supabase)** | Tables, constraints, RLS, materialized views. Source of truth. | `db/migrations/0001_init.sql` |

**Direction rule**: UI → service → repo → DB. Never import DB code from UI.
`risk_engine.py`, `options_engine.py`, `backtest_engine.py` stay pure compute —
they receive a `Portfolio` from services, not from `portfolio_config`.

Anthropic calls live in `services/ai_service.py`, wrapped in
`credit_ledger.debit(user_id, n)` transactions. Prompt templates as
`.md` files in `services/prompts/` (versioned).

---

## 2. Schema (Postgres / Supabase)

```sql
-- auth.users is Supabase-native; referenced by UUID.

create table accounts (
  id           uuid primary key default gen_random_uuid(),
  user_id      uuid not null references auth.users(id) on delete cascade,
  name         text not null,
  broker       text,
  account_type text not null check (account_type in ('cash','margin','ira','crypto','other')),
  base_ccy     char(3) not null default 'USD',
  created_at   timestamptz not null default now()
);
create index on accounts(user_id);

create table instruments (
  symbol       text primary key,
  asset_class  text not null check (asset_class in ('equity','etf','crypto','option','cash')),
  sector       text,
  currency     char(3) not null default 'USD'
);

create table transactions (             -- IMMUTABLE ledger
  id           bigserial primary key,
  account_id   uuid not null references accounts(id) on delete restrict,
  user_id      uuid not null,
  symbol       text not null references instruments(symbol),
  tx_type      text not null check (tx_type in ('buy','sell','dividend','split','fee','transfer_in','transfer_out')),
  trade_date   date not null,
  settle_date  date,
  quantity     numeric(20,8) not null,  -- signed: +buy, -sell
  price        numeric(20,8),
  fees         numeric(20,8) not null default 0,
  split_ratio  numeric(10,4),
  notes        text,
  external_id  text,                    -- broker-assigned id, for dedupe on sync
  created_at   timestamptz not null default now(),
  unique (account_id, external_id)
);
create index on transactions(user_id, trade_date desc);

create table lots (                     -- open tax lots
  id           bigserial primary key,
  account_id   uuid not null references accounts(id) on delete cascade,
  user_id      uuid not null,
  symbol       text not null references instruments(symbol),
  open_tx_id   bigint not null references transactions(id),
  open_date    date not null,
  qty_open     numeric(20,8) not null,
  cost_per_share numeric(20,8) not null,
  closed_at    timestamptz
);
create index on lots(user_id, symbol) where closed_at is null;

create table realized_pnl (
  id           bigserial primary key,
  user_id      uuid not null,
  account_id   uuid not null references accounts(id),
  close_tx_id  bigint not null references transactions(id),
  lot_id       bigint not null references lots(id),
  qty          numeric(20,8) not null,
  proceeds     numeric(20,8) not null,
  cost         numeric(20,8) not null,
  pnl          numeric(20,8) generated always as (proceeds - cost) stored,
  method       text not null check (method in ('fifo','lifo','specid')),
  realized_at  date not null
);

create table price_snapshots (          -- shared reference data
  symbol       text not null references instruments(symbol),
  date         date not null,
  close        numeric(20,8) not null,
  adj_close    numeric(20,8),
  volume       bigint,
  primary key (symbol, date)
);

create table margin_settings (
  account_id         uuid primary key references accounts(id) on delete cascade,
  user_id            uuid not null,
  loan_balance       numeric(20,2) not null default 0,
  maintenance_req    numeric(5,4) not null default 0.25,
  initial_req        numeric(5,4) not null default 0.50,
  interest_rate_apr  numeric(5,4),
  updated_at         timestamptz not null default now()
);

create table risk_limits (
  user_id              uuid primary key references auth.users(id) on delete cascade,
  var_95_limit_pct     numeric(5,4),
  max_single_pos_pct   numeric(5,4) default 0.20,
  sector_limits        jsonb,
  max_leverage         numeric(5,2) default 1.50,
  updated_at           timestamptz not null default now()
);

create table audit_log (
  id         bigserial primary key,
  user_id    uuid not null,
  actor      uuid,
  entity     text not null,
  entity_id  text not null,
  action     text not null check (action in ('insert','update','delete','login','ai_call')),
  diff       jsonb,
  ip         inet,
  at         timestamptz not null default now()
);
create index on audit_log(user_id, at desc);
```

**RLS policy pattern** (applied to all user-scoped tables):

```sql
alter table transactions enable row level security;
create policy tx_select on transactions for select using (auth.uid() = user_id);
create policy tx_insert on transactions for insert with check (auth.uid() = user_id);
create policy tx_no_update on transactions for update using (false);   -- ledger is immutable
create policy tx_no_delete on transactions for delete using (false);
```

`instruments` and `price_snapshots` are shared — grant `select` to `authenticated`,
writes only to `service_role`.

---

## 3. Migration Path — 4 PRs

**PR 1 — Domain extraction, no DB yet (~1 day).**
Extract `Portfolio`, `Lot`, `Transaction` dataclasses in `domain/models.py`.
Add `services/portfolio_service.py::load_portfolio()` that today just reads
`portfolio_config.py` and returns a `Portfolio` object. Refactor `app.py`,
`calc_weights.py`, `pages/4_Portfolio.py`, `ui/shared_sidebar.py` to call
the service. Pure refactor — shippable, tests still pass.

**PR 2 — Supabase scaffolding + v1 tables (~2 days).**
Supabase project. `repo/supabase_client.py`. Migrations for `accounts`,
`instruments`, `transactions`, `lots`, `price_snapshots`. Seed `instruments`
from current `SECTOR_MAP`. Implement `AccountRepo`, `TransactionRepo`,
`LotRepo`. Feature flag `DB_MODE`: off → returns hardcoded portfolio
(local dev still works); on → reads from Supabase.

**PR 3 — Auth + CRUD UI (~2-3 days).**
`pages/0_Login.py` with Supabase auth. Gate all pages behind `require_auth()`.
Build `pages/11_Holdings.py` with *Positions* and *Transactions* tabs.
One-shot importer: parse existing `portfolio_config.py` into synthetic
`buy` transactions with `trade_date = today`,
`price = TOTAL_COST_BASIS / total_shares_today`. Flip `DB_MODE=on`.

**PR 4 — v2 features: margin, limits, audit (~2-3 days).**
Add `margin_settings`, `risk_limits`, `audit_log`, `realized_pnl`.
UI: margin editor in Holdings, Risk Limits on Risk page. Service:
`apply_transaction()` writes lot updates + realized_pnl + audit row in
one Supabase RPC transaction.

---

## 4. MVP Slice

**v1 (must-have for single-user flow):**
- Tables: `accounts`, `instruments`, `transactions`, `lots`, `price_snapshots`
- Services: `create_account`, `add_transaction`, `get_current_positions`, `run_risk_analysis`
- UI: login, holdings page (add transaction, see positions), existing Risk/Overview wired to service
- Cost basis: FIFO default, no UI toggle
- **No**: margin, risk limits, audit — existing app runs end-to-end

**v2:**
- `margin_settings`, `risk_limits`, `realized_pnl`, `audit_log`
- Broker sync (`external_id` dedupe), CSV import, cost-basis method picker
- Institutional polish without blocking launch

---

## 5. API Surface

No REST server yet. Streamlit is server-side Python — in-process service calls.
Use Supabase Python client inside repos; services are the public API.

```python
# services/portfolio_service.py
def get_portfolio(user_id: UUID) -> Portfolio
def add_transaction(user_id: UUID, tx: TransactionInput) -> Transaction
def list_transactions(user_id: UUID, account_id: UUID | None, limit=100) -> list[Transaction]
def get_positions(user_id: UUID, as_of: date | None = None) -> list[Position]
def set_margin(user_id: UUID, account_id: UUID, loan: Decimal, ...) -> MarginSettings

# services/risk_service.py
def run_risk_analysis(user_id: UUID, params: AnalysisParams) -> RiskReport
def check_limits(user_id: UUID, report: RiskReport) -> list[LimitViolation]

# services/auth_service.py
def current_user() -> User | None
def require_auth() -> User
```

REST (FastAPI) comes later for mobile/broker webhooks. Repository boundary
means adding FastAPI is just a new caller.

---

## 6. Streamlit UI Changes

**New pages:**
- `0_Login.py` (login / signup / magic link)
- `11_Holdings.py` (accounts + transactions + positions CRUD)
- `12_Settings.py` (risk limits + cost-basis method — v2)

**Pages to rewire** (every file importing `portfolio_config`):

| File | Change |
|------|--------|
| `app.py` | `fetch_live_weights`, `_reload_portfolio_config`, `compute_portfolio_meta` → call `portfolio_service.get_portfolio(current_user().id)` |
| `ui/shared_sidebar.py` | Sidebar portfolio summary from service; remove `importlib.reload` hack |
| `calc_weights.py` | Takes `Portfolio` argument; no module-level import |
| `pages/4_Portfolio.py` | Margin monitor from `margin_settings` via `portfolio_service.get_margin(account_id)` |
| `pages/1_Overview.py` | Cost basis from `sum(qty_open * cost_per_share)`, not `TOTAL_COST_BASIS` constant |
| `performance_attribution.py` | Reads historical shares from transactions so attribution handles mid-period buys/sells |

No other pages need changes beyond confirming session_state wiring (already works).

---

## Total Estimate

**~8-10 dev-days for one person**, across 4 PRs. Local dev keeps working throughout
via the `DB_MODE` flag in PR 2. Implementation blocked on:
- **Q8**: auth method (email+pw / OAuth / magic link)
- **Q11**: DB choice (Supabase recommended)
