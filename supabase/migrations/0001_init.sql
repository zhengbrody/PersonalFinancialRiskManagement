-- supabase/migrations/0001_init.sql
--
-- Initial schema for MindMarket AI multi-user mode.
--
-- How to apply (Supabase Dashboard):
--   1. Open the project at supabase.com
--   2. Left sidebar → SQL Editor → "+ New query"
--   3. Paste the contents of THIS file
--   4. Click "Run" (or Cmd-Enter)
--   5. Verify: Left sidebar → Database → Tables → see `portfolios`
--
-- All operations are idempotent: re-running this file is safe.
-- Wrap your changes in IF NOT EXISTS / OR REPLACE so future migrations
-- can be applied repeatedly.

-- ─────────────────────────────────────────────────────────────────
-- 1. uuid_generate_v4() — Postgres extension, ships with Supabase
-- ─────────────────────────────────────────────────────────────────
create extension if not exists "uuid-ossp";


-- ─────────────────────────────────────────────────────────────────
-- 2. portfolios table
-- ─────────────────────────────────────────────────────────────────
-- holdings is jsonb so we don't have to define a separate child table
-- for now. Shape per row:
--   {
--     "AAPL": {"shares": 100, "avg_cost": 175.40},
--     "TSLA": {"shares": 50,  "avg_cost": 220.00}
--   }
-- avg_cost is optional — if omitted, P&L just won't render for that
-- ticker (matches existing portfolio_config.py semantics).
create table if not exists public.portfolios (
    id          uuid primary key default uuid_generate_v4(),
    user_id     uuid not null references auth.users(id) on delete cascade
                default auth.uid(),    -- so client doesn't need to send it
    name        text not null check (length(name) between 1 and 80),
    holdings    jsonb not null default '{}'::jsonb,
    margin_loan numeric(14, 2) not null default 0
                check (margin_loan >= 0),
    is_default  boolean not null default false,
    created_at  timestamptz not null default now(),
    updated_at  timestamptz not null default now()
);

-- Auto-bump updated_at on UPDATE
create or replace function public.touch_updated_at()
returns trigger as $$
begin
    new.updated_at = now();
    return new;
end;
$$ language plpgsql;

drop trigger if exists portfolios_touch_updated_at on public.portfolios;
create trigger portfolios_touch_updated_at
    before update on public.portfolios
    for each row execute function public.touch_updated_at();

-- Index for the most common lookup: "give me my portfolios, default first"
create index if not exists portfolios_user_default_idx
    on public.portfolios (user_id, is_default desc, created_at desc);


-- ─────────────────────────────────────────────────────────────────
-- 3. Row Level Security
-- ─────────────────────────────────────────────────────────────────
-- This is the load-bearing security control. Without RLS enabled,
-- ANY authenticated user could SELECT * from portfolios and read every
-- other user's holdings. With RLS enabled + policies below, the database
-- automatically rewrites every query to add `WHERE user_id = auth.uid()`.

alter table public.portfolios enable row level security;

-- Policy: SELECT only your own rows
drop policy if exists portfolios_select_own on public.portfolios;
create policy portfolios_select_own on public.portfolios
    for select using (auth.uid() = user_id);

-- Policy: INSERT — must declare yourself as the user_id (or omit, which
-- defaults to auth.uid() per the column DEFAULT)
drop policy if exists portfolios_insert_own on public.portfolios;
create policy portfolios_insert_own on public.portfolios
    for insert with check (auth.uid() = user_id);

-- Policy: UPDATE only your own rows
drop policy if exists portfolios_update_own on public.portfolios;
create policy portfolios_update_own on public.portfolios
    for update using (auth.uid() = user_id)
                with check (auth.uid() = user_id);

-- Policy: DELETE only your own rows
drop policy if exists portfolios_delete_own on public.portfolios;
create policy portfolios_delete_own on public.portfolios
    for delete using (auth.uid() = user_id);


-- ─────────────────────────────────────────────────────────────────
-- 4. Smoke verification (manual)
-- ─────────────────────────────────────────────────────────────────
-- After running this file, in the SQL editor try:
--
--     select count(*) from public.portfolios;
--     -- Expected: 0  (table exists, empty)
--
-- Then in Authentication → Users, create a test user manually and try
-- inserting via the Table Editor — Supabase will refuse without a
-- valid user JWT, which proves RLS is on.
