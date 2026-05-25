from __future__ import annotations

import re
import unicodedata

from src.validation.submissions import BRAZILIAN_STATES, sanitize_text


COUNTRIES = ("Brasil",)
NICKNAME_MIN_LENGTH = 3
NICKNAME_MAX_LENGTH = 40
CITY_MAX_LENGTH = 80
_NICKNAME_RE = re.compile(r"^[A-Za-z0-9_. -]+$")


def normalize_profile_nickname(value: object) -> str:
    return sanitize_text(value, max_length=NICKNAME_MAX_LENGTH)


def normalize_nickname_match_key(value: object) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or "").strip())
    without_accents = "".join(char for char in normalized if not unicodedata.combining(char))
    return " ".join(without_accents.casefold().split())


def normalize_country(value: object) -> str:
    country = sanitize_text(value, max_length=60)
    return country if country in COUNTRIES else ""


def normalize_profile_state(value: object) -> str:
    state = sanitize_text(value, max_length=2).upper()
    return state if state in BRAZILIAN_STATES else ""


def normalize_city(value: object) -> str:
    return sanitize_text(value, max_length=CITY_MAX_LENGTH)


def profile_location_is_complete(profile: dict | None) -> bool:
    profile = profile or {}
    return bool(
        normalize_country(profile.get("pais"))
        and normalize_profile_state(profile.get("estado"))
        and normalize_city(profile.get("cidade"))
    )


def validate_profile_fields(
    nickname: object,
    pais: object,
    estado: object,
    cidade: object,
) -> tuple[dict[str, str], list[str]]:
    normalized = {
        "nickname": normalize_profile_nickname(nickname),
        "pais": normalize_country(pais),
        "estado": normalize_profile_state(estado),
        "cidade": normalize_city(cidade),
    }
    errors: list[str] = []

    if not normalized["nickname"]:
        errors.append("Nickname e obrigatorio.")
    elif len(normalized["nickname"]) < NICKNAME_MIN_LENGTH:
        errors.append(f"Nickname deve ter pelo menos {NICKNAME_MIN_LENGTH} caracteres.")
    elif not _NICKNAME_RE.fullmatch(normalized["nickname"]):
        errors.append("Nickname deve usar apenas letras, numeros, espaco, ponto, hifen ou underline.")

    if not normalized["pais"]:
        errors.append("Pais e obrigatorio.")
    if not normalized["estado"]:
        errors.append("Estado e obrigatorio.")
    if not normalized["cidade"]:
        errors.append("Cidade e obrigatoria.")

    return normalized, errors
