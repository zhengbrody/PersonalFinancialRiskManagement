-- supabase/migrations/0003_portfolio_capital.sql
--
-- Add explicit user capital fields.
--
-- Why:
--   avg_cost is position-level cost basis. It is not the user's actual
--   principal once there are deposits, withdrawals, realized gains/losses,
--   cash balances, or margin loans. SaaS users need explicit principal
--   tracking so total account P&L is computed from net equity.

alter table public.portfolios
    add column if not exists contributed_capital numeric(14, 2) not null default 0;

alter table public.portfolios
    add column if not exists cash_balance numeric(14, 2) not null default 0;

do $$
begin
    if not exists (
        select 1
        from pg_constraint
        where conname = 'portfolios_contributed_capital_nonnegative'
    ) then
        alter table public.portfolios
            add constraint portfolios_contributed_capital_nonnegative
            check (contributed_capital >= 0);
    end if;

    if not exists (
        select 1
        from pg_constraint
        where conname = 'portfolios_cash_balance_nonnegative'
    ) then
        alter table public.portfolios
            add constraint portfolios_cash_balance_nonnegative
            check (cash_balance >= 0);
    end if;
end $$;
