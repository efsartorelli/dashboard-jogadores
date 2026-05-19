-- Production schema proposal for Ranking BR.
-- PostgreSQL dialect. Keep calculations materialized so the dashboard stays fast
-- when player submissions grow from hundreds to tens of thousands.

CREATE TABLE IF NOT EXISTS usuarios (
    id UUID PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    nome TEXT,
    role TEXT NOT NULL DEFAULT 'jogador' CHECK (role IN ('admin', 'moderador', 'jogador')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_login_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS jogadores (
    id BIGSERIAL PRIMARY KEY,
    nickname_atual TEXT NOT NULL,
    country TEXT,
    state TEXT,
    city TEXT,
    mostrar BOOLEAN NOT NULL DEFAULT TRUE,
    ativo BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_jogadores_nickname_atual ON jogadores (nickname_atual);
CREATE INDEX IF NOT EXISTS idx_jogadores_state ON jogadores (state);
CREATE INDEX IF NOT EXISTS idx_jogadores_dashboard ON jogadores (mostrar, ativo);

CREATE TABLE IF NOT EXISTS jogador_nicknames (
    id BIGSERIAL PRIMARY KEY,
    jogador_id BIGINT NOT NULL REFERENCES jogadores(id),
    nickname TEXT NOT NULL,
    inicio_em DATE,
    fim_em DATE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_jogador_nicknames_nickname ON jogador_nicknames (nickname);
CREATE INDEX IF NOT EXISTS idx_jogador_nicknames_jogador_periodo ON jogador_nicknames (jogador_id, inicio_em);

CREATE TABLE IF NOT EXISTS registros_periodicos (
    id BIGSERIAL PRIMARY KEY,
    jogador_id BIGINT NOT NULL REFERENCES jogadores(id),
    periodo_tipo TEXT NOT NULL CHECK (periodo_tipo IN ('mensal', 'semanal')),
    data_referencia DATE NOT NULL,
    catches BIGINT NOT NULL CHECK (catches >= 0),
    fonte TEXT NOT NULL DEFAULT 'site',
    observacao TEXT,
    contato_envio TEXT,
    status TEXT NOT NULL DEFAULT 'pendente' CHECK (status IN ('pendente', 'validado', 'rejeitado')),
    created_by UUID REFERENCES usuarios(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE registros_periodicos
    DROP CONSTRAINT IF EXISTS registros_periodicos_jogador_id_periodo_tipo_data_referencia_key;

CREATE INDEX IF NOT EXISTS idx_registros_jogador_data ON registros_periodicos (jogador_id, data_referencia);
CREATE INDEX IF NOT EXISTS idx_registros_periodo_data ON registros_periodicos (periodo_tipo, data_referencia);
CREATE INDEX IF NOT EXISTS idx_registros_status ON registros_periodicos (status);
CREATE INDEX IF NOT EXISTS idx_jogadores_nickname_lower ON jogadores (lower(nickname_atual));
CREATE INDEX IF NOT EXISTS idx_jogador_nicknames_nickname_lower ON jogador_nicknames (lower(nickname));
CREATE INDEX IF NOT EXISTS idx_registros_dashboard_validado
    ON registros_periodicos (periodo_tipo, status, data_referencia, jogador_id)
    WHERE status = 'validado';
CREATE UNIQUE INDEX IF NOT EXISTS uq_registros_ativos_jogador_periodo_data
    ON registros_periodicos (jogador_id, periodo_tipo, data_referencia)
    WHERE status IN ('pendente', 'validado');

CREATE TABLE IF NOT EXISTS rankings_snapshot (
    id BIGSERIAL PRIMARY KEY,
    ranking_tipo TEXT NOT NULL CHECK (ranking_tipo IN ('geral', 'media_diaria', 'estado', 'categoria', 'distribuicao')),
    periodo_tipo TEXT CHECK (periodo_tipo IN ('mensal', 'semanal')),
    data_base DATE NOT NULL,
    parametros JSONB NOT NULL DEFAULT '{}'::jsonb,
    status TEXT NOT NULL DEFAULT 'pronto' CHECK (status IN ('processando', 'pronto', 'erro')),
    data_processamento TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_rankings_snapshot_lookup ON rankings_snapshot (ranking_tipo, data_base, status);

CREATE TABLE IF NOT EXISTS ranking_itens (
    id BIGSERIAL PRIMARY KEY,
    snapshot_id BIGINT NOT NULL REFERENCES rankings_snapshot(id) ON DELETE CASCADE,
    jogador_id BIGINT REFERENCES jogadores(id),
    posicao INT NOT NULL,
    valor BIGINT NOT NULL,
    metricas JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_ranking_itens_snapshot_posicao ON ranking_itens (snapshot_id, posicao);
CREATE INDEX IF NOT EXISTS idx_ranking_itens_jogador ON ranking_itens (jogador_id);

CREATE TABLE IF NOT EXISTS categorias (
    id BIGSERIAL PRIMARY KEY,
    nome TEXT NOT NULL,
    tipo TEXT NOT NULL DEFAULT 'catches',
    min_catches BIGINT NOT NULL,
    max_catches BIGINT,
    ativo BOOLEAN NOT NULL DEFAULT TRUE,
    CHECK (max_catches IS NULL OR max_catches > min_catches)
);

CREATE TABLE IF NOT EXISTS historico_processamentos (
    id BIGSERIAL PRIMARY KEY,
    job_tipo TEXT NOT NULL,
    iniciado_em TIMESTAMPTZ NOT NULL DEFAULT now(),
    finalizado_em TIMESTAMPTZ,
    status TEXT NOT NULL CHECK (status IN ('processando', 'sucesso', 'erro')),
    linhas_processadas INT NOT NULL DEFAULT 0,
    erro TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS auditoria_registros (
    id BIGSERIAL PRIMARY KEY,
    registro_id BIGINT REFERENCES registros_periodicos(id),
    acao TEXT NOT NULL CHECK (acao IN ('criado', 'alterado', 'aprovado', 'rejeitado')),
    antes JSONB,
    depois JSONB,
    usuario_id UUID REFERENCES usuarios(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
