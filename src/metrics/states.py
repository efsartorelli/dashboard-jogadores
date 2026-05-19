import numpy as np
import pandas as pd


STATE_COLUMNS = ["Estado", "Posição", "Jogadores", "Total", "Média", "Melhor jogador", "Valor melhor jogador"]


def build_state_stats(base: pd.DataFrame, order_by: str = "Total capturas") -> pd.DataFrame:
    if base.empty:
        return pd.DataFrame(columns=STATE_COLUMNS)

    rows = []
    for state, group in base.groupby("state", dropna=True):
        total = group["catches"].sum()
        best = group.sort_values("catches", ascending=False).iloc[0]
        rows.append({
            "Estado": state,
            "Jogadores": group["id_jogador"].nunique(),
            "Total": total,
            "Média": int(group["catches"].mean()),
            "Melhor jogador": best["nickname"],
            "Valor melhor jogador": best["catches"],
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
