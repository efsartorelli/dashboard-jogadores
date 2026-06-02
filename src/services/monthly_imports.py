from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
import hashlib
import io
import json
import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any

import pandas as pd

from src.database.connection import get_connection
from src.database.repositories import buscar_usuario_por_id
from src.validation.submissions import BRAZILIAN_STATES, sanitize_text


REQUIRED_COLUMNS = ("nickname", "estado", "capturas")
MONTHLY_IMPORT_SOURCE = "xlsx_curadoria"
FUZZY_DUPLICATE_THRESHOLD = 0.88


@dataclass
class ExistingPlayer:
    id: int
    nickname: str
    state: str | None
    nickname_key: str
    alias_keys: set[str] = field(default_factory=set)


@dataclass
class ImportPreviewLine:
    linha_numero: int
    nickname_xlsx: str
    estado_xlsx: str
    capturas_xlsx: int | None
    capturas_original: str
    jogador_banco: str | None = None
    player_id: int | None = None
    ultimo_valor: int | None = None
    novo_valor: int | None = None
    diferenca: int | None = None
    status: str = "Erro"
    mensagem: str = ""
    acao: str = "ignorar"
    status_validacao: str = "erro"
    erros: list[str] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)
    nickname_key: str = ""
    can_import: bool = False


@dataclass
class ImportAnalysis:
    arquivo_nome: str
    arquivo_hash: str
    data_referencia: date
    total_linhas: int
    linhas: list[ImportPreviewLine]
    errors: list[str] = field(default_factory=list)

    @property
    def linhas_validas(self) -> int:
        return sum(1 for line in self.linhas if line.can_import)

    @property
    def linhas_com_erro(self) -> int:
        return sum(1 for line in self.linhas if line.status_validacao == "erro")

    @property
    def linhas_alerta(self) -> int:
        return sum(1 for line in self.linhas if line.status_validacao == "alerta")

    @property
    def has_blocking_errors(self) -> bool:
        return bool(self.errors) or self.linhas_com_erro > 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "arquivo_nome": self.arquivo_nome,
            "arquivo_hash": self.arquivo_hash,
            "data_referencia": self.data_referencia.isoformat(),
            "total_linhas": self.total_linhas,
            "errors": list(self.errors),
            "linhas": [asdict(line) for line in self.linhas],
        }


def analysis_from_dict(payload: dict[str, Any]) -> ImportAnalysis:
    return ImportAnalysis(
        arquivo_nome=str(payload.get("arquivo_nome") or ""),
        arquivo_hash=str(payload.get("arquivo_hash") or ""),
        data_referencia=date.fromisoformat(str(payload.get("data_referencia"))),
        total_linhas=int(payload.get("total_linhas") or 0),
        errors=list(payload.get("errors") or []),
        linhas=[
            ImportPreviewLine(
                **{
                    **line,
                    "capturas_xlsx": None if line.get("capturas_xlsx") is None else int(line.get("capturas_xlsx")),
                    "player_id": None if line.get("player_id") is None else int(line.get("player_id")),
                    "ultimo_valor": None if line.get("ultimo_valor") is None else int(line.get("ultimo_valor")),
                    "novo_valor": None if line.get("novo_valor") is None else int(line.get("novo_valor")),
                    "diferenca": None if line.get("diferenca") is None else int(line.get("diferenca")),
                }
            )
            for line in payload.get("linhas", [])
        ],
    )


def normalize_nickname_key(value: object) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or "").strip())
    without_accents = "".join(char for char in normalized if not unicodedata.combining(char))
    return " ".join(without_accents.casefold().split())


def compact_nickname_key(value: object) -> str:
    return re.sub(r"[^a-z0-9]", "", normalize_nickname_key(value))


def _normalize_column_name(value: object) -> str:
    key = normalize_nickname_key(value).replace(" ", "_")
    return re.sub(r"[^a-z0-9_]", "", key)


