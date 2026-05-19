import numpy as np
import pandas as pd

from src.metrics.formatting import format_int


BEST_CATCHES_COLUMNS = ["id_jogador", "nickname", "state", "catches", "date", "position"]
GENERAL_RANKING_COLUMNS = ["#", "Jogador", "Estado", "Capturas", "Dias ativo"]


def get_best_catches(data: pd.DataFrame) -> pd.DataFrame:
    """Return one row per player using the highest registered catch total."""
    if data.empty:
        return pd.DataFrame(columns=BEST_CATCHES_COLUMNS)

    idx = data.groupby("id_jogador")["catches"].idxmax()
    base = data.loc[idx, ["id_jogador", "nickname", "state", "catches", "date"]].copy()
    base = base.sort_values("catches", ascending=False).reset_index(drop=True)
    base["position"] = np.arange(1, len(base) + 1)
    return base


def build_general_ranking(data: pd.DataFrame) -> pd.DataFrame:
    if data.empty:
        return pd.DataFrame(columns=GENERAL_RANKING_COLUMNS)

    idx = data.groupby("id_jogador")["catches"].idxmax()
    ranking = (
        data.loc[idx, ["id_jogador", "nickname", "state", "catches"]]
        .sort_values("catches", ascending=False)
        .reset_index(drop=True)
    )
    active_days = data.groupby("id_jogador")["date"].agg(lambda x: max((x.max() - x.min()).days, 1)).to_dict()
    ranking["#"] = np.arange(1, len(ranking) + 1)
    ranking["Jogador"] = ranking["nickname"]
    ranking["Estado"] = ranking["state"]
    ranking["Capturas"] = ranking["catches"].map(format_int)
    ranking["Dias ativo"] = ranking["id_jogador"].map(active_days).fillna(0).astype(int)
    return ranking[GENERAL_RANKING_COLUMNS]
