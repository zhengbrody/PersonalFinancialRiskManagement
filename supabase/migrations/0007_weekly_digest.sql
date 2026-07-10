-- 0007 — weekly risk digest email: per-user preference + send log.
--
-- Applied by hand in the Supabase SQL editor (project convention). The
-- backend fail-softs while these tables are absent: the digest run reports
-- "not_ready" and the /settings toggle hides — same degrade-silently
-- contract as 0004's portfolio_snapshots.
--
-- Semantics (updated 2026-07, enforced in code — no SQL change): NO
-- digest_prefs row = NOT subscribed. The digest is EXPLICIT OPT-IN
-- (enabled=true row, set from Settings); enabled=false = opted out (set via
-- the authed /settings toggle or the signed unsubscribe link in the email).

create table if not exists public.digest_prefs (
  user_id uuid primary key references auth.users (id) on delete cascade,
  enabled boolean not null default true,
  updated_at timestamptz not null default now()
);

alter table public.digest_prefs enable row level security;

-- Users manage their own preference; the unsubscribe link path uses the
-- service role (bypasses RLS) because the reader is not signed in.
create policy digest_prefs_select_own on public.digest_prefs
  for select using (auth.uid() = user_id);
create policy digest_prefs_insert_own on public.digest_prefs
  for insert with check (auth.uid() = user_id);
create policy digest_prefs_update_own on public.digest_prefs
  for update using (auth.uid() = user_id);

-- Send log — service-role only (dedupe + audit). No user policies on
-- purpose: with RLS enabled and no policies, only the service role reads it.
create table if not exists public.digest_sends (
  id bigint generated always as identity primary key,
  user_id uuid not null references auth.users (id) on delete cascade,
  sent_at timestamptz not null default now()
);

create index if not exists digest_sends_user_time
  on public.digest_sends (user_id, sent_at desc);

alter table public.digest_sends enable row level security;
