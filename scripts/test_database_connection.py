from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

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


def mask_database_url(url: str) -> str:
    try:
        parts = urlsplit(url)
        host = parts.hostname or "host"
        port = f":{parts.port}" if parts.port else ""
        netloc = f"***:***@{host}{port}" if parts.username else f"{host}{port}"
        return urlunsplit((parts.scheme, netloc, parts.path, "", ""))
    except Exception:
        return "<DATABASE_URL mascarada>"


def sanitize_error(error: Exception, database_url: str) -> str:
    message = str(error)
    if database_url:
        message = message.replace(database_url, "<DATABASE_URL>")
        message = message.replace(mask_database_url(database_url), "<DATABASE_URL>")
        if "@" in database_url:
            userinfo = database_url.split("//", 1)[-1].split("@", 1)[0]
            message = message.replace(userinfo, "***:***")
            if ":" in userinfo:
                password = userinfo.split(":", 1)[1]
                message = message.replace(password, "<PASSWORD>")
    return message


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
        print(f"Detalhe: {sanitize_error(exc, database_url)}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
