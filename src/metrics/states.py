import numpy as np
import pandas as pd


STATE_COLUMNS = [
    "Estado",
    "Posição",
    "Jogadores",
    "Representatividade",
    "Total",
    "Média",
    "Melhor jogador",
    "Valor melhor jogador",
    "Posição média",
]


def build_state_stats(
    base: pd.DataFrame,
    order_by: str = "Total capturas",
    ranking_base: pd.DataFrame | None = None,
) -> pd.DataFrame:
    if base.empty:
        return pd.DataFrame(columns=STATE_COLUMNS)

    ranking_source = ranking_base if ranking_base is not None and not ranking_base.empty else base
    ranked_positions = (
        ranking_source.sort_values(["catches", "nickname"], ascending=[False, True])
        .reset_index(drop=True)
        .copy()
    )
    ranked_positions["ranking_position"] = np.arange(1, len(ranked_positions) + 1)
    total_players = max(int(ranked_positions["id_jogador"].nunique()), 1)
    ranked_base = base.merge(
        ranked_positions[["id_jogador", "ranking_position"]].drop_duplicates("id_jogador"),
        on="id_jogador",
        how="left",
    )

    rows = []
    for state, group in ranked_base.groupby("state", dropna=True):
        total = group["catches"].sum()
        best = group.sort_values("catches", ascending=False).iloc[0]
        player_count = group["id_jogador"].nunique()
        average_position = group["ranking_position"].dropna().mean()
        rows.append({
            "Estado": state,
            "Jogadores": player_count,
            "Representatividade": (player_count / total_players) * 100,
            "Total": total,
            "Média": int(group["catches"].mean()),
            "Melhor jogador": best["nickname"],
            "Valor melhor jogador": best["catches"],
            "Posição média": 0 if pd.isna(average_position) else int(np.floor(average_position + 0.5)),
        })

    sort_columns = {
        "Total capturas": "Total",
        "Nº de jogadores": "Jogadores",
        "Média": "Média",
    }
    sort_column = sort_columns.get(order_by, "Total")

    stats = (
        pd.DataFrame(rows)
        .sort_values([sort_column, "Estado"], ascending=[False, True])
        .reset_index(drop=True)
    )
    stats["Posição"] = np.arange(1, len(stats) + 1)
    return stats
