-- Monthly XLSX imports are administrative curation actions and must not count
-- against the monthly self-submission limit.

BEGIN;

CREATE OR REPLACE FUNCTION public.enforce_submission_limit()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
    IF NEW.created_by IS NULL
        OR COALESCE(NEW.fonte, '') IN ('admin', 'xlsx_curadoria')
        OR COALESCE(NEW.submission_type, '') = 'import'
    THEN
        RETURN NEW;
    END IF;

    IF NOT public.can_create_submission(NEW.created_by) THEN
        RAISE EXCEPTION 'monthly input limit reached';
    END IF;

    RETURN NEW;
END;
$$;

COMMIT;
