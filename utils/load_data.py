import pandas as pd

def load_data():
    file_path = "data/nofullautoinsidebuildings.xlsx"

<<<<<<< HEAD
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
=======
    dim = pd.read_excel(file_path, sheet_name="DIM_JOGADORES")
    fact = pd.read_excel(file_path, sheet_name="FATO_MENSAL")
>>>>>>> 8de7978d80c81cd9934320adbf1ebd3395b7fa29

    # padronizar colunas
    dim.columns = dim.columns.str.strip().str.lower()
    fact.columns = fact.columns.str.strip().str.lower()

    # limpar texto
    dim["nickname"] = dim["nickname"].str.strip()
    fact["nickname"] = fact["nickname"].str.strip()

    # ✅ aplicar regra MOSTRAR
    dim["mostrar"] = dim["mostrar"].str.upper().str.strip()
    dim = dim[dim["mostrar"] == "YES"]

    # ✅ JOIN PELO NICKNAME (IMPORTANTE)
    df = fact.merge(dim, on="nickname", how="inner")

    # data
    df["date"] = pd.to_datetime(df["date"])

    # ✅ pegar nickname mais recente por ID
    latest_names = (
        df.sort_values("date")
<<<<<<< HEAD
        .groupby("id_jogador", as_index=False)["nickname"]
        .last()
        .rename(columns={"nickname": "nickname_latest"})
    )

    df = df.merge(latest_names, on="id_jogador", how="left")
=======
        .groupby("id_jogador")["nickname"]
        .last()
        .reset_index()
    )

    df = df.merge(latest_names, on="id_jogador", suffixes=("", "_latest"))
>>>>>>> 8de7978d80c81cd9934320adbf1ebd3395b7fa29

    # usar nome mais recente
    df["nickname"] = df["nickname_latest"]

<<<<<<< HEAD
    return df.drop(columns=["nickname_latest"])
=======
    return df
>>>>>>> 8de7978d80c81cd9934320adbf1ebd3395b7fa29
