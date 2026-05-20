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


def contar_registros_curadoria(
    conn,
    status: str = "pendente",
    search: str | None = None,
) -> int:
    where_clauses = ["r.status = %s"]
    params: list[Any] = [status]
    if search:
        where_clauses.append(
            """(
                j.nickname_atual ILIKE %s
                OR COALESCE(u.email, '') ILIKE %s
                OR COALESCE(u.nome, '') ILIKE %s
                OR COALESCE(r.observacao, '') ILIKE %s
            )"""
        )
        search_param = f"%{search}%"
        params.extend([search_param, search_param, search_param, search_param])

    row = _fetchone(
        conn,
        f"""
        SELECT COUNT(*) AS total
        FROM registros_periodicos r
        JOIN jogadores j ON j.id = r.jogador_id
        LEFT JOIN usuarios u ON u.id = r.created_by
        WHERE {" AND ".join(where_clauses)}
        """,
        tuple(params),
    )
    return int(row["total"]) if row else 0


def listar_registros_curadoria(
    conn,
    status: str = "pendente",
    search: str | None = None,
    order_by: str = "created_at",
    order_direction: str = "asc",
    limit: int = 20,
    offset: int = 0,
) -> list[dict[str, Any]]:
    order_columns = {
        "created_at": "r.created_at",
        "data_referencia": "r.data_referencia",
        "catches": "r.catches",
        "nickname": "j.nickname_atual",
        "email": "u.email",
        "periodo_tipo": "r.periodo_tipo",
    }
    order_sql = order_columns.get(order_by, "r.created_at")
    direction_sql = "DESC" if str(order_direction).lower() == "desc" else "ASC"
    where_clauses = ["r.status = %s"]
    params: list[Any] = [status]
    if search:
        where_clauses.append(
            """(
                j.nickname_atual ILIKE %s
                OR COALESCE(u.email, '') ILIKE %s
                OR COALESCE(u.nome, '') ILIKE %s
                OR COALESCE(r.observacao, '') ILIKE %s
            )"""
        )
        search_param = f"%{search}%"
        params.extend([search_param, search_param, search_param, search_param])
    params.extend([max(1, min(int(limit), 100)), max(0, int(offset))])

    return _fetchall(
        conn,
        f"""
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
            r.updated_at,
            r.status,
            r.created_by,
            u.nome AS usuario_nome,
            u.email AS usuario_email,
            r.curadoria_observacao,
            r.reviewed_by,
            r.reviewed_at
        FROM registros_periodicos r
        JOIN jogadores j ON j.id = r.jogador_id
        LEFT JOIN usuarios u ON u.id = r.created_by
        WHERE {" AND ".join(where_clauses)}
        ORDER BY {order_sql} {direction_sql}, r.id {direction_sql}
        LIMIT %s OFFSET %s
        """,
        tuple(params),
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
            r.created_at,
            r.created_by,
            r.curadoria_observacao,
            r.reviewed_by,
            r.reviewed_at
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


def atualizar_curadoria_registro(
    conn,
    record_id: int,
    reviewed_by: str | None = None,
    curadoria_observacao: str | None = None,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE registros_periodicos
            SET reviewed_by = %s,
                reviewed_at = now(),
                curadoria_observacao = %s,
                updated_at = now()
            WHERE id = %s
            """,
            (reviewed_by, curadoria_observacao, record_id),
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


def buscar_usuario_por_id(conn, user_id: str) -> dict[str, Any] | None:
    return _fetchone(
        conn,
        """
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
            premium_until,
            input_monthly_limit,
            created_at,
            updated_at,
            last_login_at,
            last_seen_at,
            email_verified
        FROM usuarios
        WHERE id = %s
        """,
        (user_id,),
    )


def upsert_usuario_profile(
    conn,
    user_id: str,
    email: str,
    nome: str | None = None,
    nickname: str | None = None,
    pais: str | None = None,
    estado: str | None = None,
    cidade: str | None = None,
    email_verified: bool = False,
) -> dict[str, Any]:
    return _fetchone(
        conn,
        """
        INSERT INTO usuarios (
            id, email, nome, nickname, pais, estado, cidade, email_verified, last_login_at, last_seen_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now(), now())
        ON CONFLICT (id) DO UPDATE SET
            email = EXCLUDED.email,
            nome = COALESCE(NULLIF(usuarios.nome, ''), EXCLUDED.nome),
            nickname = COALESCE(NULLIF(usuarios.nickname, ''), EXCLUDED.nickname),
            pais = COALESCE(NULLIF(usuarios.pais, ''), EXCLUDED.pais),
            estado = COALESCE(NULLIF(usuarios.estado, ''), EXCLUDED.estado),
            cidade = COALESCE(NULLIF(usuarios.cidade, ''), EXCLUDED.cidade),
            email_verified = usuarios.email_verified OR EXCLUDED.email_verified,
            last_login_at = now(),
            last_seen_at = now(),
            updated_at = now()
        RETURNING
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
            premium_until,
            input_monthly_limit,
            created_at,
            updated_at,
            last_login_at,
            last_seen_at,
            email_verified
        """,
        (user_id, email, nome, nickname, pais, estado, cidade, email_verified),
    )


def atualizar_usuario_profile(
    conn,
    user_id: str,
    nome: str | None = None,
    nickname: str | None = None,
    pais: str | None = None,
    estado: str | None = None,
    cidade: str | None = None,
) -> dict[str, Any] | None:
    return _fetchone(
        conn,
        """
        UPDATE usuarios
        SET nome = %s,
            nickname = %s,
            pais = %s,
            estado = %s,
            cidade = %s,
            updated_at = now(),
            last_seen_at = now()
        WHERE id = %s
        RETURNING
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
            premium_until,
            input_monthly_limit,
            created_at,
            updated_at,
            last_login_at,
            last_seen_at,
            email_verified
        """,
        (nome, nickname, pais, estado, cidade, user_id),
    )


def tocar_ultimo_acesso_usuario(conn, user_id: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE usuarios
            SET last_seen_at = now(),
                updated_at = now()
            WHERE id = %s
            """,
            (user_id,),
        )


def contar_inputs_usuario_mes(
    conn,
    user_id: str,
    month_start: date,
    next_month_start: date,
) -> int:
    row = _fetchone(
        conn,
        """
        SELECT COUNT(*) AS total
        FROM registros_periodicos
        WHERE created_by = %s
          AND created_at >= %s
          AND created_at < %s
          AND fonte <> 'admin'
        """,
        (user_id, month_start, next_month_start),
    )
    return int(row["total"]) if row else 0


def listar_inputs_usuario(conn, user_id: str, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
    return _fetchall(
        conn,
        """
        SELECT
            r.id,
            j.nickname_atual AS nickname,
            j.state,
            r.periodo_tipo,
            r.data_referencia,
            r.catches,
            r.status,
            r.observacao,
            r.curadoria_observacao,
            r.created_at,
            r.reviewed_at,
            r.updated_at
        FROM registros_periodicos r
        JOIN jogadores j ON j.id = r.jogador_id
        WHERE r.created_by = %s
        ORDER BY r.created_at DESC, r.id DESC
        LIMIT %s OFFSET %s
        """,
        (user_id, limit, offset),
    )


def estatisticas_inputs_usuario(conn, user_id: str) -> dict[str, Any]:
    return _fetchone(
        conn,
        """
        SELECT
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE status = 'pendente') AS pendentes,
            COUNT(*) FILTER (WHERE status = 'validado') AS aprovados,
            COUNT(*) FILTER (WHERE status = 'rejeitado') AS rejeitados,
            COALESCE(MAX(created_at), NULL) AS ultimo_envio
        FROM registros_periodicos
        WHERE created_by = %s
        """,
        (user_id,),
    ) or {
        "total": 0,
        "pendentes": 0,
        "aprovados": 0,
        "rejeitados": 0,
        "ultimo_envio": None,
    }


def contar_eventos_seguranca(
    conn,
    event_type: str,
    since_timestamp,
    user_id: str | None = None,
    subject_hash: str | None = None,
) -> int:
    user_clause = "AND user_id = %s" if user_id else ""
    subject_clause = "AND subject_hash = %s" if subject_hash else ""
    params: list[Any] = [event_type, since_timestamp]
    if user_id:
        params.append(user_id)
    if subject_hash:
        params.append(subject_hash)

    row = _fetchone(
        conn,
        f"""
        SELECT COUNT(*) AS total
        FROM security_events
        WHERE event_type = %s
          AND created_at >= %s
          {user_clause}
          {subject_clause}
        """,
        tuple(params),
    )
    return int(row["total"]) if row else 0


def registrar_evento_seguranca(
    conn,
    event_type: str,
    user_id: str | None = None,
    subject_hash: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO security_events (event_type, user_id, subject_hash, metadata)
            VALUES (%s, %s, %s, %s)
            """,
            (
                event_type,
                user_id,
                subject_hash,
                json.dumps(metadata or {}, ensure_ascii=False),
            ),
        )


def criar_pagamento(
    conn,
    user_id: str,
    provider: str,
    amount_cents: int,
    currency: str,
    external_reference: str,
    checkout_url: str | None = None,
    plan_code: str = "premium_monthly",
    status: str = "checkout_pending",
) -> dict[str, Any]:
    return _fetchone(
        conn,
        """
        INSERT INTO pagamentos (
            user_id,
            provider,
            plan_code,
            status,
            amount_cents,
            currency,
            external_reference,
            checkout_url
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING
            id,
            user_id,
            provider,
            plan_code,
            status,
            amount_cents,
            currency,
            external_reference,
            checkout_url,
            created_at,
            updated_at
        """,
        (user_id, provider, plan_code, status, amount_cents, currency, external_reference, checkout_url),
    )


def buscar_pagamento_por_referencia(conn, external_reference: str) -> dict[str, Any] | None:
    return _fetchone(
        conn,
        """
        SELECT
            id,
            user_id,
            provider,
            plan_code,
            status,
            amount_cents,
            currency,
            external_reference,
            provider_payment_id,
            checkout_url,
            paid_at,
            created_at,
            updated_at
        FROM pagamentos
        WHERE external_reference = %s
        LIMIT 1
        """,
        (external_reference,),
    )


def listar_pagamentos_usuario(conn, user_id: str, limit: int = 20) -> list[dict[str, Any]]:
    return _fetchall(
        conn,
        """
        SELECT
            id,
            provider,
            plan_code,
            status,
            amount_cents,
            currency,
            external_reference,
            provider_payment_id,
            checkout_url,
            paid_at,
            created_at,
            updated_at
        FROM pagamentos
        WHERE user_id = %s
        ORDER BY created_at DESC, id DESC
        LIMIT %s
        """,
        (user_id, limit),
    )


def atualizar_pagamento_status(
    conn,
    payment_id: int,
    status: str,
    provider_payment_id: str | None = None,
    raw_payload: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    return _fetchone(
        conn,
        """
        UPDATE pagamentos
        SET status = %s,
            provider_payment_id = COALESCE(%s, provider_payment_id),
            raw_payload = COALESCE(%s::jsonb, raw_payload),
            paid_at = CASE WHEN %s = 'paid' THEN COALESCE(paid_at, now()) ELSE paid_at END,
            updated_at = now()
        WHERE id = %s
        RETURNING
            id,
            user_id,
            provider,
            plan_code,
            status,
            amount_cents,
            currency,
            external_reference,
            provider_payment_id,
            checkout_url,
            paid_at,
            created_at,
            updated_at
        """,
        (
            status,
            provider_payment_id,
            json.dumps(raw_payload, ensure_ascii=False) if raw_payload is not None else None,
            status,
            payment_id,
        ),
    )


def ativar_premium_usuario(
    conn,
    user_id: str,
    provider: str,
    premium_until=None,
) -> dict[str, Any] | None:
    return _fetchone(
        conn,
        """
        UPDATE usuarios
        SET is_premium = TRUE,
            premium_status = 'premium',
            premium_provider = %s,
            premium_until = %s,
            updated_at = now()
        WHERE id = %s
        RETURNING
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
            premium_until,
            input_monthly_limit,
            created_at,
            updated_at,
            last_login_at,
            last_seen_at,
            email_verified
        """,
        (provider, premium_until, user_id),
    )


def registrar_webhook_pagamento(
    conn,
    provider: str,
    event_id: str | None,
    signature_valid: bool,
    status: str,
    payload: dict[str, Any],
    user_id: str | None = None,
    payment_id: int | None = None,
    error: str | None = None,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO payment_webhook_logs (
                provider,
                event_id,
                signature_valid,
                status,
                payload,
                user_id,
                payment_id,
                error,
                processed_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now())
            ON CONFLICT (provider, event_id) WHERE event_id IS NOT NULL DO NOTHING
            """,
            (
                provider,
                event_id,
                signature_valid,
                status,
                json.dumps(payload, ensure_ascii=False),
                user_id,
                payment_id,
                error,
            ),
        )
