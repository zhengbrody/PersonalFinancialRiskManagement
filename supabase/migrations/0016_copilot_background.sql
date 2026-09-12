-- Additive to 0014. No tokens, service-role access or parallel job table.
BEGIN;
ALTER TABLE public.copilot_runs DROP CONSTRAINT copilot_runs_state_check;
ALTER TABLE public.copilot_runs ADD CONSTRAINT copilot_runs_state_check
  CHECK (state IN ('queued', 'running', 'completed', 'failed', 'cancelled', 'interrupted'));

-- The old HMAC is the CAS version. Server clock fences completion and progress;
-- application clocks alone cannot authorize a late worker after a DB delay.
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
  RETURN QUERY UPDATE public.copilot_runs SET
    state = p_state, record = p_record, signature = p_signature
    WHERE id = p_id AND user_id = auth.uid() AND signature = p_old_signature RETURNING *;
END;
$$;
REVOKE ALL ON FUNCTION public.transition_copilot_job(uuid,text,text,text,text) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.transition_copilot_job(uuid,text,text,text,text) TO authenticated;
COMMIT;
