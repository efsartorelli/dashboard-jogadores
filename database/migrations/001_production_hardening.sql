-- Production hardening migration.
-- Apply this to existing Supabase/PostgreSQL databases before deploying the
-- app version that allows rejected submissions to remain in history.

BEGIN;

ALTER TABLE registros_periodicos
    DROP CONSTRAINT IF EXISTS registros_periodicos_jogador_id_periodo_tipo_data_referencia_key;

CREATE INDEX IF NOT EXISTS idx_jogadores_nickname_lower
    ON jogadores (lower(nickname_atual));

CREATE INDEX IF NOT EXISTS idx_jogador_nicknames_nickname_lower
    ON jogador_nicknames (lower(nickname));

CREATE INDEX IF NOT EXISTS idx_registros_dashboard_validado
    ON registros_periodicos (periodo_tipo, status, data_referencia, jogador_id)
    WHERE status = 'validado';

CREATE UNIQUE INDEX IF NOT EXISTS uq_registros_ativos_jogador_periodo_data
    ON registros_periodicos (jogador_id, periodo_tipo, data_referencia)
    WHERE status IN ('pendente', 'validado');

COMMIT;