def _read_file_bytes(uploaded_file: Any) -> bytes:
    if isinstance(uploaded_file, bytes):
        return uploaded_file
    if isinstance(uploaded_file, bytearray):
        return bytes(uploaded_file)
    if hasattr(uploaded_file, "getvalue"):
        return bytes(uploaded_file.getvalue())
    if hasattr(uploaded_file, "read"):
        current_pos = None
        try:
            current_pos = uploaded_file.tell()
        except Exception:
            current_pos = None
        content = uploaded_file.read()
        if current_pos is not None:
            try:
                uploaded_file.seek(current_pos)
            except Exception:
                pass
        return bytes(content)
    raise ValueError("Arquivo XLSX invalido.")


def _parse_captures(value: object) -> int | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else None

    text = str(value).strip()
    if not text:
        return None
    text = text.replace("\u00a0", " ")
    if "," in text and text.rfind(",") > text.rfind("."):
        decimal_part = text[text.rfind(",") + 1 :]
        if 0 < len(decimal_part) <= 2:
            text = text[: text.rfind(",")]
    digits = re.sub(r"\D", "", text)
    return int(digits) if digits else None


def read_monthly_import_rows(uploaded_file: Any) -> tuple[list[dict[str, Any]], str]:
    file_bytes = _read_file_bytes(uploaded_file)
    file_hash = hashlib.sha256(file_bytes).hexdigest()
    df = pd.read_excel(io.BytesIO(file_bytes), sheet_name=0)
    df = df.dropna(how="all").copy()
    df.columns = [_normalize_column_name(column) for column in df.columns]

    aliases = {
        "nickname": "nickname",
        "nick": "nickname",
        "jogador": "nickname",
        "player": "nickname",
        "estado": "estado",
        "uf": "estado",
        "state": "estado",
        "capturas": "capturas",
        "catches": "capturas",
        "total_capturas": "capturas",
        "total_de_capturas": "capturas",
    }
    df = df.rename(columns={column: aliases.get(column, column) for column in df.columns})
    missing = [column for column in REQUIRED_COLUMNS if column not in df.columns]
    if missing:
        raise ValueError(f"Colunas obrigatorias ausentes: {', '.join(missing)}.")

    rows: list[dict[str, Any]] = []
    for index, row in df.iterrows():
        rows.append({
            "linha_numero": int(index) + 2,
            "nickname": row.get("nickname"),
            "estado": row.get("estado"),
            "capturas": row.get("capturas"),
        })
    return rows, file_hash


def _is_moderator_or_admin(conn, user_id: str | None) -> bool:
    if not user_id:
        return False
    profile = buscar_usuario_por_id(conn, user_id)
    return str((profile or {}).get("role") or "").lower() in {"admin", "moderador"}


def _fetch_existing_players(conn) -> tuple[list[ExistingPlayer], dict[int, int], dict[int, int]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, nickname_atual, state, COALESCE(nickname_key, '') AS nickname_key
            FROM jogadores
            WHERE ativo = TRUE
            """
        )
        player_rows = list(cur.fetchall())
        cur.execute(
            """
            SELECT jogador_id, nickname, COALESCE(nickname_key, '') AS nickname_key
            FROM jogador_nicknames
            WHERE ativo = TRUE
            """
        )
        alias_rows = list(cur.fetchall())
        cur.execute(
            """
            SELECT DISTINCT ON (jogador_id)
                jogador_id,
                catches,
                id AS registro_id
            FROM registros_periodicos
            WHERE periodo_tipo = 'mensal'
              AND status IN ('pendente', 'validado')
            ORDER BY jogador_id, data_referencia DESC, created_at DESC, id DESC
            """
        )
        latest_rows = list(cur.fetchall())
        cur.execute(
            """
            SELECT jogador_id, id AS registro_id
            FROM registros_periodicos
            WHERE periodo_tipo = 'mensal'
              AND status IN ('pendente', 'validado')
            """
        )
        all_snapshot_rows = list(cur.fetchall())

    players_by_id: dict[int, ExistingPlayer] = {}
    for row in player_rows:
        nickname = str(row["nickname_atual"] or "").strip()
        key = str(row.get("nickname_key") or "").strip() or normalize_nickname_key(nickname)
        players_by_id[int(row["id"])] = ExistingPlayer(
            id=int(row["id"]),
            nickname=nickname,
            state=row.get("state"),
            nickname_key=key,
            alias_keys={key},
        )

    for row in alias_rows:
        player = players_by_id.get(int(row["jogador_id"]))
        if not player:
            continue
        key = str(row.get("nickname_key") or "").strip() or normalize_nickname_key(row.get("nickname"))
        if key:
            player.alias_keys.add(key)

    latest = {int(row["jogador_id"]): int(row["catches"]) for row in latest_rows}
    snapshots = {int(row["registro_id"]): int(row["jogador_id"]) for row in all_snapshot_rows}
    return list(players_by_id.values()), latest, snapshots


def _fetch_snapshots_for_date(conn, data_referencia: date) -> dict[int, int]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT jogador_id, id
            FROM registros_periodicos
            WHERE periodo_tipo = 'mensal'
              AND data_referencia = %s
              AND status IN ('pendente', 'validado')
            """,
            (data_referencia,),
        )
        return {int(row["jogador_id"]): int(row["id"]) for row in cur.fetchall()}


