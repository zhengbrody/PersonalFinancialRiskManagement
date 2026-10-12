-- Requires 0015. Reuses RiskPlan and immutable confirmations; no new table.
BEGIN;
create or replace function public.confirm_copilot_funding_plan(p_record text, p_signature text)
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
    if snap->>'kind' is distinct from 'funding_scenarios'
       or result->>'methodology_version' is distinct from 'funding-scenarios-v1' then
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
        'Funding scenario: ' || left(result->>'sale_ticker', 16), 'draft', 'copilot',
        'User-confirmed hypothetical comparison. No execution or holdings change.',
        -- Keep this methodology out of the legacy client-metric review path:
        -- its live score may use a different time window/account convention.
        jsonb_build_object('captured_funding', result),
        result->'assumptions', jsonb_build_object('captured_funding', result),
        jsonb_build_object('kind', 'funding_scenarios', 'calculation_id', result_id, 'basis', 'historical captured inputs',
            'methodology_version', result->>'methodology_version', 'limitations', result->'limitations')
    );
    insert into public.comparison_confirmations(plan_id, user_id, portfolio_id, record, signature)
        values (result_id, owner_id, book_id, p_record, p_signature);
    return query select * from public.comparison_confirmations c where c.plan_id = result_id;
end;
$$;
revoke all on function public.confirm_copilot_funding_plan(text, text) from public, anon;
grant execute on function public.confirm_copilot_funding_plan(text, text) to authenticated;

COMMIT;
