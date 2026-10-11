-- Requires 0014, 0016, 0017. Re-runnable: CREATE OR REPLACE + DROP TRIGGER IF EXISTS.
-- Version-two background job records gain three DATABASE-clock guarantees that
-- application code alone cannot provide:
--   1. A running job is interrupted only after its lease has expired by the
--      database clock (a reader with a fast application clock cannot kill it).
--   2. A stored record can never move backwards: revision strictly increases and
--      execution attempts never decrease, whether written by the RPC or by a
--      direct UPDATE (RLS grants the owner UPDATE for version-one runs). A newly
--      inserted record must be a fresh initial reservation, so an old validly
--      signed record cannot be replayed after a DELETE to reset its attempts.
--   3. One owner holds at most one active (queued, or running with a live lease)
--      background job, enforced under a per-owner transaction lock.
-- Version-one foreground runs (no "version":2) are untouched.
BEGIN;

CREATE OR REPLACE FUNCTION public.copilot_job_document(p_record text)
RETURNS jsonb LANGUAGE plpgsql IMMUTABLE SET search_path = public AS $$
BEGIN
  RETURN p_record::jsonb;
EXCEPTION WHEN others THEN
  RETURN NULL;
END;
$$;
REVOKE ALL ON FUNCTION public.copilot_job_document(text) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.copilot_job_document(text) TO authenticated;

CREATE OR REPLACE FUNCTION public.enforce_copilot_job_limit(p_user uuid, p_id uuid)
RETURNS void LANGUAGE plpgsql SECURITY INVOKER SET search_path = public AS $$
DECLARE
  active integer;
BEGIN
  -- Serialize this owner's activations so two concurrent starts cannot both
  -- observe zero active jobs. Other owners are never blocked.
  PERFORM pg_advisory_xact_lock(hashtextextended('mindmarket:copilot-job:' || p_user::text, 0));
  SELECT count(*) INTO active FROM public.copilot_runs r
    WHERE r.user_id = p_user AND r.id <> p_id
      AND r.state IN ('queued', 'running')
      AND public.copilot_job_document(r.record)->>'version' = '2'
      AND (public.copilot_job_document(r.record)->>'expires_at')::timestamptz > clock_timestamp()
      AND (r.state = 'queued'
        OR (public.copilot_job_document(r.record)->>'lease_until')::timestamptz > clock_timestamp());
  IF active >= 1 THEN
    RAISE EXCEPTION 'copilot_job_limit' USING errcode = 'P0001';
  END IF;
END;
$$;
REVOKE ALL ON FUNCTION public.enforce_copilot_job_limit(uuid, uuid) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.enforce_copilot_job_limit(uuid, uuid) TO authenticated;

CREATE OR REPLACE FUNCTION public.guard_copilot_job_record()
RETURNS trigger LANGUAGE plpgsql SECURITY INVOKER SET search_path = public AS $$
DECLARE
  new_doc jsonb := public.copilot_job_document(NEW.record);
  old_doc jsonb;
BEGIN
  IF TG_OP = 'INSERT' THEN
    IF new_doc IS NULL OR jsonb_typeof(new_doc) <> 'object' OR new_doc->>'version' IS DISTINCT FROM '2' THEN
      RETURN NEW;
    END IF;
    IF NEW.state <> 'queued' OR new_doc->>'state' IS DISTINCT FROM 'queued'
      OR (new_doc->>'revision')::int IS DISTINCT FROM 0
      OR (new_doc->>'attempts')::int IS DISTINCT FROM 0
      OR (new_doc->>'created_at') IS NULL
      OR (new_doc->>'created_at')::timestamptz < clock_timestamp() - interval '5 minutes'
      OR (new_doc->>'created_at')::timestamptz > clock_timestamp() + interval '1 minute' THEN
      RAISE EXCEPTION 'copilot_job_replay' USING errcode = 'P0001';
    END IF;
    PERFORM public.enforce_copilot_job_limit(NEW.user_id, NEW.id);
    RETURN NEW;
  END IF;

  -- UPDATE
  IF NEW.record IS NOT DISTINCT FROM OLD.record THEN
    RETURN NEW;
  END IF;
  old_doc := public.copilot_job_document(OLD.record);
  IF (old_doc IS NULL OR old_doc->>'version' IS DISTINCT FROM '2')
    AND (new_doc IS NULL OR new_doc->>'version' IS DISTINCT FROM '2') THEN
    RETURN NEW;
  END IF;
  IF old_doc->>'version' IS DISTINCT FROM '2' OR new_doc->>'version' IS DISTINCT FROM '2'
    OR (new_doc->>'revision')::int IS NULL
    OR (new_doc->>'revision')::int <= (old_doc->>'revision')::int
    OR COALESCE((new_doc->>'attempts')::int, 0) < COALESCE((old_doc->>'attempts')::int, 0) THEN
    RAISE EXCEPTION 'copilot_job_rollback' USING errcode = 'P0001';
  END IF;
  -- Re-queueing an interrupted job makes it active again: same per-owner limit.
  IF NEW.state = 'queued' AND OLD.state <> 'queued' THEN
    PERFORM public.enforce_copilot_job_limit(NEW.user_id, NEW.id);
  END IF;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS copilot_job_integrity ON public.copilot_runs;
CREATE TRIGGER copilot_job_integrity
  BEFORE INSERT OR UPDATE ON public.copilot_runs
  FOR EACH ROW EXECUTE FUNCTION public.guard_copilot_job_record();

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
  -- New in 0020: only the DATABASE clock may declare a live lease dead.
  IF p_state = 'interrupted' AND old_row.state = 'running'
    AND old_lease > clock_timestamp() THEN RETURN; END IF;
  IF p_state = 'running' AND old_row.state NOT IN ('queued', 'running') THEN RETURN; END IF;
  IF p_state = 'completed' AND old_row.state <> 'running' THEN RETURN; END IF;
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
REVOKE ALL ON FUNCTION public.transition_copilot_job(uuid,text,text,text,text) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.transition_copilot_job(uuid,text,text,text,text) TO authenticated;
COMMIT;
