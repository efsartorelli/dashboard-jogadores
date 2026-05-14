import pandas as pd


def load_data():
    file_path = "data/nofullautoinsidebuildings.xlsx"

    dim = pd.read_excel(
        file_path,
        sheet_name="DIM_JOGADORES",
        usecols=["NICKNAME", "ID_JOGADOR", "STATE", "MOSTRAR"],
    )
    fact = pd.read_excel(
        file_path,
        sheet_name="FATO_MENSAL",
        usecols=["NICKNAME", "DATE", "CATCHES"],
    )

    # padronizar colunas
    dim.columns = dim.columns.str.strip().str.lower()
    fact.columns = fact.columns.str.strip().str.lower()

    # limpar texto
    dim["nickname"] = dim["nickname"].str.strip()
    fact["nickname"] = fact["nickname"].str.strip()

    # aplicar regra MOSTRAR
    dim["mostrar"] = dim["mostrar"].str.upper().str.strip()
    dim = dim[dim["mostrar"] == "YES"]

    # join pelo nickname
    df = fact.merge(dim, on="nickname", how="inner")

    # data
    df["date"] = pd.to_datetime(df["date"])

    # pegar nickname mais recente por ID
    latest_names = (
        df.sort_values("date")
        .groupby("id_jogador", as_index=False)["nickname"]
        .last()
        .rename(columns={"nickname": "nickname_latest"})
    )

    df = df.merge(latest_names, on="id_jogador", how="left")

    # usar nome mais recente
    df["nickname"] = df["nickname_latest"]

    return df.drop(columns=["nickname_latest"])
