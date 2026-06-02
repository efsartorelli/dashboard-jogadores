from __future__ import annotations

from datetime import date
from typing import Any

from src.database.connection import get_connection
from src.database.repositories import buscar_usuario_por_id


VALID_REPROCESS_STATUSES = ("validado",)


def _user_can_reprocess(conn, user_id: str | None) -> bool:
    if not user_id:
        return False
    profile = buscar_usuario_por_id(conn, user_id)
    role = str((profile or {}).get("role") or "").lower()
    return role in {"admin", "moderador"}


def reprocess_current_ranking(
    admin_user_id: str | None,
    periodo_tipo: str = "mensal",
    conn=None,
) -> dict[str, Any]:
    """Rebuild the current general ranking from validated periodic records.

    The canonical link is registros_periodicos.jogador_id. Nicknames are used
    only as display metadata and deterministic tie breakers.
    """
    periodo_tipo = str(periodo_tipo or "mensal").strip().lower()
    if periodo_tipo not in {"mensal", "semanal"}:
        return {"success": False, "errors": ["Periodo invalido para reprocessamento."]}

    owns_connection = conn is None
    context = get_connection() if owns_connection else None
    if owns_connection:
        conn = context.__enter__()

    try:
        if not _user_can_reprocess(conn, admin_user_id):
            return {"success": False, "errors": ["Acesso restrito a administradores e moderadores."]}

        with conn.cursor() as cur:
            cur.execute(
                """
                WITH latest_records AS (
                    SELECT DISTINCT ON (r.jogador_id)
                        r.id AS registro_id,
                        r.jogador_id,
                        r.data_referencia,
                        r.catches,
                        r.fonte,
                        j.nickname_atual,
                        j.state
                    FROM registros_periodicos r
                    JOIN jogadores j ON j.id = r.jogador_id
                    WHERE r.periodo_tipo = %s
                      AND r.status = ANY(%s)
                      AND j.ativo = TRUE
                      AND j.mostrar = TRUE
                    ORDER BY r.jogador_id, r.data_referencia DESC, r.id DESC
                )
                SELECT
                    COUNT(*) AS total_jogadores,
                    MAX(data_referencia) AS data_base,
                    MIN(data_referencia) AS primeira_data,
                    MAX(catches) AS maior_valor
                FROM latest_records
                """,
                (periodo_tipo, list(VALID_REPROCESS_STATUSES)),
            )
            summary = cur.fetchone() or {}
            total_jogadores = int(summary.get("total_jogadores") or 0)
            if total_jogadores <= 0:
                if owns_connection:
                    conn.rollback()
                return {
                    "success": False,
                    "errors": ["Nenhum registro validado encontrado para gerar o ranking."],
                }

            data_base = summary.get("data_base") or date.today()
            cur.execute(
                """
                INSERT INTO rankings_snapshot (
                    ranking_tipo,
                    periodo_tipo,
                    data_base,
                    parametros,
                    status
                )
                VALUES (
                    'geral',
                    %s,
                    %s,
                    jsonb_build_object(
                        'origem', 'curadoria_reprocessamento',
                        'status_registros', %s::jsonb,
                        'admin_user_id', %s
                    ),
                    'processando'
                )
                RETURNING id
                """,
                (periodo_tipo, data_base, '["validado"]', admin_user_id),
            )
            snapshot_id = int(cur.fetchone()["id"])

            cur.execute(
                """
                WITH latest_records AS (
                    SELECT DISTINCT ON (r.jogador_id)
                        r.id AS registro_id,
                        r.jogador_id,
                        r.data_referencia,
                        r.catches,
                        r.fonte,
                        j.nickname_atual,
                        j.state
                    FROM registros_periodicos r
                    JOIN jogadores j ON j.id = r.jogador_id
                    WHERE r.periodo_tipo = %s
                      AND r.status = ANY(%s)
                      AND j.ativo = TRUE
                      AND j.mostrar = TRUE
                    ORDER BY r.jogador_id, r.data_referencia DESC, r.id DESC
                ),
                ranked AS (
                    SELECT
                        jogador_id,
                        registro_id,
                        data_referencia,
                        catches,
                        fonte,
                        nickname_atual,
                        state,
                        ROW_NUMBER() OVER (
                            ORDER BY catches DESC, nickname_atual ASC, jogador_id ASC
                        ) AS posicao
                    FROM latest_records
                )
                INSERT INTO ranking_itens (
                    snapshot_id,
                    jogador_id,
                    posicao,
                    valor,
                    metricas
                )
                SELECT
                    %s,
                    jogador_id,
                    posicao,
                    catches,
                    jsonb_build_object(
                        'registro_periodico_id', registro_id,
                        'data_referencia', data_referencia,
                        'nickname_atual', nickname_atual,
                        'state', state,
                        'fonte', fonte
                    )
                FROM ranked
                ORDER BY posicao
                """,
                (periodo_tipo, list(VALID_REPROCESS_STATUSES), snapshot_id),
            )
            itens_criados = cur.rowcount

            cur.execute(
                """
                UPDATE rankings_snapshot
                SET status = 'pronto',
                    data_processamento = now()
                WHERE id = %s
                """,
                (snapshot_id,),
            )

        conn.commit()
        return {
            "success": True,
            "errors": [],
            "snapshot_id": snapshot_id,
            "ranking_tipo": "geral",
            "periodo_tipo": periodo_tipo,
            "data_base": data_base.isoformat() if hasattr(data_base, "isoformat") else str(data_base),
            "jogadores_processados": total_jogadores,
            "itens_criados": int(itens_criados or 0),
            "primeira_data": (
                summary.get("primeira_data").isoformat()
                if hasattr(summary.get("primeira_data"), "isoformat")
                else str(summary.get("primeira_data") or "")
            ),
            "maior_valor": int(summary.get("maior_valor") or 0),
        }
    except Exception:
        conn.rollback()
        return {"success": False, "errors": ["Nao foi possivel reprocessar o ranking atual."]}
    finally:
        if owns_connection and context is not None:
            context.__exit__(None, None, None)
