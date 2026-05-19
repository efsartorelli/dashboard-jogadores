import os
import unittest
from unittest.mock import patch

from src.data.loaders import load_excel_data
from src.database.repositories import carregar_dados_dashboard, verificar_duplicidade_registro
from src.metrics.rankings import build_general_ranking
from src.services.data_source import load_dashboard_data
from src.services.import_excel_to_db import normalize_player_rows, normalize_record_rows


class FakeCursor:
    def __init__(self, rows=None, row=None):
        self.rows = rows or []
        self.row = row
        self.executed = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params=()):
        self.executed.append((query, params))

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.row


class FakeConn:
    def __init__(self, rows=None, row=None):
        self.cursor_obj = FakeCursor(rows=rows, row=row)

    def cursor(self):
        return self.cursor_obj


class DatabaseLayerTest(unittest.TestCase):
    def test_duplicate_detection_uses_player_period_and_date(self):
        conn = FakeConn(row={"?column?": 1})
        exists = verificar_duplicidade_registro(conn, 10, "mensal", "2026-04-30")
        self.assertTrue(exists)

        query, params = conn.cursor_obj.executed[0]
        self.assertIn("jogador_id = %s", query)
        self.assertEqual(params, (10, "mensal", "2026-04-30", "validado"))

    def test_auto_falls_back_to_excel_without_database_url(self):
        with patch.dict(os.environ, {}, clear=True):
            result = load_dashboard_data("auto")

        self.assertEqual(result.source, "excel")
        self.assertFalse(result.data.empty)
        self.assertEqual(result.data["id_jogador"].nunique(), 179)

    def test_import_normalization_avoids_duplicates(self):
        df = load_excel_data()
        players = normalize_player_rows(df)
        records = normalize_record_rows(df)

        self.assertEqual(len(players), 179)
        self.assertEqual(len(records), 2036)
        self.assertEqual(len({row["id_jogador"] for row in players}), 179)
        self.assertEqual(
            len({(row["id_jogador"], row["periodo_tipo"], row["date"]) for row in records}),
            2036,
        )

    def test_metrics_match_when_data_comes_from_database_shape(self):
        excel_df = load_excel_data().sort_values(["nickname", "date"]).reset_index(drop=True)
        rows = [
            {
                "id": index + 1,
                "jogador_id": int(row.id_jogador),
                "nickname": row.nickname,
                "state": row.state,
                "periodo_tipo": "mensal",
                "data_referencia": row.date.date(),
                "catches": int(row.catches),
                "status": "validado",
            }
            for index, row in excel_df.iterrows()
        ]

        db_df = carregar_dados_dashboard(FakeConn(rows=rows))
        excel_ranking = build_general_ranking(excel_df).head(10).reset_index(drop=True)
        db_ranking = build_general_ranking(db_df).head(10).reset_index(drop=True)

        self.assertTrue(excel_ranking.equals(db_ranking))


if __name__ == "__main__":
    unittest.main()