def _find_exact_player(nickname_key: str, players: list[ExistingPlayer]) -> ExistingPlayer | None:
    matches = [player for player in players if nickname_key in player.alias_keys]
    return matches[0] if len(matches) == 1 else None


def _find_possible_duplicate(nickname_key: str, players: list[ExistingPlayer]) -> ExistingPlayer | None:
    compact = compact_nickname_key(nickname_key)
    if not compact:
        return None

    best_player = None
    best_score = 0.0
    for player in players:
        for alias_key in player.alias_keys:
            alias_compact = compact_nickname_key(alias_key)
            if not alias_compact:
                continue
            score = SequenceMatcher(None, compact, alias_compact).ratio()
            if compact == alias_compact and nickname_key != alias_key:
                score = 0.99
            if score > best_score:
                best_score = score
                best_player = player

    if best_player and best_score >= FUZZY_DUPLICATE_THRESHOLD:
        return best_player
    return None


def build_import_preview(
    raw_rows: list[dict[str, Any]],
    players: list[ExistingPlayer],
    latest_catches: dict[int, int],
    snapshots_for_date: dict[int, int],
) -> list[ImportPreviewLine]:
    preview: list[ImportPreviewLine] = []
    seen_keys: dict[str, int] = {}
    seen_players: dict[int, int] = {}

    for raw in raw_rows:
        nickname = sanitize_text(raw.get("nickname"), max_length=80)
        state = sanitize_text(raw.get("estado"), max_length=2).upper()
        captures_original = "" if raw.get("capturas") is None else str(raw.get("capturas"))
        captures = _parse_captures(raw.get("capturas"))
        nickname_key = normalize_nickname_key(nickname)

        line = ImportPreviewLine(
            linha_numero=int(raw.get("linha_numero") or len(preview) + 2),
            nickname_xlsx=nickname,
            estado_xlsx=state,
            capturas_xlsx=captures,
            capturas_original=captures_original,
            novo_valor=captures,
            nickname_key=nickname_key,
        )

        if not nickname:
            line.erros.append("Nickname obrigatorio.")
        if not state:
            line.erros.append("Estado obrigatorio.")
        elif state not in BRAZILIAN_STATES:
            line.erros.append("Estado deve ser uma UF brasileira valida.")
        if captures is None:
            line.erros.append("Capturas devem ser um numero inteiro.")
        elif captures <= 0:
            line.erros.append("Capturas totais devem ser maiores que zero.")
        elif captures > 9_999_999_999:
            line.erros.append("Capturas totais excedem o limite permitido.")
        if nickname_key and nickname_key in seen_keys:
            line.erros.append(f"Nickname repetido na planilha; primeira ocorrencia na linha {seen_keys[nickname_key]}.")

        player = _find_exact_player(nickname_key, players) if nickname_key else None
        possible_duplicate = None if player else _find_possible_duplicate(nickname_key, players)

        if player:
            line.jogador_banco = player.nickname
            line.player_id = player.id
            line.ultimo_valor = latest_catches.get(player.id)
            if captures is not None and line.ultimo_valor is not None:
                line.diferenca = captures - line.ultimo_valor
            if player.id in seen_players:
                line.erros.append(f"Jogador repetido na planilha; primeira ocorrencia na linha {seen_players[player.id]}.")
            if player.id in snapshots_for_date:
                line.erros.append("Ja existe snapshot para este jogador na data de referencia.")
            if line.ultimo_valor is not None and captures is not None and captures < line.ultimo_valor:
                line.erros.append("Capturas menores que o ultimo valor registrado.")
            if player.state and state and str(player.state).upper() != state:
                line.avisos.append(f"Estado diferente do banco: banco={str(player.state).upper()}, planilha={state}.")
            line.acao = "usar_existente"
        elif possible_duplicate:
            line.jogador_banco = possible_duplicate.nickname
            line.player_id = possible_duplicate.id
            line.ultimo_valor = latest_catches.get(possible_duplicate.id)
            if captures is not None and line.ultimo_valor is not None:
                line.diferenca = captures - line.ultimo_valor
            line.avisos.append("Nickname muito parecido com jogador existente; revisar antes de criar novo jogador.")
            line.acao = "possivel_duplicado"
        else:
            line.acao = "criar_jogador"

        if line.player_id and line.player_id not in seen_players:
            seen_players[line.player_id] = line.linha_numero
        if nickname_key and nickname_key not in seen_keys:
            seen_keys[nickname_key] = line.linha_numero

        if line.erros:
            line.status = "Erro"
            line.status_validacao = "erro"
            line.mensagem = "; ".join(line.erros)
            line.can_import = False
        elif line.acao == "possivel_duplicado":
            line.status = "Possivel duplicado"
            line.status_validacao = "alerta"
            line.mensagem = "; ".join(line.avisos)
            line.can_import = False
        elif line.avisos:
            line.status = "Alerta"
            line.status_validacao = "alerta"
            line.mensagem = "; ".join(line.avisos)
            line.can_import = True
        elif line.acao == "usar_existente":
            line.status = "Jogador existente"
            line.status_validacao = "ok"
            line.mensagem = "Vincular ao jogador existente."
            line.can_import = True
        else:
            line.status = "Novo jogador"
            line.status_validacao = "ok"
            line.mensagem = "Criar jogador somente na confirmacao."
            line.can_import = True

        preview.append(line)

    return preview


