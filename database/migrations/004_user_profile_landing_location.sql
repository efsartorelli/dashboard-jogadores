-- User profile fields required by the public landing/signup and first submission flow.
-- Apply after 003_admin_only_curation.sql on existing databases.

BEGIN;

ALTER TABLE usuarios
    ADD COLUMN IF NOT EXISTS nickname TEXT,
    ADD COLUMN IF NOT EXISTS pais TEXT,
    ADD COLUMN IF NOT EXISTS estado TEXT,
    ADD COLUMN IF NOT EXISTS cidade TEXT;

CREATE INDEX IF NOT EXISTS idx_usuarios_nickname_lower
    ON usuarios (lower(nickname))
    WHERE nickname IS NOT NULL AND nickname <> '';

CREATE INDEX IF NOT EXISTS idx_usuarios_localidade
    ON usuarios (pais, estado, cidade)
    WHERE pais IS NOT NULL AND estado IS NOT NULL AND cidade IS NOT NULL;

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

COMMIT;
