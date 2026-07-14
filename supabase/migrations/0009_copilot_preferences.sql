-- 0009 — Copilot user-CONFIRMED preferences (Copilot PR3).
--
-- ONE row per user (user_id is the primary key). ONLY an explicit user
-- confirmation writes here: the authed PUT /api/v1/copilot/preferences sets
-- confirmed_at — the app NEVER auto-infers preferences from chats, holdings,
-- age or behavior, and confirmed_at IS NULL is treated as "no memory".
-- Preferences shape EXPLANATION EMPHASIS only; they never override the
-- DataConfidence / grounding / conviction gates.
--
-- Purely ADDITIVE (new table only; no existing data touched) and single-
-- transaction safe. Applied via .github/workflows/db-migrate.yml
-- (psql --single-transaction -v ON_ERROR_STOP=1).

create table if not exists public.copilot_preferences (
  user_id uuid primary key references auth.users (id) on delete cascade,
  risk_tolerance smallint check (risk_tolerance between 1 and 5),
  investment_horizon text check (investment_horizon in ('short', 'medium', 'long')),
  liquidity_need text check (liquidity_need in ('low', 'medium', 'high')),
  concentration_limit numeric check (concentration_limit >= 0 and concentration_limit <= 1),
  margin_limit numeric check (margin_limit >= 1 and margin_limit <= 10),
  metadata jsonb not null default '{}'::jsonb,
  confirmed_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table public.copilot_preferences enable row level security;

-- Users manage ONLY their own row (auth.uid() = user_id on every verb).
create policy copilot_prefs_select_own on public.copilot_preferences
  for select using (auth.uid() = user_id);
create policy copilot_prefs_insert_own on public.copilot_preferences
  for insert with check (auth.uid() = user_id);
create policy copilot_prefs_update_own on public.copilot_preferences
  for update using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy copilot_prefs_delete_own on public.copilot_preferences
  for delete using (auth.uid() = user_id);
