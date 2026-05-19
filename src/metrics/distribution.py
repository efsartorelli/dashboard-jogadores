import pandas as pd


CAPTURE_THRESHOLDS = [100_000, 300_000, 500_000, 700_000, 900_000, 1_000_000, 2_000_000]
CAPTURE_LABELS = ["100k+", "300k+", "500k+", "700k+", "900k+", "1M+", "2M+"]


def build_distribution(base: pd.DataFrame) -> pd.DataFrame:
    catches = base["catches"].to_numpy()
    counts = [int((catches >= threshold).sum()) for threshold in CAPTURE_THRESHOLDS]
    return pd.DataFrame({"Faixa": CAPTURE_LABELS, "Jogadores": counts})
