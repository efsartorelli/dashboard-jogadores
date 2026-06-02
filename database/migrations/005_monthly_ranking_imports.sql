-- Monthly ranking imports inside Curadoria.
-- Adds import batches, import line audit, normalized nickname fields and
-- links imported snapshots back to the XLSX import that created them.

BEGIN;

ALTER TABLE jogadores
    ADD COLUMN IF NOT EXISTS nickname_key TEXT,
    ADD COLUMN IF NOT EXISTS state_updated_at TIMESTAMPTZ;

ALTER TABLE jogador_nicknames
    ADD COLUMN IF NOT EXISTS nickname_key TEXT,
    ADD COLUMN IF NOT EXISTS ativo BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS motivo TEXT,
    ADD COLUMN IF NOT EXISTS importacao_id BIGINT;

CREATE TABLE IF NOT EXISTS importacoes_xlsx (
    id BIGSERIAL PRIMARY KEY,
    arquivo_nome TEXT NOT NULL,
    arquivo_hash TEXT NOT NULL,
    data_referencia DATE NOT NULL,
    status TEXT NOT NULL DEFAULT 'confirmado'
        CHECK (status IN ('rascunho', 'validado', 'confirmado', 'cancelado', 'desfeito', 'erro')),
    total_linhas INT NOT NULL DEFAULT 0 CHECK (total_linhas >= 0),
    linhas_validas INT NOT NULL DEFAULT 0 CHECK (linhas_validas >= 0),
    linhas_com_erro INT NOT NULL DEFAULT 0 CHECK (linhas_com_erro >= 0),
    linhas_alerta INT NOT NULL DEFAULT 0 CHECK (linhas_alerta >= 0),
    jogadores_existentes INT NOT NULL DEFAULT 0 CHECK (jogadores_existentes >= 0),
    jogadores_criados INT NOT NULL DEFAULT 0 CHECK (jogadores_criados >= 0),
    snapshots_criados INT NOT NULL DEFAULT 0 CHECK (snapshots_criados >= 0),
    linhas_ignoradas INT NOT NULL DEFAULT 0 CHECK (linhas_ignoradas >= 0),
    created_by UUID REFERENCES usuarios(id),
    confirmed_by UUID REFERENCES usuarios(id),
    confirmed_at TIMESTAMPTZ,
    undone_by UUID REFERENCES usuarios(id),
    undone_at TIMESTAMPTZ,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_importacoes_xlsx_data_status
    ON importacoes_xlsx (data_referencia DESC, status);

CREATE INDEX IF NOT EXISTS idx_importacoes_xlsx_created
    ON importacoes_xlsx (created_at DESC);

CREATE TABLE IF NOT EXISTS importacao_linhas (
    id BIGSERIAL PRIMARY KEY,
    importacao_id BIGINT NOT NULL REFERENCES importacoes_xlsx(id) ON DELETE CASCADE,
    linha_numero INT NOT NULL,
    nickname_original TEXT,
    nickname_normalizado TEXT,
    nickname_key TEXT,
    estado_original TEXT,
    estado_normalizado TEXT,
    capturas_original TEXT,
    capturas BIGINT,
    jogador_id BIGINT REFERENCES jogadores(id),
    jogador_nickname TEXT,
    ultimo_catches BIGINT,
    diferenca BIGINT,
    acao TEXT NOT NULL DEFAULT 'ignorar'
        CHECK (acao IN ('usar_existente', 'criar_jogador', 'possivel_duplicado', 'ignorar')),
    status_validacao TEXT NOT NULL DEFAULT 'erro'
        CHECK (status_validacao IN ('ok', 'alerta', 'erro')),
    status_linha TEXT NOT NULL,
    mensagem TEXT,
    erros JSONB NOT NULL DEFAULT '[]'::jsonb,
    avisos JSONB NOT NULL DEFAULT '[]'::jsonb,
    registro_periodico_id BIGINT REFERENCES registros_periodicos(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_importacao_linhas_importacao_status
    ON importacao_linhas (importacao_id, status_validacao);

CREATE INDEX IF NOT EXISTS idx_importacao_linhas_jogador
    ON importacao_linhas (jogador_id);

ALTER TABLE registros_periodicos
    ADD COLUMN IF NOT EXISTS importacao_id BIGINT REFERENCES importacoes_xlsx(id),
    ADD COLUMN IF NOT EXISTS importacao_linha_id BIGINT REFERENCES importacao_linhas(id);

CREATE INDEX IF NOT EXISTS idx_registros_importacao
    ON registros_periodicos (importacao_id);

CREATE INDEX IF NOT EXISTS idx_registros_importacao_linha
    ON registros_periodicos (importacao_linha_id);

CREATE INDEX IF NOT EXISTS idx_jogadores_nickname_key
    ON jogadores (nickname_key)
    WHERE nickname_key IS NOT NULL AND nickname_key <> '';

CREATE INDEX IF NOT EXISTS idx_jogador_nicknames_nickname_key
    ON jogador_nicknames (nickname_key)
    WHERE nickname_key IS NOT NULL AND nickname_key <> '';

CREATE OR REPLACE FUNCTION public.set_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS set_importacoes_xlsx_updated_at ON importacoes_xlsx;
CREATE TRIGGER set_importacoes_xlsx_updated_at
BEFORE UPDATE ON importacoes_xlsx
FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

ALTER TABLE importacoes_xlsx ENABLE ROW LEVEL SECURITY;
ALTER TABLE importacao_linhas ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS importacoes_xlsx_select_admin ON importacoes_xlsx;
CREATE POLICY importacoes_xlsx_select_admin ON importacoes_xlsx
FOR SELECT
TO authenticated
USING (public.is_admin());

DROP POLICY IF EXISTS importacoes_xlsx_admin_write ON importacoes_xlsx;
CREATE POLICY importacoes_xlsx_admin_write ON importacoes_xlsx
FOR ALL
TO authenticated
USING (public.is_admin())
WITH CHECK (public.is_admin());

DROP POLICY IF EXISTS importacao_linhas_select_admin ON importacao_linhas;
CREATE POLICY importacao_linhas_select_admin ON importacao_linhas
FOR SELECT
TO authenticated
USING (public.is_admin());

DROP POLICY IF EXISTS importacao_linhas_admin_write ON importacao_linhas;
CREATE POLICY importacao_linhas_admin_write ON importacao_linhas
FOR ALL
TO authenticated
USING (public.is_admin())
WITH CHECK (public.is_admin());

GRANT SELECT ON importacoes_xlsx, importacao_linhas TO authenticated;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO authenticated;

COMMIT;
