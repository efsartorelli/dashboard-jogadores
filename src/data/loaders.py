from pathlib import Path

import pandas as pd

from src.config import DEFAULT_EXCEL_PATH


DIM_COLUMNS = ["NICKNAME", "ID_JOGADOR", "STATE", "MOSTRAR"]
FACT_COLUMNS = ["NICKNAME", "DATE", "CATCHES"]


def load_excel_data(file_path: str | Path = DEFAULT_EXCEL_PATH) -> pd.DataFrame:
    """Load the legacy Excel file and normalize it to the app's canonical schema."""
    path = Path(file_path)
    dim = pd.read_excel(
        path,
        sheet_name="DIM_JOGADORES",
        usecols=DIM_COLUMNS,
    )
    fact = pd.read_excel(
        path,
        sheet_name="FATO_MENSAL",
        usecols=FACT_COLUMNS,
    )

    dim.columns = dim.columns.str.strip().str.lower()
    fact.columns = fact.columns.str.strip().str.lower()

    dim["nickname"] = dim["nickname"].astype(str).str.strip()
    fact["nickname"] = fact["nickname"].astype(str).str.strip()

    dim["mostrar"] = dim["mostrar"].astype(str).str.upper().str.strip()
    dim = dim[dim["mostrar"] == "YES"]

    df = fact.merge(dim, on="nickname", how="inner")
    df["date"] = pd.to_datetime(df["date"], errors="raise")

    latest_names = (
        df.sort_values("date")
        .groupby("id_jogador", as_index=False)["nickname"]
        .last()
        .rename(columns={"nickname": "nickname_latest"})
    )

    df = df.merge(latest_names, on="id_jogador", how="left")
    df["nickname"] = df["nickname_latest"]

    return df.drop(columns=["nickname_latest"])


def data_file_fingerprint(file_path: str | Path = DEFAULT_EXCEL_PATH) -> tuple[str, int, int]:
    """Return a stable cache key for Streamlit based on path, mtime and size."""
    path = Path(file_path)
    stat = path.stat()
    return str(path.resolve()), int(stat.st_mtime), int(stat.st_size)