def analyze_monthly_import(
    uploaded_file: Any,
    data_referencia: date,
    arquivo_nome: str | None = None,
    conn=None,
) -> ImportAnalysis:
    if data_referencia > date.today():
        return ImportAnalysis(
            arquivo_nome=arquivo_nome or "ranking.xlsx",
            arquivo_hash="",
            data_referencia=data_referencia,
            total_linhas=0,
            linhas=[],
            errors=["Data de referencia nao pode ser futura."],
        )

    rows, file_hash = read_monthly_import_rows(uploaded_file)
    owns_connection = conn is None
    context = get_connection() if owns_connection else None
    if owns_connection:
        conn = context.__enter__()
    try:
        players, latest_catches, _ = _fetch_existing_players(conn)
        snapshots_for_date = _fetch_snapshots_for_date(conn, data_referencia)
        preview = build_import_preview(rows, players, latest_catches, snapshots_for_date)
        return ImportAnalysis(
            arquivo_nome=arquivo_nome or getattr(uploaded_file, "name", "ranking.xlsx"),
            arquivo_hash=file_hash,
            data_referencia=data_referencia,
            total_linhas=len(rows),
            linhas=preview,
        )
    finally:
        if owns_connection and context is not None:
            context.__exit__(None, None, None)


def _insert_import_batch(conn, analysis: ImportAnalysis, admin_user_id: str | None) -> int:
    jogadores_existentes = sum(1 for line in analysis.linhas if line.can_import and line.acao == "usar_existente")
    jogadores_criados = sum(1 for line in analysis.linhas if line.can_import and line.acao == "criar_jogador")
    linhas_ignoradas = sum(1 for line in analysis.linhas if not line.can_import)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO importacoes_xlsx (
                arquivo_nome,
                arquivo_hash,
                data_referencia,
                status,
                total_linhas,
                linhas_validas,
                linhas_com_erro,
                linhas_alerta,
                jogadores_existentes,
                jogadores_criados,
                snapshots_criados,
                linhas_ignoradas,
                created_by,
                confirmed_by,
                confirmed_at,
                metadata
            )
            VALUES (%s, %s, %s, 'confirmado', %s, %s, %s, %s, %s, %s, 0, %s, %s, %s, now(), %s)
            RETURNING id
            """,
            (
                analysis.arquivo_nome,
                analysis.arquivo_hash,
                analysis.data_referencia,
                analysis.total_linhas,
                analysis.linhas_validas,
                analysis.linhas_com_erro,
                analysis.linhas_alerta,
                jogadores_existentes,
                jogadores_criados,
                linhas_ignoradas,
                admin_user_id,
                admin_user_id,
                json.dumps({"source": MONTHLY_IMPORT_SOURCE}, ensure_ascii=False),
            ),
        )
        return int(cur.fetchone()["id"])


def _insert_import_line(conn, import_id: int, line: ImportPreviewLine) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO importacao_linhas (
                importacao_id,
                linha_numero,
                nickname_original,
                nickname_normalizado,
                nickname_key,
                estado_original,
                estado_normalizado,
                capturas_original,
                capturas,
                jogador_id,
                jogador_nickname,
                ultimo_catches,
                diferenca,
                acao,
                status_validacao,
                status_linha,
                mensagem,
                erros,
                avisos
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                import_id,
                line.linha_numero,
                line.nickname_xlsx,
                line.nickname_xlsx,
                line.nickname_key,
                line.estado_xlsx,
                line.estado_xlsx,
                line.capturas_original,
                line.capturas_xlsx,
                line.player_id,
                line.jogador_banco,
                line.ultimo_valor,
                line.diferenca,
                line.acao,
                line.status_validacao,
                line.status,
                line.mensagem,
                json.dumps(line.erros, ensure_ascii=False),
                json.dumps(line.avisos, ensure_ascii=False),
            ),
        )
        return int(cur.fetchone()["id"])


def _create_player(conn, line: ImportPreviewLine) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO jogadores (nickname_atual, nickname_key, country, state, mostrar, ativo, state_updated_at)
            VALUES (%s, %s, 'Brasil', %s, TRUE, TRUE, now())
            RETURNING id
            """,
            (line.nickname_xlsx, line.nickname_key, line.estado_xlsx),
        )
        player_id = int(cur.fetchone()["id"])
        cur.execute(
            """
            INSERT INTO jogador_nicknames (jogador_id, nickname, nickname_key, inicio_em, ativo, motivo)
            VALUES (%s, %s, %s, %s, TRUE, 'importacao_mensal')
            """,
            (player_id, line.nickname_xlsx, line.nickname_key, date.today()),
        )
        return player_id


