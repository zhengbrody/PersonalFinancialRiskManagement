-- supabase/migrations/0004_risk_memory.sql
--
-- Risk Memory + AI Action Loop — persistent state so MindMarket feels like
-- a copilot with memory, not a one-shot dashboard.
--
-- New tables (both fully idempotent — safe to re-run):
--   1. portfolio_snapshots
--      One row per successful analysis run. Used by "What changed since
--      last run" (deterministic delta) and by the AI chat as recall
--      context. NEVER store raw price series here — only headline metrics
--      + top-N positions/sectors as compact JSONB.
--
--   2. saved_insights
--      User-curated AI digests / chat answers. Lets users revisit a good
--      analysis later. Stored verbatim with provenance (provider, model,
--      tokens, cost) so we can audit and so users can see what they were
--      reading at the time.
--
-- Both tables follow the same RLS pattern as `portfolios`:
--   - user_id DEFAULT auth.uid() so client doesn't need to send it
--   - SELECT/INSERT/DELETE policies restrict to auth.uid() = user_id
--   - Service-role key (used by webhook + admin) bypasses RLS by design.
--
-- Apply via Supabase SQL Editor (same pattern as 0001-0003).

create extension if not exists "uuid-ossp";


-- ─────────────────────────────────────────────────────────────────
-- 1. portfolio_snapshots — one row per completed analysis
-- ─────────────────────────────────────────────────────────────────
-- We DO NOT FK to portfolios.id because:
--   (a) anonymous / demo-portfolio analyses won't have a portfolio row;
--   (b) we want snapshot history to survive portfolio rename/delete.
-- The application is responsible for cleaning up orphans if it cares.
create table if not exists public.portfolio_snapshots (
    id                  uuid primary key default uuid_generate_v4(),
    user_id             uuid not null references auth.users(id) on delete cascade
                          default auth.uid(),
    portfolio_id        uuid,
    source              text not null default 'manual'
                          check (length(source) between 1 and 40),

    -- Headline capital + leverage figures (numeric, not jsonb, so we can
    -- aggregate / chart without parsing JSON).
    net_equity          numeric(14, 2),
    total_long          numeric(14, 2),
    cash_balance        numeric(14, 2),
    margin_loan         numeric(14, 2),
    contributed_capital numeric(14, 2),
    leverage            numeric(8, 4),

    -- Compact JSONB blobs for analysis state. Keep small — these are
    -- summaries, not the full report. The application caps these to
    -- top-N positions/sectors before insert.
    top_positions       jsonb not null default '[]'::jsonb,
    sector_exposure     jsonb not null default '{}'::jsonb,
    risk_metrics        jsonb not null default '{}'::jsonb,
    data_quality        jsonb not null default '{}'::jsonb,

    created_at          timestamptz not null default now()
);

-- "Give me my last N snapshots, newest first" — the only query pattern
-- we run on this table.
create index if not exists portfolio_snapshots_user_created_idx
    on public.portfolio_snapshots (user_id, created_at desc);

alter table public.portfolio_snapshots enable row level security;

drop policy if exists portfolio_snapshots_select_own on public.portfolio_snapshots;
create policy portfolio_snapshots_select_own on public.portfolio_snapshots
    for select using (auth.uid() = user_id);

drop policy if exists portfolio_snapshots_insert_own on public.portfolio_snapshots;
create policy portfolio_snapshots_insert_own on public.portfolio_snapshots
    for insert with check (auth.uid() = user_id);

drop policy if exists portfolio_snapshots_delete_own on public.portfolio_snapshots;
create policy portfolio_snapshots_delete_own on public.portfolio_snapshots
    for delete using (auth.uid() = user_id);

-- Intentionally no UPDATE policy: snapshots are immutable by design.
-- A user who wants to "correct" a snapshot should run a new analysis.


-- ─────────────────────────────────────────────────────────────────
-- 2. saved_insights — user-curated AI outputs
-- ─────────────────────────────────────────────────────────────────
create table if not exists public.saved_insights (
    id          uuid primary key default uuid_generate_v4(),
    user_id     uuid not null references auth.users(id) on delete cascade
                  default auth.uid(),
    portfolio_id uuid,

    -- Where this insight came from in the app (e.g. "overview" / "risk" /
    -- "chat" / "ticker_research"). Used for grouping in the Saved Insights
    -- list — not a foreign key.
    page        text not null check (length(page) between 1 and 60),

    title       text not null check (length(title) between 1 and 200),
    content     text not null check (length(content) between 1 and 20000),

    -- Provenance: which AI produced this, how much it cost. Lets us
    -- show "answered by Claude Sonnet @ $0.014" and audit later if a
    -- user disputes accuracy.
    provider    text,
    model       text,
    tokens_in   integer not null default 0 check (tokens_in >= 0),
    tokens_out  integer not null default 0 check (tokens_out >= 0),
    cost_usd    numeric(10, 6) not null default 0 check (cost_usd >= 0),

    -- Free-form metadata bag: data sources, confidence level, snapshot id,
    -- chat thread id, etc. JSONB so we can extend without migrations.
    metadata    jsonb not null default '{}'::jsonb,

    created_at  timestamptz not null default now()
);

create index if not exists saved_insights_user_created_idx
    on public.saved_insights (user_id, created_at desc);

alter table public.saved_insights enable row level security;

drop policy if exists saved_insights_select_own on public.saved_insights;
create policy saved_insights_select_own on public.saved_insights
    for select using (auth.uid() = user_id);

drop policy if exists saved_insights_insert_own on public.saved_insights;
create policy saved_insights_insert_own on public.saved_insights
    for insert with check (auth.uid() = user_id);

drop policy if exists saved_insights_delete_own on public.saved_insights;
create policy saved_insights_delete_own on public.saved_insights
    for delete using (auth.uid() = user_id);


-- ─────────────────────────────────────────────────────────────────
-- 3. Smoke verification (after applying)
-- ─────────────────────────────────────────────────────────────────
-- select count(*) from public.portfolio_snapshots;  -- 0
-- select count(*) from public.saved_insights;       -- 0
-- Insert a snapshot via your authed app then re-check.
