-- 0008 — auditable Health Score methodology version on snapshots.
--
-- Applied by hand in the Supabase SQL editor (project convention). Idempotent
-- (`add column if not exists`); the backend fail-softs if this column is absent
-- — the "what changed?" engine simply treats an unknown version as
-- not-comparable, same degrade-silently contract as 0004/0007.
--
-- WHY: every snapshot must record WHICH methodology version produced its score
-- (single source: libs/mindmarket_core/score_version.py). Two snapshots with
-- different versions are NOT directly comparable — the trend UI must say
-- "methodology changed", not report the delta as a market/holdings move.
--
-- IMPORTANT — do NOT backfill existing rows with the CURRENT version. Those
-- snapshots predate versioning; their methodology provenance is unverifiable,
-- so they are marked 'legacy' (honest unknown), never the current label. The
-- `default 'legacy'` also covers any row written during the deploy window
-- before the new backend code (which sends the real version) rolls out.

alter table public.portfolio_snapshots
    add column if not exists score_version text not null default 'legacy';

-- Existing rows explicitly marked legacy (the default already did this for rows
-- present at migration time; this makes the intent auditable and re-runnable).
update public.portfolio_snapshots
    set score_version = 'legacy'
    where score_version is null;
