import io
import unittest

import pandas as pd

from src.services.monthly_imports import (
    ExistingPlayer,
    build_import_preview,
    normalize_nickname_key,
    read_monthly_import_rows,
)


class MonthlyImportPreviewTest(unittest.TestCase):
    def test_normalized_nickname_links_existing_player(self):
        players = [
            ExistingPlayer(
                id=123,
                nickname="Makaytso",
                state="SP",
                nickname_key=normalize_nickname_key("makaytso"),
                alias_keys={normalize_nickname_key("makaytso")},
            )
        ]
        rows = [
            {"linha_numero": 2, "nickname": "Makaytso", "estado": "SP", "capturas": "2.500.000"},
            {"linha_numero": 3, "nickname": "JoaoGO", "estado": "RJ", "capturas": "800.000"},
        ]

        preview = build_import_preview(rows, players, {123: 2_300_000}, {})

        self.assertEqual(preview[0].status, "Jogador existente")
        self.assertEqual(preview[0].player_id, 123)
        self.assertEqual(preview[0].diferenca, 200_000)
        self.assertTrue(preview[0].can_import)
        self.assertEqual(preview[1].status, "Novo jogador")
        self.assertIsNone(preview[1].player_id)
        self.assertTrue(preview[1].can_import)

    def test_spaces_case_and_accents_are_ignored_for_exact_match(self):
        players = [
            ExistingPlayer(
                id=10,
                nickname="Enzo  Makaytso",
                state="SP",
                nickname_key=normalize_nickname_key("Enzo  Makaytso"),
                alias_keys={normalize_nickname_key("Enzo  Makaytso")},
            )
        ]
        rows = [{"linha_numero": 2, "nickname": " enzo makaytso ", "estado": "SP", "capturas": 1_000_000}]

        preview = build_import_preview(rows, players, {10: 900_000}, {})

        self.assertEqual(preview[0].status, "Jogador existente")
        self.assertEqual(preview[0].player_id, 10)
        self.assertTrue(preview[0].can_import)

    def test_similar_nickname_is_review_instead_of_new_player(self):
        players = [
            ExistingPlayer(
                id=123,
                nickname="Makaytso",
                state="SP",
                nickname_key=normalize_nickname_key("Makaytso"),
                alias_keys={normalize_nickname_key("Makaytso")},
            )
        ]
        rows = [{"linha_numero": 2, "nickname": "Makay tso", "estado": "SP", "capturas": 2_500_000}]

        preview = build_import_preview(rows, players, {123: 2_300_000}, {})

        self.assertEqual(preview[0].status, "Possivel duplicado")
        self.assertEqual(preview[0].player_id, 123)
        self.assertFalse(preview[0].can_import)

    def test_existing_player_blocks_lower_value_and_duplicate_snapshot(self):
        players = [
            ExistingPlayer(
                id=123,
                nickname="Makaytso",
                state="SP",
                nickname_key=normalize_nickname_key("Makaytso"),
                alias_keys={normalize_nickname_key("Makaytso")},
            )
        ]
        rows = [{"linha_numero": 2, "nickname": "Makaytso", "estado": "SP", "capturas": 2_000_000}]

        preview = build_import_preview(rows, players, {123: 2_300_000}, {123: 55})

        self.assertEqual(preview[0].status, "Erro")
        self.assertFalse(preview[0].can_import)
        self.assertTrue(any("menores" in error for error in preview[0].erros))
        self.assertTrue(any("snapshot" in error for error in preview[0].erros))

    def test_existing_foreign_player_accepts_saved_foreign_code(self):
        players = [
            ExistingPlayer(
                id=1,
                nickname="Angelatini",
                state="ENG",
                nickname_key=normalize_nickname_key("Angelatini"),
                alias_keys={normalize_nickname_key("Angelatini")},
            ),
            ExistingPlayer(
                id=144,
                nickname="GihLucca",
                state="COI",
                nickname_key=normalize_nickname_key("GihLucca"),
                alias_keys={normalize_nickname_key("GihLucca")},
            ),
        ]
        rows = [
            {"linha_numero": 2, "nickname": "Angelatini", "estado": "ENG", "capturas": 3_153_387},
            {"linha_numero": 3, "nickname": "GihLucca", "estado": "COI", "capturas": 466_670},
        ]

        preview = build_import_preview(rows, players, {1: 3_071_000, 144: 465_000}, {})

        self.assertEqual(preview[0].status, "Alerta")
        self.assertTrue(preview[0].can_import)
        self.assertEqual(preview[0].estado_xlsx, "ENG")
        self.assertEqual(preview[1].status, "Alerta")
        self.assertTrue(preview[1].can_import)
        self.assertEqual(preview[1].estado_xlsx, "COI")

    def test_reader_accepts_required_xlsx_columns(self):
        buffer = io.BytesIO()
        pd.DataFrame({
            "Nickname": ["Makaytso"],
            "Estado": ["SP"],
            "Capturas": ["2.500.000"],
        }).to_excel(buffer, index=False)

        rows, file_hash = read_monthly_import_rows(buffer.getvalue())

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["nickname"], "Makaytso")
        self.assertEqual(rows[0]["estado"], "SP")
        self.assertEqual(rows[0]["capturas"], "2.500.000")
        self.assertEqual(len(file_hash), 64)


if __name__ == "__main__":
    unittest.main()
