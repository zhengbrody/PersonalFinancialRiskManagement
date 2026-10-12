-- Requires 0016. User JWT / RLS only. No scheduled privileged worker.
BEGIN;
CREATE OR REPLACE FUNCTION public.transition_copilot_job(
  p_id uuid, p_old_signature text, p_record text, p_signature text, p_state text
) RETURNS SETOF public.copilot_runs
LANGUAGE plpgsql SECURITY INVOKER SET search_path = public AS $$
DECLARE
  old_row public.copilot_runs;
  old_doc jsonb;
  new_doc jsonb;
  old_lease timestamptz;
BEGIN
  SELECT * INTO old_row FROM public.copilot_runs
    WHERE id = p_id AND user_id = auth.uid() AND signature = p_old_signature FOR UPDATE;
  IF NOT FOUND THEN RETURN; END IF;
  old_doc := old_row.record::jsonb;
  new_doc := p_record::jsonb;
  IF old_doc->>'version' IS DISTINCT FROM '2' OR new_doc->>'version' IS DISTINCT FROM '2'
    OR new_doc->>'id' IS DISTINCT FROM old_row.id::text
    OR new_doc->>'user_id' IS DISTINCT FROM auth.uid()::text
    OR new_doc->>'portfolio_id' IS DISTINCT FROM old_row.portfolio_id::text
    OR new_doc->>'state' IS DISTINCT FROM p_state
    OR (new_doc->>'revision')::int IS DISTINCT FROM (old_doc->>'revision')::int + 1
    OR new_doc->'task' IS DISTINCT FROM old_doc->'task'
    OR new_doc->'snapshot' IS DISTINCT FROM old_doc->'snapshot'
    OR new_doc->'portfolio_revision' IS DISTINCT FROM old_doc->'portfolio_revision'
    OR new_doc->'expires_at' IS DISTINCT FROM old_doc->'expires_at'
    THEN RETURN; END IF;
  IF old_row.state NOT IN ('queued', 'running', 'interrupted') THEN RETURN; END IF;
  old_lease := (old_doc->>'lease_until')::timestamptz;
  IF old_row.state = 'running' AND p_state IN ('running', 'completed', 'failed')
    AND (old_lease IS NULL OR old_lease <= clock_timestamp()) THEN RETURN; END IF;
  IF p_state = 'queued' AND old_row.state = 'running'
    AND old_lease > clock_timestamp() THEN RETURN; END IF;
  IF p_state = 'running' AND old_row.state NOT IN ('queued', 'running') THEN RETURN; END IF;
  IF p_state = 'completed' AND old_row.state <> 'running' THEN RETURN; END IF;
  -- An attempt owns a fixed deadline. Heartbeats may renew its lease, not its lifetime.
  IF old_row.state = 'running' AND p_state IN ('running', 'completed', 'failed') THEN
    IF new_doc->'execution_deadline' IS DISTINCT FROM old_doc->'execution_deadline'
      OR COALESCE((old_doc->>'execution_deadline')::timestamptz, old_lease) <= clock_timestamp()
      OR (new_doc->>'attempts')::int IS DISTINCT FROM (old_doc->>'attempts')::int
      THEN RETURN; END IF;
  END IF;
  IF p_state = 'running' THEN
    IF (new_doc->>'lease_until') IS NULL
      OR (new_doc->>'lease_until')::timestamptz <= clock_timestamp()
      OR (new_doc->>'lease_until')::timestamptz > COALESCE((new_doc->>'execution_deadline')::timestamptz, old_lease)
      THEN RETURN; END IF;
    IF old_row.state = 'queued' AND (
      (new_doc->>'execution_deadline') IS NULL
      OR (new_doc->>'execution_deadline')::timestamptz > clock_timestamp() + interval '5 minutes'
      OR (new_doc->>'attempts')::int IS DISTINCT FROM (old_doc->>'attempts')::int + 1
      OR (new_doc->>'attempts')::int > 2
    ) THEN RETURN; END IF;
  END IF;
  RETURN QUERY UPDATE public.copilot_runs SET
    state = p_state, record = p_record, signature = p_signature
    WHERE id = p_id AND user_id = auth.uid() AND signature = p_old_signature RETURNING *;
END;
$$;

CREATE OR REPLACE FUNCTION public.cleanup_copilot_jobs(p_portfolio_id uuid)
RETURNS integer LANGUAGE plpgsql SECURITY INVOKER SET search_path=public AS $$
DECLARE removed integer;
BEGIN
  -- Canonical signed version-two records end with this marker. No JSON parsing of
  -- arbitrary client-written legacy text, and no deletion of version-one checks.
  WITH expired AS (
    SELECT id FROM public.copilot_runs
    WHERE user_id = auth.uid() AND portfolio_id = p_portfolio_id
      AND created_at < clock_timestamp() - interval '1 day'
      AND record LIKE '%"version":2}'
    ORDER BY created_at LIMIT 100 FOR UPDATE SKIP LOCKED
  ), deleted AS (
    DELETE FROM public.copilot_runs r USING expired e
    WHERE r.id = e.id AND r.user_id = auth.uid() RETURNING r.id
  ) SELECT count(*) INTO removed FROM deleted;
  RETURN removed;
END;
$$;
REVOKE ALL ON FUNCTION public.cleanup_copilot_jobs(uuid) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.cleanup_copilot_jobs(uuid) TO authenticated;
COMMIT;
