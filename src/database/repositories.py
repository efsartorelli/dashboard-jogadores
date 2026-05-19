from __future__ import annotations

import json
from datetime import date
from typing import Any

import pandas as pd


def _fetchall(conn, query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(query, params)
        return list(cur.fetchall())


def _fetchone(conn, query: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(query, params)
        return cur.fetchone()


def buscar_jogadores(conn, incluir_inativos: bool = False) -> list[dict[str, Any]]:
    where = "" if incluir_inativos else "WHERE mostrar = TRUE AND ativo = TRUE"
    return _fetchall(
        conn,
        f"""
        SELECT id, nickname_atual, country, state, city, mostrar, ativo
        FROM jogadores
        {where}
        ORDER BY nickname_atual
        """,
    )


def buscar_jogador_por_nickname(conn, nickname: str) -> dict[str, Any] | None:
    return _fetchone(
        conn,
        """
        SELECT j.id, j.nickname_atual, j.country, j.state, j.city, j.mostrar, j.ativo
        FROM jogadores j
        LEFT JOIN jogador_nicknames n ON n.jogador_id = j.id
        WHERE lower(j.nickname_atual) = lower(%s)
           OR lower(n.nickname) = lower(%s)
        ORDER BY j.updated_at DESC
        LIMIT 1
        """,
        (nickname, nickname),
    )


def buscar_registros_por_periodo(
    conn,
    periodo_tipo: str = "mensal",
    status: str = "validado",
) -> list[dict[str, Any]]:
    rows = _fetchall(
        conn,
        """
        SELECT
            r.id,
            r.jogador_id,
            j.nickname_atual AS nickname,
            j.state,
            r.periodo_tipo,
            r.data_referencia,
            r.catches,
            r.status
        FROM registros_periodicos r
        JOIN jogadores j ON j.id = r.jogador_id
        WHERE r.periodo_tipo = %s
          AND r.status = %s
          AND j.mostrar = TRUE
          AND j.ativo = TRUE
        ORDER BY j.nickname_atual, r.data_referencia
        """,
        (periodo_tipo, status),
    )
    return rows


def inserir_novo_jogador(
    conn,
    nickname: str,
    state: str | None = None,
    country: str | None = None,
    city: str | None = None,
    jogador_id: int | None = None,
    mostrar: bool = True,
    ativo: bool = True,
) -> int:
    columns = ["nickname_atual", "state", "country", "city", "mostrar", "ativo"]
    values: list[Any] = [nickname, state, country, city, mostrar, ativo]
    if jogador_id is not None:
        columns.insert(0, "id")
        values.insert(0, jogador_id)

    placeholders = ", ".join(["%s"] * len(values))
    sql = f"""
        INSERT INTO jogadores ({", ".join(columns)})
        VALUES ({placeholders})
        ON CONFLICT (id) DO UPDATE SET
            nickname_atual = EXCLUDED.nickname_atual,
            state = EXCLUDED.state,
            country = COALESCE(EXCLUDED.country, jogadores.country),
            city = COALESCE(EXCLUDED.city, jogadores.city),
            mostrar = EXCLUDED.mostrar,
            ativo = EXCLUDED.ativo,
            updated_at = now()
        RETURNING id
    """
    with conn.cursor() as cur:
        cur.execute(sql, tuple(values))
        row = cur.fetchone()
    return int(row["id"])


def inserir_nickname_jogador(conn, jogador_id: int, nickname: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO jogador_nicknames (jogador_id, nickname)
            SELECT %s, %s
            WHERE NOT EXISTS (
                SELECT 1 FROM jogador_nicknames
                WHERE jogador_id = %s AND lower(nickname) = lower(%s)
            )
            """,
            (jogador_id, nickname, jogador_id, nickname),
        )


def verificar_duplicidade_registro(
    conn,
    jogador_id: int,
    periodo_tipo: str,
    data_referencia: date,
    exclude_record_id: int | None = None,
    statuses: tuple[str, ...] = ("validado",),
) -> bool:
    status_placeholders = ", ".join(["%s"] * len(statuses))
    exclude_sql = "AND id <> %s" if exclude_record_id is not None else ""
    params: tuple[Any, ...]
    if exclude_record_id is not None:
        params = (jogador_id, periodo_tipo, data_referencia, *statuses, exclude_record_id)
    else:
        params = (jogador_id, periodo_tipo, data_referencia, *statuses)

    row = _fetchone(
        conn,
        f"""
        SELECT 1
        FROM registros_periodicos
        WHERE jogador_id = %s
          AND periodo_tipo = %s
          AND data_referencia = %s
          AND status IN ({status_placeholders})
          {exclude_sql}
        LIMIT 1
        """,
        params,
    )
    return row is not None


def inserir_registro_periodico(
    conn,
    jogador_id: int,
    periodo_tipo: str,
    data_referencia: date,
    catches: int,
    fonte: str = "site",
    status: str = "validado",
    created_by: str | None = None,
    observacao: str | None = None,
    contato_envio: str | None = None,
) -> int | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO registros_periodicos (
                jogador_id, periodo_tipo, data_referencia, catches, fonte, status,
                created_by, observacao, contato_envio
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
            RETURNING id
            """,
            (
                jogador_id,
                periodo_tipo,
                data_referencia,
                catches,
                fonte,
                status,
                created_by,
                observacao,
                contato_envio,
            ),
        )
        row = cur.fetchone()
    return int(row["id"]) if row else None


def listar_registros_pendentes(conn) -> list[dict[str, Any]]:
    return _fetchall(
        conn,
        """
        SELECT
            r.id,
            r.jogador_id,
            j.nickname_atual AS nickname,
            j.state,
            j.ativo,
            r.periodo_tipo,
            r.data_referencia,
            r.catches,
            r.observacao,
            r.contato_envio,
            r.created_at,
            r.status
        FROM registros_periodicos r
        JOIN jogadores j ON j.id = r.jogador_id
        WHERE r.status = 'pendente'
        ORDER BY r.created_at ASC, r.id ASC
        """,
    )


def buscar_registro_por_id(conn, record_id: int) -> dict[str, Any] | None:
    return _fetchone(
        conn,
        """
        SELECT
            r.id,
            r.jogador_id,
            j.nickname_atual AS nickname,
            j.state,
            j.ativo,
            r.periodo_tipo,
            r.data_referencia,
            r.catches,
            r.observacao,
            r.contato_envio,
            r.status,
            r.created_at
        FROM registros_periodicos r
        JOIN jogadores j ON j.id = r.jogador_id
        WHERE r.id = %s
        """,
        (record_id,),
    )


def atualizar_registro(
    conn,
    record_id: int,
    data_referencia: date,
    catches: int,
    periodo_tipo: str,
    state: str | None = None,
    observacao: str | None = None,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE registros_periodicos
            SET data_referencia = %s,
                catches = %s,
                periodo_tipo = %s,
                observacao = %s,
                updated_at = now()
            WHERE id = %s
            """,
            (data_referencia, catches, periodo_tipo, observacao, record_id),
        )
        if state is not None:
            cur.execute(
                """
                UPDATE jogadores
                SET state = %s,
                    updated_at = now()
                WHERE id = (
                    SELECT jogador_id FROM registros_periodicos WHERE id = %s
                )
                """,
                (state, record_id),
            )


def alterar_status_registro(conn, record_id: int, status: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE registros_periodicos
            SET status = %s,
                updated_at = now()
            WHERE id = %s
            """,
            (status, record_id),
        )


def registrar_auditoria(
    conn,
    record_id: int | None,
    acao: str,
    antes: dict[str, Any] | None = None,
    depois: dict[str, Any] | None = None,
    usuario_id: str | None = None,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO auditoria_registros (registro_id, acao, antes, depois, usuario_id)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (
                record_id,
                acao,
                json.dumps(antes, ensure_ascii=False) if antes is not None else None,
                json.dumps(depois, ensure_ascii=False) if depois is not None else None,
                usuario_id,
            ),
        )


def buscar_ultimo_catches(conn, jogador_id: int, periodo_tipo: str = "mensal") -> int | None:
    row = _fetchone(
        conn,
        """
        SELECT catches
        FROM registros_periodicos
        WHERE jogador_id = %s
          AND periodo_tipo = %s
          AND status IN ('validado', 'pendente')
        ORDER BY data_referencia DESC
        LIMIT 1
        """,
        (jogador_id, periodo_tipo),
    )
    return int(row["catches"]) if row else None


def buscar_rankings_materializados(
    conn,
    ranking_tipo: str,
    data_base: date | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    data_filter = "AND s.data_base = %s" if data_base else ""
    params: list[Any] = [ranking_tipo]
    if data_base:
        params.append(data_base)
    params.extend([limit, offset])

    return _fetchall(
        conn,
        f"""
        SELECT
            s.id AS snapshot_id,
            s.ranking_tipo,
            s.data_base,
            i.jogador_id,
            j.nickname_atual AS nickname,
            j.state,
            i.posicao,
            i.valor,
            i.metricas
        FROM rankings_snapshot s
        JOIN ranking_itens i ON i.snapshot_id = s.id
        LEFT JOIN jogadores j ON j.id = i.jogador_id
        WHERE s.ranking_tipo = %s
          AND s.status = 'pronto'
          {data_filter}
        ORDER BY s.data_base DESC, s.data_processamento DESC, i.posicao
        LIMIT %s OFFSET %s
        """,
        tuple(params),
    )


def carregar_dados_dashboard(conn, periodo_tipo: str = "mensal") -> pd.DataFrame:
    rows = buscar_registros_por_periodo(conn, periodo_tipo=periodo_tipo, status="validado")
    if not rows:
        columns = ["nickname", "date", "catches", "id_jogador", "state", "mostrar"]
        return pd.DataFrame(columns=columns)

    df = pd.DataFrame(rows)
    df = df.rename(columns={"jogador_id": "id_jogador", "data_referencia": "date"})
    df["date"] = pd.to_datetime(df["date"])
    df["mostrar"] = "YES"
    df = df[["nickname", "date", "catches", "id_jogador", "state", "mostrar"]]
    return df
