-- 0012 — Risk Ops: saved risk PLANS, alert lifecycle STATE, and per-user
-- JOURNEY milestones. Three additive tables, all RLS-scoped to the caller.
--
-- Purely ADDITIVE (new tables only; no existing data touched) and single-
-- transaction safe. Applied via .github/workflows/db-migrate.yml
-- (psql --single-transaction -v ON_ERROR_STOP=1).
--
-- Rollback: drop table public.{risk_plans,risk_alert_states,user_journey_state};
-- (each is independent; no other object depends on them).

-- ── risk_plans — a saved ANALYSIS (never an order; the app never writes to
--    holdings from a plan) ─────────────────────────────────────────────────
create table if not exists public.risk_plans (
  id uuid primary key default uuid_generate_v4(),
  user_id uuid not null references auth.users (id) on delete cascade default auth.uid(),
  -- A plan is about a specific book; deleting the book cascades its plans.
  portfolio_id uuid not null references public.portfolios (id) on delete cascade,
  title text not null check (length(title) between 1 and 200),
  status text not null default 'draft'
    check (status in ('draft', 'active', 'resolved', 'archived')),
  source text not null
    check (source in ('score', 'risk', 'scenario', 'research', 'copilot')),
  hypothesis text check (hypothesis is null or length(hypothesis) <= 2000),
  baseline jsonb not null default '{}'::jsonb,
  proposed_changes jsonb not null default '{}'::jsonb,
  expected_impact jsonb not null default '{}'::jsonb,
  data_confidence jsonb not null default '{}'::jsonb,
  review_at timestamptz,
  reviewed_at timestamptz,
  resolved_at timestamptz,
  outcome jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists risk_plans_user_portfolio_idx
  on public.risk_plans (user_id, portfolio_id, created_at desc);
create index if not exists risk_plans_review_idx
  on public.risk_plans (user_id, review_at)
  where status in ('draft', 'active') and review_at is not null;

alter table public.risk_plans enable row level security;

-- Users operate ONLY on their own plans, and only against their OWN portfolios
-- (the portfolio_id must resolve to a book they own — no cross-user reference).
create policy risk_plans_select_own on public.risk_plans
  for select using (auth.uid() = user_id);
create policy risk_plans_insert_own on public.risk_plans
  for insert with check (
    auth.uid() = user_id
    and exists (select 1 from public.portfolios p
                where p.id = portfolio_id and p.user_id = auth.uid())
  );
create policy risk_plans_update_own on public.risk_plans
  for update using (auth.uid() = user_id)
  with check (
    auth.uid() = user_id
    and exists (select 1 from public.portfolios p
                where p.id = portfolio_id and p.user_id = auth.uid())
  );
create policy risk_plans_delete_own on public.risk_plans
  for delete using (auth.uid() = user_id);

-- ── risk_alert_states — lifecycle for a deterministic alert's STABLE episode
--    id (new/seen/snoozed/resolved); one row per (user, portfolio, alert_key) ─
create table if not exists public.risk_alert_states (
  id uuid primary key default uuid_generate_v4(),
  user_id uuid not null references auth.users (id) on delete cascade default auth.uid(),
  portfolio_id uuid not null references public.portfolios (id) on delete cascade,
  alert_key text not null check (length(alert_key) between 1 and 200),
  state text not null default 'new'
    check (state in ('new', 'seen', 'snoozed', 'resolved')),
  snooze_until timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (user_id, portfolio_id, alert_key)
);

alter table public.risk_alert_states enable row level security;

create policy risk_alert_states_select_own on public.risk_alert_states
  for select using (auth.uid() = user_id);
create policy risk_alert_states_insert_own on public.risk_alert_states
  for insert with check (
    auth.uid() = user_id
    and exists (select 1 from public.portfolios p
                where p.id = portfolio_id and p.user_id = auth.uid())
  );
create policy risk_alert_states_update_own on public.risk_alert_states
  for update using (auth.uid() = user_id)
  with check (
    auth.uid() = user_id
    and exists (select 1 from public.portfolios p
                where p.id = portfolio_id and p.user_id = auth.uid())
  );
create policy risk_alert_states_delete_own on public.risk_alert_states
  for delete using (auth.uid() = user_id);

-- ── user_journey_state — ONE row per user, milestone timestamps only (never
--    holdings / tickers / amounts / question text) ────────────────────────────
create table if not exists public.user_journey_state (
  user_id uuid primary key references auth.users (id) on delete cascade default auth.uid(),
  first_portfolio_at timestamptz,
  first_score_at timestamptz,
  first_driver_viewed_at timestamptz,
  first_stress_test_at timestamptz,
  first_plan_at timestamptz,
  first_plan_reviewed_at timestamptz,
  last_workspace_view timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table public.user_journey_state enable row level security;

create policy user_journey_select_own on public.user_journey_state
  for select using (auth.uid() = user_id);
create policy user_journey_insert_own on public.user_journey_state
  for insert with check (auth.uid() = user_id);
create policy user_journey_update_own on public.user_journey_state
  for update using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy user_journey_delete_own on public.user_journey_state
  for delete using (auth.uid() = user_id);