def _ensure_player_alias(conn, player_id: int, line: ImportPreviewLine) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE jogadores
            SET nickname_key = COALESCE(NULLIF(nickname_key, ''), %s),
                updated_at = now()
            WHERE id = %s
            """,
            (line.nickname_key, player_id),
        )
        cur.execute(
            """
            INSERT INTO jogador_nicknames (jogador_id, nickname, nickname_key, inicio_em, ativo, motivo)
            SELECT %s, %s, %s, %s, TRUE, 'importacao_mensal'
            WHERE NOT EXISTS (
                SELECT 1
                FROM jogador_nicknames
                WHERE jogador_id = %s
                  AND (
                    lower(nickname) = lower(%s)
                    OR COALESCE(nickname_key, '') = %s
                  )
            )
            """,
            (
                player_id,
                line.nickname_xlsx,
                line.nickname_key,
                analysis_date_or_today(line),
                player_id,
                line.nickname_xlsx,
                line.nickname_key,
            ),
        )


def analysis_date_or_today(_line: ImportPreviewLine) -> date:
    return date.today()


def _insert_snapshot(
    conn,
    import_id: int,
    import_line_id: int,
    player_id: int,
    line: ImportPreviewLine,
    data_referencia: date,
    admin_user_id: str | None,
) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO registros_periodicos (
                jogador_id,
                periodo_tipo,
                data_referencia,
                catches,
                fonte,
                observacao,
                status,
                created_by,
                submission_type,
                reviewed_by,
                reviewed_at,
                validation_metadata,
                importacao_id,
                importacao_linha_id
            )
            VALUES (
                %s, 'mensal', %s, %s, %s, %s, 'validado', %s, 'import', %s, now(),
                %s::jsonb, %s, %s
            )
            RETURNING id
            """,
            (
                player_id,
                data_referencia,
                int(line.capturas_xlsx or 0),
                MONTHLY_IMPORT_SOURCE,
                f"Importacao XLSX Curadoria #{import_id}",
                admin_user_id,
                admin_user_id,
                json.dumps({
                    "nickname_xlsx": line.nickname_xlsx,
                    "estado_xlsx": line.estado_xlsx,
                    "status_previa": line.status,
                    "avisos": line.avisos,
                }, ensure_ascii=False),
                import_id,
                import_line_id,
            ),
        )
        return int(cur.fetchone()["id"])


