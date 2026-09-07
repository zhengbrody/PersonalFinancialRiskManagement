-- Local opt-in foundation. Apply only after staging RLS/concurrency acceptance.
-- JWT/RLS is ownership, NOT evidence authenticity; API checks the server HMAC.
-- No UPDATE policy on evidence. Deleting its draft plan removes evidence too.

alter table public.portfolios add column if not exists comparison_revision uuid
    not null default pg_catalog.gen_random_uuid();

-- Serialize all JWT-scoped portfolio writes before acquiring row locks. This
-- also closes the new-default INSERT phantom while a confirmation is saving.
create or replace function public.lock_comparison_portfolio_scope()
returns trigger language plpgsql set search_path = public, pg_temp as $$
begin
    if auth.uid() is not null then
        perform pg_advisory_xact_lock(hashtextextended('mindmarket:portfolio-write:' || auth.uid()::text, 0));
    end if;
    return null;
end;
$$;
drop trigger if exists portfolios_comparison_scope on public.portfolios;
create trigger portfolios_comparison_scope before insert or update or delete on public.portfolios
for each statement execute function public.lock_comparison_portfolio_scope();

create or replace function public.bump_comparison_revision()
returns trigger language plpgsql set search_path = public, pg_temp as $$
begin
    -- Also cover administrative writes without an end-user claim. Such callers
    -- must retry ordinary PostgreSQL deadlock/serialization failures.
    if tg_op = 'DELETE' then
        perform pg_advisory_xact_lock(hashtextextended('mindmarket:portfolio-write:' || old.user_id::text, 0));
        return old;
    end if;
    perform pg_advisory_xact_lock(hashtextextended('mindmarket:portfolio-write:' || new.user_id::text, 0));
    -- Caller-supplied revision (including old versions) is never accepted.
    new.comparison_revision := pg_catalog.gen_random_uuid();
    return new;
end;
$$;
drop trigger if exists portfolios_comparison_revision on public.portfolios;
create trigger portfolios_comparison_revision before insert or update or delete on public.portfolios
for each row execute function public.bump_comparison_revision();

create table if not exists public.comparison_confirmations (
    plan_id uuid primary key references public.risk_plans(id) on delete cascade,
    user_id uuid not null references auth.users(id) on delete cascade,
    portfolio_id uuid not null references public.portfolios(id) on delete cascade,
    record text not null check (octet_length(record) <= 768000),
    signature text not null check (signature ~ '^[a-f0-9]{64}$')
);
create index if not exists comparison_confirmations_user_idx
    on public.comparison_confirmations(user_id, portfolio_id);
create index if not exists comparison_confirmations_portfolio_idx
    on public.comparison_confirmations(portfolio_id);
alter table public.comparison_confirmations enable row level security;
drop policy if exists comparison_confirmations_select on public.comparison_confirmations;
create policy comparison_confirmations_select on public.comparison_confirmations for select
to authenticated using (user_id = auth.uid());
drop policy if exists comparison_confirmations_insert on public.comparison_confirmations;
create policy comparison_confirmations_insert on public.comparison_confirmations for insert
to authenticated with check (
    user_id = auth.uid() and exists (
        select 1 from public.risk_plans p where p.id = plan_id
        and p.user_id = auth.uid() and p.portfolio_id = comparison_confirmations.portfolio_id
    )
);
-- Owners delete the parent plan, not just the evidence. No direct update/delete.
revoke all on public.comparison_confirmations from anon, authenticated;
grant select, insert on public.comparison_confirmations to authenticated;

create or replace function public.confirm_copilot_comparison(p_record text, p_signature text)
returns setof public.comparison_confirmations
language plpgsql security invoker set search_path = public, pg_temp as $$
declare
    proof jsonb;
    snap jsonb;
    result jsonb;
    owner_id uuid := auth.uid();
    book_id uuid;
    result_id uuid;
    active_id uuid;
    revision uuid;
    prior public.comparison_confirmations;
    capture_time timestamptz;
    confirm_time timestamptz;
