from __future__ import annotations

import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.database.connection import get_connection, get_database_url
from src.database.repositories import carregar_dados_dashboard
from src.security import sanitize_error_message


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


def scalar(cur, query, params=()):
    cur.execute(query, params)
    row = cur.fetchone()
    return next(iter(row.values())) if row else None


def print_rows(title: str, rows: list[dict]):
    print(f"\n{title}")
    if not rows:
        print("  nenhum registro")
        return
    for row in rows:
        print("  " + " | ".join(f"{key}={value}" for key, value in row.items()))


def main() -> int:
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                print("DEBUG BANCO: conexao aberta.")
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
                tables = [row["table_name"] for row in cur.fetchall()]
                print(f"Tabelas principais encontradas: {len(tables)}/{len(MAIN_TABLES)}")
                print("Tabelas: " + (", ".join(tables) if tables else "nenhuma"))

                print(f"Jogadores total: {scalar(cur, 'SELECT COUNT(*) FROM jogadores')}")
                print(
                    "Jogadores visiveis: "
                    f"{scalar(cur, 'SELECT COUNT(*) FROM jogadores WHERE mostrar = TRUE AND ativo = TRUE')}"
                )
                print(f"Registros total: {scalar(cur, 'SELECT COUNT(*) FROM registros_periodicos')}")
                registros_validado = scalar(
                    cur,
                    "SELECT COUNT(*) FROM registros_periodicos WHERE status = 'validado'",
                )
                print(f"Registros validado: {registros_validado}")
                print(
                    "Registros com capturas > 0: "
                    f"{scalar(cur, 'SELECT COUNT(*) FROM registros_periodicos WHERE catches > 0')}"
                )

                cur.execute(
                    """
                    SELECT id, nickname_atual, state, mostrar, ativo
                    FROM jogadores
                    ORDER BY id
                    LIMIT 5
                    """
                )
                print_rows("5 jogadores:", cur.fetchall())

                cur.execute(
                    """
                    SELECT id, jogador_id, periodo_tipo, data_referencia, catches, status
                    FROM registros_periodicos
                    ORDER BY data_referencia, jogador_id
                    LIMIT 5
                    """
                )
                print_rows("5 registros:", cur.fetchall())

                cur.execute(
                    """
                    SELECT
                        MIN(data_referencia) AS min_data,
                        MAX(data_referencia) AS max_data,
                        MIN(catches) AS min_catches,
                        MAX(catches) AS max_catches
                    FROM registros_periodicos
                    """
                )
                print_rows("Datas e capturas:", cur.fetchall())

                cur.execute(
                    """
                    SELECT periodo_tipo, status, COUNT(*) AS quantidade
                    FROM registros_periodicos
                    GROUP BY periodo_tipo, status
                    ORDER BY periodo_tipo, status
                    """
                )
                print_rows("Registros por periodo/status:", cur.fetchall())

                cur.execute(
                    """
                    SELECT nome, tipo, min_catches, max_catches, ativo
                    FROM categorias
                    ORDER BY min_catches
                    """
                )
                print_rows("Categorias:", cur.fetchall())

            df = carregar_dados_dashboard(conn)
            print("\nDataFrame do dashboard:")
            print(f"  linhas={len(df)}")
            print(f"  colunas={list(df.columns)}")
            if not df.empty:
                print(f"  ids={df['id_jogador'].nunique()}")
                print(f"  datas={df['date'].min()} -> {df['date'].max()}")
                print(f"  catches_min={int(df['catches'].min())}")
                print(f"  catches_max={int(df['catches'].max())}")
        return 0
    except Exception as exc:
        print("ERRO DEBUG BANCO: falha ao consultar dados.")
        print(f"Detalhe: {sanitize_error_message(exc, [get_database_url()])}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
