import numpy as np
import pandas as pd

from src.metrics.formatting import format_int


AVERAGE_COLUMNS = ["nickname", "state", "media", "data_inicial", "data_final", "dias", "catches_periodo"]
AVERAGE_RANKING_COLUMNS = ["#", "Jogador", "Estado", "Média", "Período", "Dias"]


def calculate_daily_averages(data: pd.DataFrame, apenas_mensais: bool) -> pd.DataFrame:
    """Calculate positive daily gains for every valid date pair per player.

    This preserves the current business rule exactly. It is intentionally kept as
    a pure function so it can later move to a background job or database-backed
    precomputation without changing the dashboard contract.
    """
    frames = []

    for _, group in data.groupby("id_jogador", sort=False):
        group = group.sort_values("date").reset_index(drop=True)
        size = len(group)

        if size < 2:
            continue

        starts, ends = np.triu_indices(size, k=1)
        dates = group["date"].to_numpy()
        catches = group["catches"].to_numpy()

        dias = ((dates[ends] - dates[starts]) / np.timedelta64(1, "D")).astype(int)
        ganho = catches[ends] - catches[starts]

        mask = (dias > 0) & (ganho > 0)
        if apenas_mensais:
            mask &= dias <= 32

        if not mask.any():
            continue

        starts = starts[mask]
        ends = ends[mask]
        dias = dias[mask]
        ganho = ganho[mask]

        frames.append(pd.DataFrame({
            "nickname": group["nickname"].iloc[-1],
            "state": group["state"].iloc[0],
            "media": (ganho / dias).astype(int),
            "data_inicial": pd.Series(dates[starts]).dt.date,
            "data_final": pd.Series(dates[ends]).dt.date,
            "dias": dias,
            "catches_periodo": ganho,
        }))

    if not frames:
        return pd.DataFrame(columns=AVERAGE_COLUMNS)

    return pd.concat(frames, ignore_index=True)


def build_average_ranking(data: pd.DataFrame, somente_melhor: bool, apenas_mensais: bool) -> pd.DataFrame:
    df_media = calculate_daily_averages(data, apenas_mensais)

    if df_media.empty:
        return pd.DataFrame(columns=AVERAGE_RANKING_COLUMNS)

    if somente_melhor:
        df_media = df_media.sort_values("media", ascending=False).groupby("nickname").head(1)

    df_media = df_media.sort_values("media", ascending=False).reset_index(drop=True)
    df_media["#"] = np.arange(1, len(df_media) + 1)
    df_media["Jogador"] = df_media["nickname"]
    df_media["Estado"] = df_media["state"]
    df_media["Média"] = df_media["media"].map(format_int)
    df_media["Período"] = df_media["data_inicial"].astype(str) + " - " + df_media["data_final"].astype(str)
    df_media["Dias"] = df_media["dias"]
    return df_media[AVERAGE_RANKING_COLUMNS]
