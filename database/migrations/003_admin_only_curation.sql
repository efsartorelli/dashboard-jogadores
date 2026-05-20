-- Restrict administrative curation policies to role = 'admin'.
-- Apply after 002_saas_auth_premium_payments.sql on existing databases.

BEGIN;

CREATE OR REPLACE FUNCTION public.is_admin()
RETURNS BOOLEAN
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
    SELECT EXISTS (
        SELECT 1
        FROM usuarios
        WHERE id = auth.uid()
          AND role = 'admin'
    );
$$;

COMMIT;
