from pathlib import Path
import os
from typing import Any

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None


if load_dotenv is not None:
    load_dotenv()

env_path = Path(__file__).resolve().parents[1] / ".env"
if env_path.exists():
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if not line or line.strip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip().lstrip("\ufeff"), value.strip().strip('"').strip("'"))


def _streamlit_secret(key: str) -> Any | None:
    try:
        import streamlit as st

        if key in st.secrets:
            return st.secrets[key]
    except Exception:
        return None
    return None


def get_setting(key: str, default: str | None = None) -> str | None:
    value = os.getenv(key)
    if value is not None and str(value).strip():
        return str(value).strip()

    secret = _streamlit_secret(key)
    if secret is not None and str(secret).strip():
        return str(secret).strip()

    return default

ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT_DIR / "data"
DEFAULT_EXCEL_PATH = DATA_DIR / "nofullautoinsidebuildings.xlsx"

DATA_SOURCE = (get_setting("DATA_SOURCE", "auto") or "auto").strip().lower()
DATABASE_URL = get_setting("DATABASE_URL")
ENABLE_ADMIN = (get_setting("ENABLE_ADMIN", "false") or "false").strip().lower() == "true"
ADMIN_PASSWORD = get_setting("ADMIN_PASSWORD")
