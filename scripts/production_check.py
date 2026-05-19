from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.config import get_setting
from src.database.connection import get_connection, has_database_config


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


def ok(message: str) -> None:
    print(f"OK: {message}")


def fail(message: str, failures: list[str]) -> None:
    print(f"ERRO: {message}")
    failures.append(message)


def warn(message: str) -> None:
    print(f"AVISO: {message}")


def is_git_tracked(path: str) -> bool:
    try:
        result = subprocess.run(
            ["git", "ls-files", "--error-unmatch", path],
            cwd=ROOT_DIR,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return result.returncode == 0
    except Exception:
        return False


def env_example_is_safe() -> bool:
    path = ROOT_DIR / ".env.example"
    if not path.exists():
        return False

    content = path.read_text(encoding="utf-8")
    if "SUA_SENHA" not in content or "seu-projeto" not in content:
        return False

    suspicious_patterns = [
        r"postgresql://postgres:[^@\s]*(?:%|[A-Za-z0-9]{12,})@db\.",
        r"ADMIN_PASSWORD=(?!SUA_SENHA_ADMIN_FORTE).{12,}",
    ]
    return not any(re.search(pattern, content) for pattern in suspicious_patterns)


def main() -> int:
    failures: list[str] = []

    data_source = (get_setting("DATA_SOURCE", "auto") or "auto").lower()
    enable_admin = (get_setting("ENABLE_ADMIN", "false") or "false").lower()
    admin_password = get_setting("ADMIN_PASSWORD")

    if data_source in {"database", "auto", "excel"}:
        ok(f"DATA_SOURCE configurado como {data_source}")
    else:
        fail("DATA_SOURCE deve ser excel, database ou auto.", failures)

    if data_source == "database" and not has_database_config():
        fail("DATABASE_URL e obrigatorio quando DATA_SOURCE=database.", failures)
    elif has_database_config():
        ok("DATABASE_URL configurado")
    else:
        warn("DATABASE_URL ausente; o app so podera usar Excel/auto fallback.")

    if enable_admin in {"true", "false"}:
        ok(f"ENABLE_ADMIN configurado como {enable_admin}")
    else:
        fail("ENABLE_ADMIN deve ser true ou false.", failures)

    if enable_admin == "true" and not admin_password:
        fail("ADMIN_PASSWORD e obrigatorio quando ENABLE_ADMIN=true.", failures)
    elif enable_admin == "true":
        ok("ADMIN_PASSWORD configurado")

    if is_git_tracked(".env"):
        fail(".env esta versionado no Git. Remova antes do deploy.", failures)
    else:
        ok(".env nao esta versionado")

    if env_example_is_safe():
        ok(".env.example nao contem segredo real aparente")
    else:
        fail(".env.example ausente ou com conteudo sensivel/suspeito.", failures)

    if has_database_config():
        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
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

                    cur.execute("SELECT COUNT(*) AS count FROM jogadores")
                    players = int(cur.fetchone()["count"])

                    cur.execute("SELECT COUNT(*) AS count FROM registros_periodicos")
                    records = int(cur.fetchone()["count"])

                    cur.execute(
                        """
                        SELECT COUNT(*) AS count
                        FROM registros_periodicos
                        WHERE status = 'validado'
                        """
                    )
                    validated = int(cur.fetchone()["count"])

            missing_tables = sorted(set(MAIN_TABLES) - set(found_tables))
            if missing_tables:
                fail("Tabelas ausentes: " + ", ".join(missing_tables), failures)
            else:
                ok("Todas as tabelas principais existem")

            if players > 0:
                ok(f"Jogadores cadastrados: {players}")
            else:
                fail("Nenhum jogador encontrado no banco.", failures)

            if records > 0:
                ok(f"Registros cadastrados: {records}")
            else:
                fail("Nenhum registro encontrado no banco.", failures)

            if validated > 0:
                ok(f"Registros validados: {validated}")
            else:
                fail("Nao existe registro validado para alimentar o dashboard.", failures)
        except Exception:
            fail("Falha ao conectar ou consultar o banco. Verifique DATABASE_URL e schema.", failures)

    if failures:
        print(f"\nResultado: {len(failures)} problema(s) encontrado(s).")
        return 1

    print("\nResultado: production_check passou.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