def confirm_monthly_import(
    analysis_payload: dict[str, Any] | ImportAnalysis,
    admin_user_id: str | None,
    conn=None,
) -> dict[str, Any]:
    analysis = analysis_payload if isinstance(analysis_payload, ImportAnalysis) else analysis_from_dict(analysis_payload)
    if analysis.has_blocking_errors:
        return {
            "success": False,
            "errors": ["Corrija as linhas com erro antes de confirmar a importacao."],
        }
    if not any(line.can_import for line in analysis.linhas):
        return {"success": False, "errors": ["Nenhuma linha valida para importar."]}

    owns_connection = conn is None
    context = get_connection() if owns_connection else None
    if owns_connection:
        conn = context.__enter__()
    try:
        if not _is_moderator_or_admin(conn, admin_user_id):
            return {"success": False, "errors": ["Acesso restrito a administradores e moderadores."]}

        import_id = _insert_import_batch(conn, analysis, admin_user_id)
        snapshots_created = 0
        existing_players = 0
        new_players = 0
        ignored_lines = 0

        for line in analysis.linhas:
            import_line_id = _insert_import_line(conn, import_id, line)
            if not line.can_import:
                ignored_lines += 1
                continue

            if line.acao == "criar_jogador":
                player_id = _create_player(conn, line)
                new_players += 1
            else:
                player_id = int(line.player_id or 0)
                _ensure_player_alias(conn, player_id, line)
                existing_players += 1

            record_id = _insert_snapshot(
                conn,
                import_id,
                import_line_id,
                player_id,
                line,
                analysis.data_referencia,
                admin_user_id,
            )
            snapshots_created += 1
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE importacao_linhas
                    SET jogador_id = %s,
                        registro_periodico_id = %s
                    WHERE id = %s
                    """,
                    (player_id, record_id, import_line_id),
                )

        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE importacoes_xlsx
                SET jogadores_existentes = %s,
                    jogadores_criados = %s,
                    snapshots_criados = %s,
                    linhas_ignoradas = %s,
                    updated_at = now()
                WHERE id = %s
                """,
                (existing_players, new_players, snapshots_created, ignored_lines, import_id),
            )

        conn.commit()
        return {
            "success": True,
            "errors": [],
            "importacao_id": import_id,
            "data_referencia": analysis.data_referencia.isoformat(),
            "jogadores_existentes": existing_players,
            "novos_jogadores": new_players,
            "snapshots_criados": snapshots_created,
            "linhas_ignoradas": ignored_lines,
            "linhas_com_erro": analysis.linhas_com_erro,
            "linhas_alerta": analysis.linhas_alerta,
        }
    except Exception as exc:
        conn.rollback()
        return {"success": False, "errors": [f"Nao foi possivel confirmar a importacao: {exc}"]}
    finally:
        if owns_connection and context is not None:
            context.__exit__(None, None, None)


