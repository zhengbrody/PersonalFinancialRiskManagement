-- supabase/migrations/0005_normalize_asset_type.sql
--
-- Data cleanup: normalize legacy holdings.asset_type values.
--
-- `portfolios.holdings` is JSONB: { "<TICKER>": { shares, avg_cost,
-- asset_type, ... }, ... }. Some rows were stored with asset_type values
-- outside the domain model's allowed set (public_security / cash / crypto /
-- real_estate) — notably the legacy label 'equity' — which made the scoring
-- endpoints raise a Pydantic ValidationError → 500 (the app now normalizes
-- defensively at the boundary, but this fixes the data at rest too).
--
-- Idempotent: re-running matches nothing. Only the nested `asset_type` field
-- of object-valued holdings is rewritten; every other field and untouched
-- ticker is preserved exactly.

update public.portfolios p
set holdings = (
    select jsonb_object_agg(
        e.key,
        case
            when jsonb_typeof(e.value) = 'object'
                 and (e.value ->> 'asset_type') is not null
                 and (e.value ->> 'asset_type') not in
                     ('public_security', 'cash', 'crypto', 'real_estate')
            then jsonb_set(e.value, '{asset_type}', '"public_security"'::jsonb)
            else e.value
        end
    )
    from jsonb_each(p.holdings) e
)
where exists (
    select 1
    from jsonb_each(p.holdings) e
    where jsonb_typeof(e.value) = 'object'
      and (e.value ->> 'asset_type') is not null
      and (e.value ->> 'asset_type') not in
          ('public_security', 'cash', 'crypto', 'real_estate')
);
