-- Scope risk-memory lookups and the daily de-duplication window to the active
-- portfolio.  The column already exists (0004); this is an additive index only.
-- Legacy NULL rows intentionally remain readable for audit/backup purposes but
-- application queries no longer compare them to an identified portfolio.

create index if not exists portfolio_snapshots_user_portfolio_created_idx
    on public.portfolio_snapshots (user_id, portfolio_id, created_at desc)
    where portfolio_id is not null;