def list_monthly_imports(admin_user_id: str | None, limit: int = 20, conn=None) -> dict[str, Any]:
    owns_connection = conn is None
    context = get_connection() if owns_connection else None
    if owns_connection:
        conn = context.__enter__()
    try:
        if not _is_moderator_or_admin(conn, admin_user_id):
            return {"success": False, "errors": ["Acesso restrito a administradores e moderadores."], "imports": []}
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    id,
                    arquivo_nome,
                    data_referencia,
                    status,
                    total_linhas,
                    linhas_validas,
                    linhas_com_erro,
                    linhas_alerta,
                    jogadores_existentes,
                    jogadores_criados,
                    snapshots_criados,
                    linhas_ignoradas,
                    confirmed_at,
                    undone_at,
                    created_at
                FROM importacoes_xlsx
                ORDER BY created_at DESC, id DESC
                LIMIT %s
                """,
                (max(1, min(int(limit), 100)),),
            )
            return {"success": True, "errors": [], "imports": list(cur.fetchall())}
    except Exception as exc:
        try:
            conn.rollback()
        except Exception:
            pass
        message = str(exc)
        if "importacoes_xlsx" in message or "importacao_linhas" in message:
            message = "Tabelas de importacao mensal ainda nao existem. Aplique a migration 005_monthly_ranking_imports.sql no Supabase."
        else:
            message = f"Nao foi possivel carregar o historico de importacoes: {message}"
        return {"success": False, "errors": [message], "imports": []}
    finally:
        if owns_connection and context is not None:
            context.__exit__(None, None, None)


def undo_monthly_import(importacao_id: int, admin_user_id: str | None, conn=None) -> dict[str, Any]:
    owns_connection = conn is None
    context = get_connection() if owns_connection else None
    if owns_connection:
        conn = context.__enter__()
    try:
        if not _is_moderator_or_admin(conn, admin_user_id):
            return {"success": False, "errors": ["Acesso restrito a administradores e moderadores."]}
        with conn.cursor() as cur:
            cur.execute("SELECT id, status FROM importacoes_xlsx WHERE id = %s", (importacao_id,))
            import_row = cur.fetchone()
            if not import_row:
                return {"success": False, "errors": ["Importacao nao encontrada."]}
            if import_row["status"] != "confirmado":
                return {"success": False, "errors": ["Apenas importacoes confirmadas podem ser desfeitas."]}

            cur.execute(
                """
                UPDATE registros_periodicos
                SET status = 'rejeitado',
                    curadoria_observacao = COALESCE(curadoria_observacao || E'\n', '') || 'Importacao desfeita pela Curadoria.',
                    reviewed_by = %s,
                    reviewed_at = now(),
                    updated_at = now()
                WHERE importacao_id = %s
                  AND status = 'validado'
                RETURNING id
                """,
                (admin_user_id, importacao_id),
            )
            reverted = len(cur.fetchall())
            cur.execute(
                """
                UPDATE importacoes_xlsx
                SET status = 'desfeito',
                    undone_by = %s,
                    undone_at = now(),
                    updated_at = now()
                WHERE id = %s
                """,
                (admin_user_id, importacao_id),
            )
        conn.commit()
        return {"success": True, "errors": [], "importacao_id": importacao_id, "snapshots_desfeitos": reverted}
    except Exception as exc:
        conn.rollback()
        return {"success": False, "errors": [f"Nao foi possivel desfazer a importacao: {exc}"]}
    finally:
        if owns_connection and context is not None:
            context.__exit__(None, None, None)
