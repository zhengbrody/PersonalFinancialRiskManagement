-- Durable foreground checks. Apply only after review; feature defaults OFF.
-- The authenticated user's JWT is used for access. Independent server HMAC
-- signatures authenticate the record TEXT; RLS alone does not make a client's
-- own writes trustworthy evidence. Never put tokens or HMAC keys in this table.
CREATE TABLE public.copilot_runs (
    id uuid PRIMARY KEY,
    user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    portfolio_id uuid NOT NULL REFERENCES public.portfolios(id) ON DELETE CASCADE,
    state text NOT NULL CHECK (state IN ('running', 'completed', 'failed', 'cancelled', 'interrupted')),
    created_at timestamptz NOT NULL DEFAULT now(),
    record text NOT NULL CHECK (octet_length(record) <= 512000),
    signature text NOT NULL CHECK (signature ~ '^[a-f0-9]{64}$')
);
CREATE INDEX copilot_runs_owner_portfolio ON public.copilot_runs(user_id, portfolio_id, created_at DESC);
ALTER TABLE public.copilot_runs ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.copilot_runs FROM anon;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.copilot_runs TO authenticated;

CREATE POLICY copilot_runs_select ON public.copilot_runs FOR SELECT TO authenticated
USING (user_id = (SELECT auth.uid()));
CREATE POLICY copilot_runs_insert ON public.copilot_runs FOR INSERT TO authenticated
WITH CHECK (user_id = (SELECT auth.uid()) AND EXISTS (
    SELECT 1 FROM public.portfolios p WHERE p.id = portfolio_id AND p.user_id = (SELECT auth.uid())
));
CREATE POLICY copilot_runs_update ON public.copilot_runs FOR UPDATE TO authenticated
USING (user_id = (SELECT auth.uid()))
WITH CHECK (user_id = (SELECT auth.uid()) AND EXISTS (
    SELECT 1 FROM public.portfolios p WHERE p.id = portfolio_id AND p.user_id = (SELECT auth.uid())
));
CREATE POLICY copilot_runs_delete ON public.copilot_runs FOR DELETE TO authenticated
USING (user_id = (SELECT auth.uid()));
