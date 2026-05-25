from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - dependency is declared in requirements.txt
    load_dotenv = None


ROOT_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT_DIR / "data"
DEFAULT_EXCEL_PATH = DATA_DIR / "nofullautoinsidebuildings.xlsx"
DOTENV_PATH = ROOT_DIR / ".env"
PRODUCTION_APP_URL = "https://dashboard-jogadores-yhkbgujmiz4nkfgsh3xnvq.streamlit.app"


def _load_local_dotenv() -> None:
    """Load local .env values without overriding real environment variables."""
    if load_dotenv is None:
        return
    load_dotenv(DOTENV_PATH, override=False)
    for key, value in list(os.environ.items()):
        normalized = key.lstrip("\ufeff").strip()
        if normalized != key and normalized and normalized not in os.environ:
            os.environ[normalized] = value


_load_local_dotenv()


def _streamlit_secret(key: str) -> Any | None:
    try:
        import streamlit as st

        if key in st.secrets:
            return st.secrets[key]
    except Exception:
        return None
    return None


def _clean_value(value: Any) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def get_setting(key: str, default: str | None = None) -> str | None:
    secret = _clean_value(_streamlit_secret(key))
    if secret is not None:
        return secret

    value = _clean_value(os.getenv(key))
    if value is not None:
        return value

    return default


def get_int_setting(key: str, default: int) -> int:
    value = get_setting(key, str(default))
    try:
        return int(value or default)
    except (TypeError, ValueError):
        return default


def get_bool_setting(key: str, default: bool = False) -> bool:
    value = (get_setting(key) or "").strip().lower()
    if not value:
        return default
    return value in {"1", "true", "yes", "y", "on"}


def _is_local_url(value: str | None) -> bool:
    normalized = (value or "").strip().lower()
    return (
        "localhost" in normalized
        or "127.0.0.1" in normalized
        or normalized.startswith("http://0.0.0.0")
    )


def get_auth_redirect_url() -> str:
    configured = get_setting("SUPABASE_AUTH_REDIRECT_URL")
    if configured and not _is_local_url(configured):
        return configured.rstrip("/")

    for legacy_key in ("SITE_URL", "APP_URL", "STREAMLIT_APP_URL", "NEXT_PUBLIC_SITE_URL"):
        legacy_value = get_setting(legacy_key)
        if legacy_value and not _is_local_url(legacy_value):
            return legacy_value.rstrip("/")

    return PRODUCTION_APP_URL


@dataclass(frozen=True)
class SettingsValidation:
    missing: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.missing

    def message(self) -> str:
        if self.ok:
            return "Configuracao obrigatoria presente."
        return "Variaveis obrigatorias ausentes: " + ", ".join(self.missing)


def validate_required_settings(keys: Iterable[str]) -> SettingsValidation:
    missing = tuple(key for key in keys if not get_setting(key))
    return SettingsValidation(missing=missing)


def validate_runtime_settings(
    *,
    require_database: bool = False,
    require_auth: bool = True,
    require_payment_webhook: bool = False,
) -> SettingsValidation:
    required: list[str] = []
    if require_database:
        required.append("DATABASE_URL")
    if require_auth:
        required.extend(["SUPABASE_URL", "SUPABASE_ANON_KEY"])
    if require_payment_webhook:
        required.append("PAYMENT_WEBHOOK_SECRET")
    return validate_required_settings(required)


DATA_SOURCE = (get_setting("DATA_SOURCE", "auto") or "auto").strip().lower()
DATABASE_URL = get_setting("DATABASE_URL")
SUPABASE_URL = get_setting("SUPABASE_URL")
SUPABASE_ANON_KEY = get_setting("SUPABASE_ANON_KEY")
SUPABASE_AUTH_REDIRECT_URL = get_auth_redirect_url()

AUTH_SESSION_REFRESH_MARGIN_SECONDS = get_int_setting("AUTH_SESSION_REFRESH_MARGIN_SECONDS", 120)
AUTH_SESSION_VALIDATE_INTERVAL_SECONDS = get_int_setting("AUTH_SESSION_VALIDATE_INTERVAL_SECONDS", 300)
FREE_MONTHLY_INPUT_LIMIT = get_int_setting("FREE_MONTHLY_INPUT_LIMIT", 5)
PREMIUM_MONTHLY_INPUT_LIMIT = get_int_setting("PREMIUM_MONTHLY_INPUT_LIMIT", 50)
ENABLE_PREMIUM = get_bool_setting("ENABLE_PREMIUM", False)

PAYMENT_PROVIDER = (get_setting("PAYMENT_PROVIDER", "manual") or "manual").strip().lower()
PAYMENT_CHECKOUT_URL = get_setting("PAYMENT_CHECKOUT_URL")
PAYMENT_WEBHOOK_SECRET = get_setting("PAYMENT_WEBHOOK_SECRET")
PAYMENT_SUCCESS_URL = get_setting("PAYMENT_SUCCESS_URL")
PAYMENT_CANCEL_URL = get_setting("PAYMENT_CANCEL_URL")
PREMIUM_PRICE_CENTS = get_int_setting("PREMIUM_PRICE_CENTS", 1990)
PREMIUM_CURRENCY = (get_setting("PREMIUM_CURRENCY", "BRL") or "BRL").strip().upper()
