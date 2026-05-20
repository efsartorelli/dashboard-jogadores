-- SaaS layer for Supabase Auth, profiles, monthly limits, curation, payments and RLS.
-- Apply after 001_production_hardening.sql in a Supabase project.

BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

ALTER TABLE usuarios
    ADD COLUMN IF NOT EXISTS is_premium BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS nickname TEXT,
    ADD COLUMN IF NOT EXISTS pais TEXT,
    ADD COLUMN IF NOT EXISTS estado TEXT,
    ADD COLUMN IF NOT EXISTS cidade TEXT,
    ADD COLUMN IF NOT EXISTS premium_status TEXT NOT NULL DEFAULT 'free'
        CHECK (premium_status IN ('free', 'premium', 'past_due', 'cancelled')),
    ADD COLUMN IF NOT EXISTS premium_provider TEXT,
    ADD COLUMN IF NOT EXISTS premium_until TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS input_monthly_limit INT NOT NULL DEFAULT 5 CHECK (input_monthly_limit >= 0),
    ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS email_verified BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS session_revoked_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS terms_accepted_at TIMESTAMPTZ;

DO $$
BEGIN
    ALTER TABLE usuarios
        ADD CONSTRAINT usuarios_id_auth_users_fkey
        FOREIGN KEY (id) REFERENCES auth.users(id) ON DELETE CASCADE NOT VALID;
EXCEPTION
    WHEN duplicate_object OR undefined_table THEN NULL;
END $$;

CREATE OR REPLACE VIEW profiles
WITH (security_invoker = true) AS
SELECT
    id,
    email,
    nome,
    nickname,
    pais,
    estado,
    cidade,
    role,
    is_premium,
    premium_status,
    premium_provider,
    premium_until,
    input_monthly_limit,
    created_at,
    updated_at,
    last_login_at,
    last_seen_at,
    email_verified
FROM usuarios;

ALTER TABLE registros_periodicos
    ADD COLUMN IF NOT EXISTS submission_type TEXT NOT NULL DEFAULT 'manual'
        CHECK (submission_type IN ('manual', 'site', 'api', 'import', 'admin')),
    ADD COLUMN IF NOT EXISTS curadoria_observacao TEXT,
    ADD COLUMN IF NOT EXISTS reviewed_by UUID REFERENCES usuarios(id),
    ADD COLUMN IF NOT EXISTS reviewed_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS auto_score NUMERIC(6, 3),
    ADD COLUMN IF NOT EXISTS validation_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS ip_hash TEXT,
    ADD COLUMN IF NOT EXISTS user_agent_hash TEXT;

