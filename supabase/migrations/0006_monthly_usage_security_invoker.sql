-- supabase/migrations/0006_monthly_usage_security_invoker.sql
--
-- Fix Supabase Advisor finding:
--   SECURITY / CRITICAL / Security Definer View
--   View public.monthly_usage is defined with the SECURITY DEFINER property.
--
-- Postgres views are SECURITY DEFINER by default. For a public aggregate view
-- over user-scoped billing data, that is the wrong default: callers must stay
-- constrained by the underlying public.usage_events RLS policies.
--
-- This migration is idempotent and safe to run in the Supabase SQL editor.

create or replace view public.monthly_usage
with (security_invoker = true) as
select
    user_id,
    kind,
    date_trunc('month', created_at) as month,
    count(*)                         as event_count,
    sum(coalesce(tokens_in, 0))       as tokens_in,
    sum(coalesce(tokens_out, 0))      as tokens_out,
    sum(coalesce(cost_usd, 0))        as cost_usd
from public.usage_events
group by user_id, kind, date_trunc('month', created_at);
