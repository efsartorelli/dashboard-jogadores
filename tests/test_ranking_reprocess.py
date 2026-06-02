import unittest
from datetime import date
from unittest.mock import patch

from src.services.ranking_reprocess import reprocess_current_ranking


class FakeCursor:
    def __init__(self, rows):
        self.rows = list(rows)
        self.executed = []
        self.rowcount = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params=()):
        self.executed.append((query, params))
        if "INSERT INTO ranking_itens" in query:
            self.rowcount = 2

    def fetchone(self):
        return self.rows.pop(0)


class FakeConn:
    def __init__(self, rows):
        self.cursor_obj = FakeCursor(rows)
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class RankingReprocessTest(unittest.TestCase):
    def test_reprocess_creates_snapshot_and_items_by_player_id(self):
        conn = FakeConn([
            {
                "total_jogadores": 2,
                "data_base": date(2026, 6, 1),
                "primeira_data": date(2026, 5, 1),
                "maior_valor": 2_500_000,
            },
            {"id": 99},
        ])

        with patch(
            "src.services.ranking_reprocess.buscar_usuario_por_id",
            return_value={"role": "moderador"},
        ):
            result = reprocess_current_ranking("00000000-0000-0000-0000-000000000001", conn=conn)

        self.assertTrue(result["success"])
        self.assertEqual(result["snapshot_id"], 99)
        self.assertEqual(result["itens_criados"], 2)
        self.assertEqual(conn.commits, 1)
        executed_sql = "\n".join(query for query, _params in conn.cursor_obj.executed)
        self.assertIn("DISTINCT ON (r.jogador_id)", executed_sql)
        self.assertIn("INSERT INTO rankings_snapshot", executed_sql)
        self.assertIn("INSERT INTO ranking_itens", executed_sql)
        self.assertIn("jogador_id", executed_sql)

    def test_reprocess_requires_admin_or_moderator(self):
        conn = FakeConn([])

        with patch(
            "src.services.ranking_reprocess.buscar_usuario_por_id",
            return_value={"role": "jogador"},
        ):
            result = reprocess_current_ranking("00000000-0000-0000-0000-000000000001", conn=conn)

        self.assertFalse(result["success"])
        self.assertEqual(conn.commits, 0)
        self.assertEqual(conn.rollbacks, 0)


if __name__ == "__main__":
    unittest.main()