CREATE INDEX IF NOT EXISTS idx_registros_created_by_created_at
    ON registros_periodicos (created_by, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_registros_status_created_at
    ON registros_periodicos (status, created_at DESC);

CREATE TABLE IF NOT EXISTS security_events (
    id BIGSERIAL PRIMARY KEY,
    event_type TEXT NOT NULL,
    user_id UUID REFERENCES usuarios(id) ON DELETE SET NULL,
    subject_hash TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_security_events_user_type_created
    ON security_events (user_id, event_type, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_security_events_subject_type_created
    ON security_events (subject_hash, event_type, created_at DESC);

CREATE TABLE IF NOT EXISTS pagamentos (
    id BIGSERIAL PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    provider TEXT NOT NULL CHECK (provider IN ('manual', 'cacto', 'pagseguro', 'stripe')),
    plan_code TEXT NOT NULL DEFAULT 'premium_monthly',
    status TEXT NOT NULL DEFAULT 'checkout_pending'
        CHECK (status IN ('checkout_pending', 'pending', 'paid', 'failed', 'cancelled', 'refunded')),
    amount_cents INT NOT NULL CHECK (amount_cents >= 0),
    currency TEXT NOT NULL DEFAULT 'BRL',
    external_reference TEXT NOT NULL UNIQUE,
    provider_payment_id TEXT,
    checkout_url TEXT,
    raw_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    retry_count INT NOT NULL DEFAULT 0 CHECK (retry_count >= 0),
    last_error TEXT,
    paid_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_pagamentos_user_created
    ON pagamentos (user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_pagamentos_provider_payment
    ON pagamentos (provider, provider_payment_id);

CREATE TABLE IF NOT EXISTS payment_webhook_logs (
    id BIGSERIAL PRIMARY KEY,
    provider TEXT NOT NULL,
    event_id TEXT,
    signature_valid BOOLEAN NOT NULL DEFAULT FALSE,
    status TEXT NOT NULL DEFAULT 'received',
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    user_id UUID REFERENCES usuarios(id) ON DELETE SET NULL,
    payment_id BIGINT REFERENCES pagamentos(id) ON DELETE SET NULL,
    error TEXT,
    processed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_payment_webhook_provider_event
    ON payment_webhook_logs (provider, event_id)
    WHERE event_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_payment_webhook_created
    ON payment_webhook_logs (created_at DESC);

CREATE OR REPLACE FUNCTION public.set_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS set_usuarios_updated_at ON usuarios;
CREATE TRIGGER set_usuarios_updated_at
BEFORE UPDATE ON usuarios
FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

DROP TRIGGER IF EXISTS set_pagamentos_updated_at ON pagamentos;
CREATE TRIGGER set_pagamentos_updated_at
BEFORE UPDATE ON pagamentos
FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

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

CREATE OR REPLACE FUNCTION public.monthly_inputs_used(
    p_user_id UUID,
    p_month_start DATE DEFAULT date_trunc('month', now())::date
)
RETURNS INT
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
    SELECT COUNT(*)::int
    FROM registros_periodicos
    WHERE created_by = p_user_id
      AND fonte <> 'admin'
      AND created_at >= p_month_start
      AND created_at < (p_month_start + interval '1 month');
$$;

CREATE OR REPLACE FUNCTION public.can_create_submission(p_user_id UUID)
RETURNS BOOLEAN
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
    SELECT COALESCE(
        monthly_inputs_used(p_user_id) <
        CASE
            WHEN u.is_premium THEN GREATEST(u.input_monthly_limit, 50)
            ELSE u.input_monthly_limit
        END,
        FALSE
    )
    FROM usuarios u
    WHERE u.id = p_user_id;
$$;

CREATE OR REPLACE FUNCTION public.enforce_submission_limit()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
    IF NEW.created_by IS NULL OR COALESCE(NEW.fonte, '') = 'admin' THEN
        RETURN NEW;
    END IF;

    IF NOT public.can_create_submission(NEW.created_by) THEN
        RAISE EXCEPTION 'monthly input limit reached';
    END IF;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS enforce_submission_limit_before_insert ON registros_periodicos;
CREATE TRIGGER enforce_submission_limit_before_insert
BEFORE INSERT ON registros_periodicos
FOR EACH ROW EXECUTE FUNCTION public.enforce_submission_limit();

CREATE OR REPLACE FUNCTION public.protect_usuario_privileged_fields()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
    IF auth.uid() = OLD.id AND NOT public.is_admin() THEN
        NEW.role = OLD.role;
        NEW.is_premium = OLD.is_premium;
        NEW.premium_status = OLD.premium_status;
        NEW.premium_provider = OLD.premium_provider;
        NEW.premium_until = OLD.premium_until;
        NEW.input_monthly_limit = OLD.input_monthly_limit;
        NEW.email = OLD.email;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS protect_usuario_privileged_fields_before_update ON usuarios;
CREATE TRIGGER protect_usuario_privileged_fields_before_update
BEFORE UPDATE ON usuarios
FOR EACH ROW EXECUTE FUNCTION public.protect_usuario_privileged_fields();

CREATE OR REPLACE FUNCTION public.handle_new_auth_user()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, auth
AS $$
BEGIN
    INSERT INTO public.usuarios (
        id, email, nome, nickname, pais, estado, cidade,
        email_verified, last_login_at, last_seen_at
    )
    VALUES (
        NEW.id,
        NEW.email,
        COALESCE(NEW.raw_user_meta_data ->> 'nome', NEW.raw_user_meta_data ->> 'full_name'),
        NEW.raw_user_meta_data ->> 'nickname',
        NEW.raw_user_meta_data ->> 'pais',
        NEW.raw_user_meta_data ->> 'estado',
        NEW.raw_user_meta_data ->> 'cidade',
        NEW.email_confirmed_at IS NOT NULL,
        now(),
        now()
    )
    ON CONFLICT (id) DO UPDATE SET
        email = EXCLUDED.email,
        nickname = COALESCE(NULLIF(usuarios.nickname, ''), EXCLUDED.nickname),
        pais = COALESCE(NULLIF(usuarios.pais, ''), EXCLUDED.pais),
        estado = COALESCE(NULLIF(usuarios.estado, ''), EXCLUDED.estado),
        cidade = COALESCE(NULLIF(usuarios.cidade, ''), EXCLUDED.cidade),
        email_verified = usuarios.email_verified OR EXCLUDED.email_verified,
        last_seen_at = now(),
        updated_at = now();
    RETURN NEW;
END;
$$;

DO $$
BEGIN
    DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
    CREATE TRIGGER on_auth_user_created
    AFTER INSERT ON auth.users
    FOR EACH ROW EXECUTE FUNCTION public.handle_new_auth_user();
EXCEPTION
    WHEN undefined_table THEN NULL;
END $$;

ALTER TABLE usuarios ENABLE ROW LEVEL SECURITY;
ALTER TABLE jogadores ENABLE ROW LEVEL SECURITY;
ALTER TABLE jogador_nicknames ENABLE ROW LEVEL SECURITY;
ALTER TABLE registros_periodicos ENABLE ROW LEVEL SECURITY;
ALTER TABLE auditoria_registros ENABLE ROW LEVEL SECURITY;
ALTER TABLE security_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE pagamentos ENABLE ROW LEVEL SECURITY;
ALTER TABLE payment_webhook_logs ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS usuarios_select_own_or_admin ON usuarios;
CREATE POLICY usuarios_select_own_or_admin ON usuarios
FOR SELECT
USING (auth.uid() = id OR public.is_admin());

DROP POLICY IF EXISTS usuarios_update_own_profile ON usuarios;
CREATE POLICY usuarios_update_own_profile ON usuarios
FOR UPDATE
USING (auth.uid() = id OR public.is_admin())
WITH CHECK (auth.uid() = id OR public.is_admin());

DROP POLICY IF EXISTS jogadores_select_authenticated ON jogadores;
CREATE POLICY jogadores_select_authenticated ON jogadores
FOR SELECT
TO authenticated
USING (mostrar = TRUE AND ativo = TRUE OR public.is_admin());

DROP POLICY IF EXISTS jogadores_admin_write ON jogadores;
CREATE POLICY jogadores_admin_write ON jogadores
FOR ALL
TO authenticated
USING (public.is_admin())
WITH CHECK (public.is_admin());

DROP POLICY IF EXISTS jogador_nicknames_select_authenticated ON jogador_nicknames;
CREATE POLICY jogador_nicknames_select_authenticated ON jogador_nicknames
FOR SELECT
TO authenticated
USING (
    EXISTS (
        SELECT 1
        FROM jogadores j
        WHERE j.id = jogador_nicknames.jogador_id
          AND (j.mostrar = TRUE AND j.ativo = TRUE OR public.is_admin())
    )
);

DROP POLICY IF EXISTS jogador_nicknames_admin_write ON jogador_nicknames;
CREATE POLICY jogador_nicknames_admin_write ON jogador_nicknames
FOR ALL
TO authenticated
USING (public.is_admin())
WITH CHECK (public.is_admin());

DROP POLICY IF EXISTS registros_select_global_or_own ON registros_periodicos;
CREATE POLICY registros_select_global_or_own ON registros_periodicos
FOR SELECT
TO authenticated
USING (
    status = 'validado'
    OR created_by = auth.uid()
    OR public.is_admin()
);

DROP POLICY IF EXISTS registros_insert_own_limited ON registros_periodicos;
CREATE POLICY registros_insert_own_limited ON registros_periodicos
FOR INSERT
TO authenticated
WITH CHECK (
    created_by = auth.uid()
    AND status = 'pendente'
    AND public.can_create_submission(auth.uid())
);

DROP POLICY IF EXISTS registros_admin_write ON registros_periodicos;
CREATE POLICY registros_admin_write ON registros_periodicos
FOR UPDATE
TO authenticated
USING (public.is_admin())
WITH CHECK (public.is_admin());

DROP POLICY IF EXISTS auditoria_select_admin ON auditoria_registros;
CREATE POLICY auditoria_select_admin ON auditoria_registros
FOR SELECT
TO authenticated
USING (public.is_admin());

DROP POLICY IF EXISTS security_events_insert_own ON security_events;
CREATE POLICY security_events_insert_own ON security_events
FOR INSERT
TO authenticated
WITH CHECK (user_id = auth.uid());

DROP POLICY IF EXISTS security_events_select_admin ON security_events;
CREATE POLICY security_events_select_admin ON security_events
FOR SELECT
TO authenticated
USING (public.is_admin());

DROP POLICY IF EXISTS pagamentos_select_own_or_admin ON pagamentos;
CREATE POLICY pagamentos_select_own_or_admin ON pagamentos
FOR SELECT
TO authenticated
USING (user_id = auth.uid() OR public.is_admin());

DROP POLICY IF EXISTS pagamentos_insert_own ON pagamentos;
CREATE POLICY pagamentos_insert_own ON pagamentos
FOR INSERT
TO authenticated
WITH CHECK (user_id = auth.uid());

DROP POLICY IF EXISTS pagamentos_admin_update ON pagamentos;
CREATE POLICY pagamentos_admin_update ON pagamentos
FOR UPDATE
TO authenticated
USING (public.is_admin())
WITH CHECK (public.is_admin());

DROP POLICY IF EXISTS payment_webhook_logs_select_admin ON payment_webhook_logs;
CREATE POLICY payment_webhook_logs_select_admin ON payment_webhook_logs
FOR SELECT
TO authenticated
USING (public.is_admin());

GRANT USAGE ON SCHEMA public TO authenticated;
GRANT SELECT ON profiles TO authenticated;
GRANT SELECT ON jogadores, jogador_nicknames, registros_periodicos TO authenticated;
GRANT SELECT, UPDATE ON usuarios TO authenticated;
GRANT SELECT, INSERT ON pagamentos TO authenticated;
GRANT INSERT ON security_events TO authenticated;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO authenticated;

COMMIT;
