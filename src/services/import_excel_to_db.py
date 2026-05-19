from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from src.config import DEFAULT_EXCEL_PATH
from src.data.loaders import load_excel_data
from src.database.connection import get_connection


@dataclass
class ImportReport:
    jogadores_inseridos: int = 0
    registros_inseridos: int = 0
    registros_ignorados: int = 0
    erros: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.erros


def normalize_player_rows(df):
    players = (
        df[["id_jogador", "nickname", "state", "mostrar"]]
        .drop_duplicates("id_jogador")
        .sort_values("id_jogador")
    )
    return players.to_dict("records")


def normalize_record_rows(df, periodo_tipo: str = "mensal"):
    records = df[["id_jogador", "date", "catches"]].copy()
    records["periodo_tipo"] = periodo_tipo
    records = records.drop_duplicates(["id_jogador", "periodo_tipo", "date"])
    return records.sort_values(["id_jogador", "date"]).to_dict("records")


def import_excel_to_db(
    file_path: str | Path = DEFAULT_EXCEL_PATH,
    periodo_tipo: str = "mensal",
    conn=None,
) -> ImportReport:
    report = ImportReport()
    owns_connection = conn is None
    context = get_connection() if owns_connection else None

    if owns_connection:
        conn = context.__enter__()

    try:
        df = load_excel_data(file_path)
        player_rows = normalize_player_rows(df)
        record_rows = normalize_record_rows(df, periodo_tipo=periodo_tipo)

        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS total FROM registros_periodicos")
            records_before = int(cur.fetchone()["total"])

            cur.executemany(
                """
                INSERT INTO jogadores (id, nickname_atual, state, mostrar, ativo)
                VALUES (%s, %s, %s, %s, TRUE)
                ON CONFLICT (id) DO UPDATE SET
                    nickname_atual = EXCLUDED.nickname_atual,
                    state = EXCLUDED.state,
                    mostrar = EXCLUDED.mostrar,
                    ativo = EXCLUDED.ativo,
                    updated_at = now()
                """,
                [
                    (
                        int(player["id_jogador"]),
                        player["nickname"],
                        player["state"],
                        str(player["mostrar"]).upper() == "YES",
                    )
                    for player in player_rows
                ],
            )
            report.jogadores_inseridos = len(player_rows)

            cur.executemany(
                """
                INSERT INTO jogador_nicknames (jogador_id, nickname)
                SELECT %s, %s
                WHERE NOT EXISTS (
                    SELECT 1 FROM jogador_nicknames
                    WHERE jogador_id = %s AND lower(nickname) = lower(%s)
                )
                """,
                [
                    (
                        int(player["id_jogador"]),
                        player["nickname"],
                        int(player["id_jogador"]),
                        player["nickname"],
                    )
                    for player in player_rows
                ],
            )

            cur.executemany(
                """
                INSERT INTO registros_periodicos (
                    jogador_id, periodo_tipo, data_referencia, catches, fonte, status
                )
                VALUES (%s, %s, %s, %s, 'importacao_excel', 'validado')
                ON CONFLICT (jogador_id, periodo_tipo, data_referencia) DO NOTHING
                """,
                [
                    (
                        int(record["id_jogador"]),
                        record["periodo_tipo"],
                        record["date"].date(),
                        int(record["catches"]),
                    )
                    for record in record_rows
                ],
            )

            cur.execute("SELECT COUNT(*) AS total FROM registros_periodicos")
            records_after = int(cur.fetchone()["total"])
            report.registros_inseridos = max(records_after - records_before, 0)
            report.registros_ignorados = max(len(record_rows) - report.registros_inseridos, 0)

            cur.execute(
                """
                SELECT setval(
                    pg_get_serial_sequence('jogadores', 'id'),
                    COALESCE((SELECT MAX(id) FROM jogadores), 1),
                    TRUE
                )
                """
            )

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        if owns_connection and context is not None:
            context.__exit__(None, None, None)

    return report
