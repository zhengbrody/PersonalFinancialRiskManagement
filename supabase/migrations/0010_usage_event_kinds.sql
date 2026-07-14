-- 0010 — widen the usage_events.kind CHECK to include 'anthropic_topup'.
--
-- WHY: /admin's "set Claude balance after a top-up" (PR #103, 2026-06-17)
-- stores its marker as a usage_events row with kind='anthropic_topup', but
-- 0002's CHECK only allowed ('analysis','chat','tool_call') — the insert was
-- rejected (23514) and the fail-soft telemetry writer swallowed it, so the
-- endpoint returned 200 while persisting NOTHING (confirmed empirically
-- 2026-07-14). This relaxes the constraint to admit the marker kind.
--
-- SAFETY: constraint-widening only — no data is read, modified or deleted;
-- every existing row already satisfies the wider check, so the ADD validates
-- instantly. Single-transaction via db-migrate.yml (drop+add is atomic).

alter table public.usage_events
  drop constraint usage_events_kind_check;

alter table public.usage_events
  add constraint usage_events_kind_check
  check (kind in ('analysis', 'chat', 'tool_call', 'anthropic_topup'));
