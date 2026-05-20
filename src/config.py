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
SUPABASE_URL = get_setting("SUPABASE_URL")
SUPABASE_ANON_KEY = get_setting("SUPABASE_ANON_KEY")

AUTH_SESSION_REFRESH_MARGIN_SECONDS = int(get_setting("AUTH_SESSION_REFRESH_MARGIN_SECONDS", "120") or "120")
AUTH_SESSION_VALIDATE_INTERVAL_SECONDS = int(get_setting("AUTH_SESSION_VALIDATE_INTERVAL_SECONDS", "300") or "300")
FREE_MONTHLY_INPUT_LIMIT = int(get_setting("FREE_MONTHLY_INPUT_LIMIT", "5") or "5")
PREMIUM_MONTHLY_INPUT_LIMIT = int(get_setting("PREMIUM_MONTHLY_INPUT_LIMIT", "50") or "50")

PAYMENT_PROVIDER = (get_setting("PAYMENT_PROVIDER", "manual") or "manual").strip().lower()
PAYMENT_CHECKOUT_URL = get_setting("PAYMENT_CHECKOUT_URL")
PAYMENT_WEBHOOK_SECRET = get_setting("PAYMENT_WEBHOOK_SECRET")
PAYMENT_SUCCESS_URL = get_setting("PAYMENT_SUCCESS_URL")
PAYMENT_CANCEL_URL = get_setting("PAYMENT_CANCEL_URL")
PREMIUM_PRICE_CENTS = int(get_setting("PREMIUM_PRICE_CENTS", "1990") or "1990")
PREMIUM_CURRENCY = (get_setting("PREMIUM_CURRENCY", "BRL") or "BRL").strip().upper()