begin
    if owner_id is null or octet_length(p_record) > 768000 then
        raise exception 'comparison_conflict' using errcode = 'P0001';
    end if;
    proof := p_record::jsonb;
    snap := (proof->'receipt'->>'record')::jsonb;
    result := snap->'result';
    book_id := (proof->>'portfolio_id')::uuid;
    result_id := (proof->>'plan_id')::uuid;
    if (proof->>'user_id')::uuid is distinct from owner_id
       or (snap->>'user_id')::uuid is distinct from owner_id
       or (snap->'account'->>'portfolio_id')::uuid is distinct from book_id
       or (result->>'portfolio_id')::uuid is distinct from book_id
       or (result->>'result_id')::uuid is distinct from result_id then
        raise exception 'comparison_conflict' using errcode = 'P0001';
    end if;
    -- Serialize only this owner's result retries. Unique PK is the final guard.
    perform pg_advisory_xact_lock(hashtextextended(owner_id::text || ':' || result_id::text, 0));
    select * into prior from public.comparison_confirmations c where c.plan_id = result_id;
    if found then
        if (prior.record::jsonb->'receipt'->>'record') is distinct from (proof->'receipt'->>'record')
           or prior.portfolio_id is distinct from book_id then
            raise exception 'comparison_conflict' using errcode = 'P0001';
        end if;
        return next prior;
        return;
    end if;
    perform pg_advisory_xact_lock(hashtextextended('mindmarket:portfolio-write:' || owner_id::text, 0));
    -- Lock the captured row before checking active selection and writing.
    -- Scope lock also covers inserts, deletes and active-portfolio switches.
    select p.comparison_revision into revision from public.portfolios p
        where p.id = book_id and p.user_id = owner_id for update;
    if not found or revision is distinct from (snap->>'portfolio_revision')::uuid then
        raise exception 'comparison_stale' using errcode = 'P0001';
    end if;
    select p.id into active_id from public.portfolios p where p.user_id = owner_id
        order by p.is_default desc, p.created_at desc limit 1;
    capture_time := (snap->>'captured_at')::timestamptz;
    confirm_time := (proof->>'confirmed_at')::timestamptz;
    if active_id is distinct from book_id or capture_time is null or confirm_time is null
       or capture_time > clock_timestamp() or capture_time < clock_timestamp() - interval '15 minutes'
       or confirm_time < capture_time or confirm_time > clock_timestamp()
       or confirm_time < clock_timestamp() - interval '60 seconds' then
        raise exception 'comparison_stale' using errcode = 'P0001';
    end if;
    if exists (select 1 from public.risk_plans p where p.id = result_id) then
        raise exception 'comparison_conflict' using errcode = 'P0001';
    end if;
    insert into public.risk_plans (
        id, user_id, portfolio_id, title, status, source, hypothesis,
        baseline, proposed_changes, expected_impact, data_confidence
    ) values (
        result_id, owner_id, book_id,
        'Test reducing ' || left(result->'assumptions'->>'ticker', 12), 'draft', 'copilot',
        'User-confirmed hypothetical comparison. No execution or holdings change.',
        -- Keep this methodology out of the legacy client-metric review path:
        -- its live score may use a different time window/account convention.
        jsonb_build_object('captured_comparison', result->'baseline'),
        result->'assumptions', jsonb_build_object('captured_comparison', result->'candidate'),
        jsonb_build_object('calculation_id', result_id, 'basis', 'historical captured inputs',
            'methodology_version', result->>'methodology_version', 'limitations', result->'limitations')
    );
    insert into public.comparison_confirmations(plan_id, user_id, portfolio_id, record, signature)
        values (result_id, owner_id, book_id, p_record, p_signature);
    return query select * from public.comparison_confirmations c where c.plan_id = result_id;
end;
$$;
revoke all on function public.confirm_copilot_comparison(text, text) from public, anon;
grant execute on function public.confirm_copilot_comparison(text, text) to authenticated;
