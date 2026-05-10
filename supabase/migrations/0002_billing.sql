-- supabase/migrations/0002_billing.sql
--
-- Billing primitives for the freemium tier model:
--
--   profiles         — 1 row per user, joins to auth.users on user_id
--   subscriptions    — current plan + Stripe subscription state
--   usage_events     — append-only log of "I just ran an analysis"
--                       events; one row per call. Source of truth.
--   monthly_usage    — VIEW that aggregates usage_events into per-user
--                       per-month counts; faster reads than scanning
--                       events for every quota check.
--
-- Plan tiers (constants — also defined in libs/billing/usage.py):
--   free   2 analyses + 2 chat msgs per calendar month
--   basic  30 analyses + 100 chat msgs per calendar month  ($10/mo)
--   pro    150 analyses + 500 chat msgs per calendar month ($29/mo)
--
-- Apply via Supabase SQL Editor (same pattern as 0001_init.sql). All
-- statements are idempotent — safe to re-run.

-- ─────────────────────────────────────────────────────────────────
-- 1. profiles — extends auth.users with billing-relevant metadata
-- ─────────────────────────────────────────────────────────────────
create table if not exists public.profiles (
    user_id      uuid primary key references auth.users(id) on delete cascade,
    email        text,
    plan         text not null default 'free'
                  check (plan in ('free', 'basic', 'pro')),
    created_at   timestamptz not null default now(),
    updated_at   timestamptz not null default now()
);

drop trigger if exists profiles_touch_updated_at on public.profiles;
create trigger profiles_touch_updated_at
    before update on public.profiles
    for each row execute function public.touch_updated_at();

-- Auto-create a profile row on signup. Supabase fires this when
-- auth.users gets a new INSERT (i.e. someone completes sign-up).
create or replace function public.handle_new_user()
returns trigger as $$
begin
    insert into public.profiles (user_id, email, plan)
    values (new.id, new.email, 'free')
    on conflict (user_id) do nothing;
    return new;
end;
$$ language plpgsql security definer;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
    after insert on auth.users
    for each row execute function public.handle_new_user();

-- Backfill: any existing auth.users without a profile row gets one.
insert into public.profiles (user_id, email, plan)
select id, email, 'free' from auth.users
on conflict (user_id) do nothing;


-- ─────────────────────────────────────────────────────────────────
-- 2. subscriptions — Stripe sync target (Sprint 2 will populate this)
-- ─────────────────────────────────────────────────────────────────
create table if not exists public.subscriptions (
    user_id              uuid primary key references auth.users(id) on delete cascade,
    stripe_customer_id   text,
    stripe_subscription_id text,
    plan                 text not null default 'free'
                          check (plan in ('free', 'basic', 'pro')),
    status               text not null default 'active'
                          check (status in ('active', 'past_due', 'canceled', 'trialing')),
    current_period_start timestamptz,
    current_period_end   timestamptz,
    cancel_at_period_end boolean not null default false,
    created_at           timestamptz not null default now(),
    updated_at           timestamptz not null default now()
);

drop trigger if exists subscriptions_touch_updated_at on public.subscriptions;
create trigger subscriptions_touch_updated_at
    before update on public.subscriptions
    for each row execute function public.touch_updated_at();

create index if not exists subscriptions_stripe_sub_idx
    on public.subscriptions (stripe_subscription_id);

create index if not exists subscriptions_stripe_customer_idx
    on public.subscriptions (stripe_customer_id);


-- ─────────────────────────────────────────────────────────────────
-- 3. usage_events — append-only log of every billable action
-- ─────────────────────────────────────────────────────────────────
-- We log the EVENT, not the cost. Cost computation is left to the
-- application (LLM provider / model dependent). Keeping rows narrow
-- means an "am I over quota" query touches one index, fast.
create table if not exists public.usage_events (
    id           uuid primary key default uuid_generate_v4(),
    user_id      uuid not null references auth.users(id) on delete cascade,
    kind         text not null
                  check (kind in ('analysis', 'chat', 'tool_call')),
    provider     text,                   -- 'anthropic' | 'deepseek' | 'ollama' | 'fmp' | etc.
    model        text,                   -- 'claude-sonnet-4-5' | 'deepseek-chat' | etc.
    tokens_in    integer default 0,
    tokens_out   integer default 0,
    cost_usd     numeric(10, 6) default 0,
    metadata     jsonb default '{}'::jsonb,
    created_at   timestamptz not null default now()
);

create index if not exists usage_events_user_month_idx
    on public.usage_events (user_id, kind, created_at);


-- ─────────────────────────────────────────────────────────────────
-- 4. monthly_usage — aggregate view (read-side)
-- ─────────────────────────────────────────────────────────────────
-- Per user per kind per calendar month. Used by quota checks. Views
-- inherit RLS from underlying tables, so we don't need separate policies.
create or replace view public.monthly_usage as
select
    user_id,
    kind,
    date_trunc('month', created_at) as month,
    count(*)                          as event_count,
    sum(coalesce(tokens_in, 0))       as tokens_in,
    sum(coalesce(tokens_out, 0))      as tokens_out,
    sum(coalesce(cost_usd, 0))        as cost_usd
from public.usage_events
group by user_id, kind, date_trunc('month', created_at);


-- ─────────────────────────────────────────────────────────────────
-- 5. Row Level Security
-- ─────────────────────────────────────────────────────────────────
-- Same load-bearing pattern as portfolios: every SELECT/UPDATE filtered
-- to auth.uid(). Server-side admin scripts using the service-role key
-- bypass RLS by design (that's the WHOLE point of service-role).

alter table public.profiles      enable row level security;
alter table public.subscriptions enable row level security;
alter table public.usage_events  enable row level security;

-- profiles
drop policy if exists profiles_select_own on public.profiles;
create policy profiles_select_own on public.profiles
    for select using (auth.uid() = user_id);

-- Do not let clients update profiles directly. `profiles.plan` is the
-- source of truth for quota checks, so allowing `UPDATE own profile`
-- would let a user self-upgrade from free to pro. Stripe/admin service-role
-- code may still update this table because service-role bypasses RLS.
drop policy if exists profiles_update_own on public.profiles;

-- INSERT/UPDATE policy: only the trigger handle_new_user() (security
-- definer) and future Stripe/admin service-role code should write here.
-- Anon/authenticated clients should not INSERT or UPDATE directly.

-- subscriptions
drop policy if exists subs_select_own on public.subscriptions;
create policy subs_select_own on public.subscriptions
    for select using (auth.uid() = user_id);

-- INSERT/UPDATE on subscriptions only via Stripe webhook (service role).
-- No client-side policies → blocked by default.

-- usage_events: SELECT own, INSERT own (server-side recorder uses
-- the user's JWT to authenticate, so auth.uid() is set correctly).
drop policy if exists usage_select_own on public.usage_events;
create policy usage_select_own on public.usage_events
    for select using (auth.uid() = user_id);

drop policy if exists usage_insert_own on public.usage_events;
create policy usage_insert_own on public.usage_events
    for insert with check (auth.uid() = user_id);


-- ─────────────────────────────────────────────────────────────────
-- 6. Smoke verification (run after applying)
-- ─────────────────────────────────────────────────────────────────
-- select count(*) from public.profiles;             -- should equal auth.users count
-- select count(*) from public.usage_events;         -- 0 (fresh)
-- select * from public.monthly_usage limit 1;       -- empty until events arrive
