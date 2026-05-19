from __future__ import annotations

import os
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.security import sanitize_error_message

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None


if load_dotenv is not None:
    load_dotenv(ROOT_DIR / ".env")

env_path = ROOT_DIR / ".env"
if env_path.exists():
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if not line or line.strip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip().lstrip("\ufeff"), value.strip().strip('"').strip("'"))


MAIN_TABLES = [
    "usuarios",
    "jogadores",
    "jogador_nicknames",
    "registros_periodicos",
    "rankings_snapshot",
    "ranking_itens",
    "categorias",
    "historico_processamentos",
    "auditoria_registros",
]


def main() -> int:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("ERRO: DATABASE_URL nao encontrada. Configure o arquivo .env.")
        return 1

    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:
        print("ERRO: driver psycopg nao instalado. Rode: pip install -r requirements.txt")
        print(f"Detalhe: {exc}")
        return 1

    try:
        with psycopg.connect(database_url, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT current_database() AS database_name")
                database_name = cur.fetchone()["database_name"]

                cur.execute(
                    """
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_schema = 'public'
                      AND table_name = ANY(%s)
                    ORDER BY table_name
                    """,
                    (MAIN_TABLES,),
                )
                found_tables = [row["table_name"] for row in cur.fetchall()]

        missing_tables = sorted(set(MAIN_TABLES) - set(found_tables))
        print("SUCESSO: conexao com PostgreSQL/Supabase aberta.")
        print(f"Banco conectado: {database_name}")
        print(f"Tabelas principais encontradas: {len(found_tables)}/{len(MAIN_TABLES)}")
        if found_tables:
            print("Encontradas: " + ", ".join(found_tables))
        if missing_tables:
            print("Ausentes: " + ", ".join(missing_tables))
            print("Observacao: execute database/schema.sql se as tabelas ainda nao existem.")
        return 0
    except Exception as exc:
        print("ERRO: nao foi possivel conectar ao PostgreSQL/Supabase.")
        print(f"Detalhe: {sanitize_error_message(exc, [database_url])}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
