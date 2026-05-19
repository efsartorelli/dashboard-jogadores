from dataclasses import dataclass

import pandas as pd

from src.config import DATA_SOURCE, DEFAULT_EXCEL_PATH
from src.data.loaders import data_file_fingerprint, load_excel_data
from src.database.connection import check_database, get_connection, has_database_config
from src.database.repositories import carregar_dados_dashboard


@dataclass(frozen=True)
class DataSourceResult:
    data: pd.DataFrame
    source: str
    message: str | None = None


def normalize_data_source(value: str | None = None) -> str:
    source = (value or DATA_SOURCE or "auto").strip().lower()
    if source not in {"auto", "excel", "database"}:
        return "auto"
    return source


def get_database_fingerprint():
    if not has_database_config():
        return ("database", False)

    ok, _ = check_database()
    if not ok:
        return ("database", True, "unavailable")

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    COUNT(*) AS registros,
                    COALESCE(MAX(updated_at), 'epoch'::timestamptz) AS max_registro_updated_at,
                    COALESCE(MAX(data_referencia), 'epoch'::date) AS max_data_referencia
                FROM registros_periodicos
                """
            )
            registros = cur.fetchone()
            cur.execute(
                """
                SELECT
                    COUNT(*) AS jogadores,
                    COALESCE(MAX(updated_at), 'epoch'::timestamptz) AS max_jogador_updated_at
                FROM jogadores
                """
            )
            jogadores = cur.fetchone()

    return (
        "database",
        True,
        int(jogadores["jogadores"]),
        str(jogadores["max_jogador_updated_at"]),
        int(registros["registros"]),
        str(registros["max_registro_updated_at"]),
        str(registros["max_data_referencia"]),
    )


def get_data_source_fingerprint(source: str | None = None):
    selected = normalize_data_source(source)
    if selected == "excel":
        return ("excel", data_file_fingerprint(DEFAULT_EXCEL_PATH))
    if selected == "database":
        return get_database_fingerprint()
    return ("auto", get_database_fingerprint(), data_file_fingerprint(DEFAULT_EXCEL_PATH))


def load_dashboard_data(source: str | None = None) -> DataSourceResult:
    selected = normalize_data_source(source)

    if selected in {"database", "auto"} and has_database_config():
        ok, error = check_database()
        if ok:
            with get_connection() as conn:
                data = carregar_dados_dashboard(conn)
            if not data.empty:
                return DataSourceResult(
                    data=data.sort_values(["nickname", "date"]).reset_index(drop=True),
                    source="database",
                )
            if selected == "database":
                return DataSourceResult(data=data, source="database", message="Banco conectado, mas sem registros.")
        elif selected == "database":
            raise RuntimeError("Banco de dados indisponivel.")

    data = load_excel_data(DEFAULT_EXCEL_PATH).sort_values(["nickname", "date"]).reset_index(drop=True)
    return DataSourceResult(data=data, source="excel", message="Usando Excel legado.")
