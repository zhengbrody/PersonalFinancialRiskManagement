-- 0011 — atomic active-portfolio switch.
--
-- "Active portfolio" == the single row with is_default=true (this is already
-- how every backend + frontend read path resolves "which book?"). Today the
-- switch is a non-atomic 2-step demote in app code (libs/auth/portfolios.py),
-- which can transiently leave 0 or 2+ defaults if interrupted or bypassed. This
-- adds a single-statement, RLS-enforced, atomic switch so a user always has
-- exactly one active portfolio.
--
-- PostgREST cannot express a per-row computed SET (is_default = (id = target)),
-- so the atomic swap lives in a SQL function called via .rpc(). The backend
-- calls it with the caller's JWT, so auth.uid() is the caller and RLS applies.
--
-- Purely ADDITIVE (new function only; no table/column/data change) and single-
-- transaction safe. CREATE OR REPLACE makes it re-runnable (verify-safe) but the
-- migration is not meant to be applied twice. Applied via
-- .github/workflows/db-migrate.yml (psql --single-transaction -v ON_ERROR_STOP=1).
--
-- Rollback: `drop function if exists public.activate_portfolio(uuid);`. The app
-- keeps the legacy PATCH is_default=true path working, so dropping the function
-- only removes the atomic switch (callers fall back to the 2-step demote).

create or replace function public.activate_portfolio(p_id uuid)
returns public.portfolios
language plpgsql
security invoker
set search_path = public, pg_temp
as $$
declare
  activated public.portfolios;
begin
  -- Ownership gate under RLS: a non-owned OR non-existent id is invisible to
  -- this SELECT, so both return NULL identically (no existence leak) and
  -- nothing is mutated.
  if not exists (
    select 1 from public.portfolios where id = p_id and user_id = auth.uid()
  ) then
    return null;
  end if;

  -- Atomic single-default: exactly one row true, all the caller's others false,
  -- in ONE statement (no transient 2-defaults window). RLS already scopes the
  -- write to the caller; the explicit user_id = auth.uid() is defense-in-depth.
  -- The `is_default IS DISTINCT FROM (id = p_id)` predicate restricts the write
  -- to ONLY the (≤2) rows whose flag actually flips — a plain
  -- `where user_id = auth.uid()` would restamp updated_at (via the
  -- touch_updated_at trigger) on EVERY book, an unnecessary write amplification
  -- vs the legacy 2-step demote. The (≤2) flipped rows still get restamped;
  -- the UI derives "data freshness" from the score's as_of, not this column.
  update public.portfolios
     set is_default = (id = p_id),
         updated_at = now()
   where user_id = auth.uid()
     and is_default is distinct from (id = p_id);

  select * into activated
    from public.portfolios
   where id = p_id and user_id = auth.uid();
  return activated;
end;
$$;

-- Authenticated callers only. Postgres grants EXECUTE to PUBLIC by default on
-- CREATE FUNCTION, so revoke that first (defense-in-depth / Supabase advisor) —
-- anon has no auth.uid() so the gate already no-ops, but there's no reason to
-- expose the RPC to it.
revoke execute on function public.activate_portfolio(uuid) from public;
grant execute on function public.activate_portfolio(uuid) to authenticated;
