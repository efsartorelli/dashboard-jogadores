import unittest

from src.data.loaders import load_excel_data
from src.metrics.averages import build_average_ranking, calculate_daily_averages
from src.metrics.distribution import build_distribution
from src.metrics.rankings import build_general_ranking, get_best_catches
from src.metrics.states import build_state_stats


class MetricsRegressionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.df = load_excel_data().sort_values(["nickname", "date"]).reset_index(drop=True)
        cls.base = get_best_catches(cls.df)

    def test_loaded_data_shape_and_top_player(self):
        self.assertEqual(self.df.shape, (2036, 6))
        self.assertEqual(self.df["id_jogador"].nunique(), 179)
        self.assertEqual(self.base.iloc[0]["nickname"], "Angelatini")
        self.assertEqual(int(self.base.iloc[0]["catches"]), 3_071_000)

    def test_general_ranking_preserves_current_contract(self):
        ranking = build_general_ranking(self.df)
        self.assertEqual(list(ranking.columns), ["#", "Jogador", "Estado", "Capturas", "Dias ativo"])
        self.assertEqual(ranking.iloc[0]["Jogador"], "Angelatini")
        self.assertEqual(ranking.iloc[0]["Capturas"], "3.071.000")

    def test_average_ranking_preserves_current_contract(self):
        all_averages = calculate_daily_averages(self.df, apenas_mensais=False)
        monthly_averages = calculate_daily_averages(self.df, apenas_mensais=True)
        self.assertEqual(all_averages.shape[0], 12659)
        self.assertEqual(monthly_averages.shape[0], 1096)

        ranking = build_average_ranking(self.df, somente_melhor=False, apenas_mensais=True)
        self.assertEqual(ranking.iloc[0]["Jogador"], "Kendo4687")
        self.assertEqual(ranking.iloc[0]["Média"], "3.240")

    def test_state_stats_and_distribution(self):
        stats = build_state_stats(self.base)
        sp = stats[stats["Estado"] == "SP"].iloc[0]
        self.assertEqual(int(sp["Jogadores"]), 118)
        self.assertEqual(int(sp["Total"]), 80_857_436)
        expected_share = 118 / self.base["id_jogador"].nunique() * 100
        self.assertAlmostEqual(float(sp["Representatividade"]), expected_share, places=1)
        self.assertGreater(int(sp["Posição média"]), 0)
        sp_only = build_state_stats(self.base[self.base["state"] == "SP"], ranking_base=self.base).iloc[0]
        self.assertAlmostEqual(float(sp_only["Representatividade"]), expected_share, places=1)
        self.assertEqual(int(sp_only["Posição média"]), int(sp["Posição média"]))

        distribution = build_distribution(self.base)
        self.assertEqual(distribution.set_index("Faixa").loc["1M+", "Jogadores"], 15)
        self.assertEqual(distribution.set_index("Faixa").loc["2M+", "Jogadores"], 3)


if __name__ == "__main__":
    unittest.main()
