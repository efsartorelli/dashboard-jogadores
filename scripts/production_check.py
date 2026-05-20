from __future__ import annotations

import re
import subprocess
import sys
import tomllib
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
    "security_events",
    "pagamentos",
    "payment_webhook_logs",
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

    expected_values = {
        "DATABASE_URL": "",
        "DATA_SOURCE": "database",
        "SUPABASE_URL": "",
        "SUPABASE_ANON_KEY": "",
        "FREE_MONTHLY_INPUT_LIMIT": "5",
        "PREMIUM_MONTHLY_INPUT_LIMIT": "50",
        "AUTH_SESSION_REFRESH_MARGIN_SECONDS": "120",
        "AUTH_SESSION_VALIDATE_INTERVAL_SECONDS": "300",
        "PAYMENT_PROVIDER": "manual",
        "PAYMENT_CHECKOUT_URL": "",
        "PAYMENT_WEBHOOK_SECRET": "",
        "PAYMENT_SUCCESS_URL": "",
        "PAYMENT_CANCEL_URL": "",
        "PREMIUM_PRICE_CENTS": "1990",
        "PREMIUM_CURRENCY": "BRL",
    }

    parsed: dict[str, str] = {}
    content = path.read_text(encoding="utf-8")
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            return False
        key, value = line.split("=", 1)
        parsed[key.strip()] = value.strip().strip('"').strip("'")

    if parsed != expected_values:
        return False

    suspicious_patterns = [
        r"postgres(?:ql)?://",
        r"https://[A-Za-z0-9.-]+\.supabase\.co",
        r"SUPABASE_(?:ANON|SERVICE_ROLE)_KEY=.+",
        r"PAYMENT_WEBHOOK_SECRET=.+",
        r"eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}",
    ]
    return not any(re.search(pattern, content) for pattern in suspicious_patterns)


def streamlit_secrets_example_is_safe() -> bool:
    path = ROOT_DIR / ".streamlit" / "secrets.toml.example"
    if not path.exists():
        return False

    expected_values = {
        "DATABASE_URL": "",
        "DATA_SOURCE": "database",
        "SUPABASE_URL": "",
        "SUPABASE_ANON_KEY": "",
        "FREE_MONTHLY_INPUT_LIMIT": "5",
        "PREMIUM_MONTHLY_INPUT_LIMIT": "50",
        "AUTH_SESSION_REFRESH_MARGIN_SECONDS": "120",
        "AUTH_SESSION_VALIDATE_INTERVAL_SECONDS": "300",
        "PAYMENT_PROVIDER": "manual",
        "PAYMENT_CHECKOUT_URL": "",
        "PAYMENT_WEBHOOK_SECRET": "",
        "PAYMENT_SUCCESS_URL": "",
        "PAYMENT_CANCEL_URL": "",
        "PREMIUM_PRICE_CENTS": "1990",
        "PREMIUM_CURRENCY": "BRL",
    }

    content = path.read_text(encoding="utf-8")
    try:
        parsed = tomllib.loads(content)
    except tomllib.TOMLDecodeError:
        return False

    normalized = {key: str(value).strip() for key, value in parsed.items()}
    if normalized != expected_values:
        return False

    suspicious_patterns = [
        r"postgres(?:ql)?://",
        r"https://[A-Za-z0-9.-]+\.supabase\.co",
        r"SUPABASE_(?:ANON|SERVICE_ROLE)_KEY\s*=\s*['\"]?[^'\"\s]+",
        r"PAYMENT_WEBHOOK_SECRET\s*=\s*['\"]?[^'\"\s]+",
        r"eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}",
    ]
    return not any(re.search(pattern, content) for pattern in suspicious_patterns)


def main() -> int:
    failures: list[str] = []

    data_source = (get_setting("DATA_SOURCE", "auto") or "auto").lower()
    supabase_url = get_setting("SUPABASE_URL")
    supabase_anon_key = get_setting("SUPABASE_ANON_KEY")
    payment_provider = (get_setting("PAYMENT_PROVIDER", "manual") or "manual").lower()
    payment_webhook_secret = get_setting("PAYMENT_WEBHOOK_SECRET")

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

    if supabase_url and supabase_anon_key:
        ok("Supabase Auth configurado")
    else:
        fail("SUPABASE_URL e SUPABASE_ANON_KEY sao obrigatorios para autenticacao.", failures)

    if payment_provider in {"manual", "cacto", "pagseguro", "stripe"}:
        ok(f"PAYMENT_PROVIDER configurado como {payment_provider}")
    else:
        fail("PAYMENT_PROVIDER deve ser manual, cacto, pagseguro ou stripe.", failures)

    if payment_provider != "manual" and not payment_webhook_secret:
        fail("PAYMENT_WEBHOOK_SECRET e obrigatorio para webhooks de pagamento em producao.", failures)

    if is_git_tracked(".env"):
        fail(".env esta versionado no Git. Remova antes do deploy.", failures)
    else:
        ok(".env nao esta versionado")

    if is_git_tracked(".streamlit/secrets.toml"):
        fail(".streamlit/secrets.toml esta versionado no Git. Remova antes do deploy.", failures)
    else:
        ok(".streamlit/secrets.toml nao esta versionado")

    if env_example_is_safe():
        ok(".env.example nao contem segredo real aparente")
    else:
        fail(".env.example ausente ou com conteudo sensivel/suspeito.", failures)

    if streamlit_secrets_example_is_safe():
        ok(".streamlit/secrets.toml.example nao contem segredo real aparente")
    else:
        fail(".streamlit/secrets.toml.example ausente ou com conteudo sensivel/suspeito.", failures)

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

                    cur.execute(
                        """
                        SELECT COUNT(*) AS count
                        FROM (
                            SELECT jogador_id, periodo_tipo, data_referencia
                            FROM registros_periodicos
                            WHERE status IN ('pendente', 'validado')
                            GROUP BY jogador_id, periodo_tipo, data_referencia
                            HAVING COUNT(*) > 1
                        ) duplicated
                        """
                    )
                    active_duplicates = int(cur.fetchone()["count"])

                    cur.execute(
                        """
                        SELECT 1
                        FROM pg_indexes
                        WHERE schemaname = 'public'
                          AND indexname = 'uq_registros_ativos_jogador_periodo_data'
                        """
                    )
                    has_partial_unique_index = cur.fetchone() is not None

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

            if active_duplicates == 0:
                ok("Sem duplicidade ativa por jogador/data/tipo")
            else:
                fail("Ha duplicidade ativa em registros pendentes/validados.", failures)

            if has_partial_unique_index:
                ok("Indice unico parcial de registros ativos encontrado")
            else:
                warn("Migration database/migrations/001_production_hardening.sql ainda nao aplicada.")
        except Exception:
            fail("Falha ao conectar ou consultar o banco. Verifique DATABASE_URL e schema.", failures)

    if failures:
        print(f"\nResultado: {len(failures)} problema(s) encontrado(s).")
        return 1

    print("\nResultado: production_check passou.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
