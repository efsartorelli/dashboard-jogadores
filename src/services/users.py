from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any
from uuid import UUID

from src.config import FREE_MONTHLY_INPUT_LIMIT, PREMIUM_MONTHLY_INPUT_LIMIT
from src.database.connection import get_connection
from src.database.repositories import (
    atualizar_usuario_profile,
    buscar_usuario_por_id,
    contar_inputs_usuario_mes,
    estatisticas_inputs_usuario,
    listar_perfis_publicos_usuario,
    listar_inputs_usuario,
    listar_pagamentos_usuario,
    tocar_ultimo_acesso_usuario,
    upsert_usuario_profile,
)
from src.validation.submissions import sanitize_text
from src.validation.profiles import (
    normalize_city,
    normalize_country,
    normalize_nickname_match_key,
    normalize_profile_nickname,
    normalize_profile_state,
    profile_location_is_complete,
    validate_profile_fields,
)


def normalize_user_id(value: object) -> str | None:
    try:
        return str(UUID(str(value)))
    except Exception:
        return None


def current_month_range(today: date | None = None) -> tuple[date, date]:
    today = today or date.today()
    month_start = today.replace(day=1)
    if month_start.month == 12:
        next_month = month_start.replace(year=month_start.year + 1, month=1)
    else:
        next_month = month_start.replace(month=month_start.month + 1)
    return month_start, next_month


@dataclass(frozen=True)
class UserEntitlement:
    is_premium: bool
    monthly_limit: int
    used_this_month: int

    @property
    def remaining_this_month(self) -> int:
        return max(0, self.monthly_limit - self.used_this_month)

    @property
    def can_submit(self) -> bool:
        return self.remaining_this_month > 0


def _user_metadata(auth_user: dict[str, Any]) -> dict[str, Any]:
    return dict(auth_user.get("user_metadata") or auth_user.get("raw_user_meta_data") or {})


def ensure_profile(auth_user: dict[str, Any], conn=None) -> dict[str, Any]:
    user_id = normalize_user_id(auth_user.get("id"))
    if not user_id:
        raise ValueError("Usuario autenticado sem UUID valido.")

    metadata = _user_metadata(auth_user)
    email = str(auth_user.get("email") or "").strip().lower()
    name = sanitize_text(metadata.get("nome") or metadata.get("full_name") or "", max_length=120)
    nickname = normalize_profile_nickname(metadata.get("nickname") or name)
    pais = normalize_country(metadata.get("pais"))
    estado = normalize_profile_state(metadata.get("estado"))
    cidade = normalize_city(metadata.get("cidade"))
    email_verified = bool(
        auth_user.get("email_confirmed_at")
        or auth_user.get("confirmed_at")
        or auth_user.get("email_verified")
    )

    owns_connection = conn is None
    context = get_connection() if owns_connection else None
    if owns_connection:
        conn = context.__enter__()
    try:
        profile = upsert_usuario_profile(
            conn,
            user_id,
            email,
            name,
            nickname=nickname,
            pais=pais,
            estado=estado,
            cidade=cidade,
            email_verified=email_verified,
        )
        if owns_connection:
            conn.commit()
        return profile
    except Exception:
        if owns_connection:
            conn.rollback()
        raise
    finally:
        if owns_connection and context is not None:
            context.__exit__(None, None, None)


def refresh_profile(user_id: str, conn=None) -> dict[str, Any] | None:
    user_id = normalize_user_id(user_id)
    if not user_id:
        return None

    owns_connection = conn is None
    context = get_connection() if owns_connection else None
    if owns_connection:
        conn = context.__enter__()
    try:
        profile = buscar_usuario_por_id(conn, user_id)
        if profile:
            tocar_ultimo_acesso_usuario(conn, user_id)
            if owns_connection:
                conn.commit()
        return profile
    except Exception:
        if owns_connection:
            conn.rollback()
        raise
    finally:
        if owns_connection and context is not None:
            context.__exit__(None, None, None)


def update_profile_name(user_id: str, name: str, conn=None) -> dict[str, Any] | None:
    return update_user_profile(user_id, name, None, None, None, None, conn=conn)


def update_user_profile(
    user_id: str,
    name: str | None,
    nickname: str | None,
    pais: str | None,
    estado: str | None,
    cidade: str | None,
    conn=None,
) -> dict[str, Any] | None:
    user_id = normalize_user_id(user_id)
    if not user_id:
        return None

    name = sanitize_text(name, max_length=120)
    if nickname is not None or pais is not None or estado is not None or cidade is not None:
        normalized, errors = validate_profile_fields(nickname, pais, estado, cidade)
        if errors:
            raise ValueError("; ".join(errors))
        nickname = normalized["nickname"]
        pais = normalized["pais"]
        estado = normalized["estado"]
        cidade = normalized["cidade"]

    owns_connection = conn is None
    context = get_connection() if owns_connection else None
    if owns_connection:
        conn = context.__enter__()
    try:
        current = buscar_usuario_por_id(conn, user_id)
        if not current:
            return None
        profile = atualizar_usuario_profile(
            conn,
            user_id,
            name if name is not None else current.get("nome"),
            nickname if nickname is not None else current.get("nickname"),
            pais if pais is not None else current.get("pais"),
            estado if estado is not None else current.get("estado"),
            cidade if cidade is not None else current.get("cidade"),
        )
        if owns_connection:
            conn.commit()
        return profile
    except Exception:
        if owns_connection:
            conn.rollback()
        raise
    finally:
        if owns_connection and context is not None:
            context.__exit__(None, None, None)


def get_user_entitlement(profile: dict[str, Any], conn=None, today: date | None = None) -> UserEntitlement:
    user_id = normalize_user_id(profile.get("id"))
    if not user_id:
        return UserEntitlement(False, FREE_MONTHLY_INPUT_LIMIT, FREE_MONTHLY_INPUT_LIMIT)

    is_premium = bool(profile.get("is_premium"))
    configured_limit = profile.get("input_monthly_limit")
    if configured_limit is not None:
        monthly_limit = int(configured_limit)
        if is_premium and monthly_limit <= FREE_MONTHLY_INPUT_LIMIT:
            monthly_limit = PREMIUM_MONTHLY_INPUT_LIMIT
    else:
        monthly_limit = PREMIUM_MONTHLY_INPUT_LIMIT if is_premium else FREE_MONTHLY_INPUT_LIMIT

    owns_connection = conn is None
    context = get_connection() if owns_connection else None
    if owns_connection:
        conn = context.__enter__()
    try:
        month_start, next_month = current_month_range(today)
        used = contar_inputs_usuario_mes(conn, user_id, month_start, next_month)
        return UserEntitlement(is_premium, monthly_limit, used)
    finally:
        if owns_connection and context is not None:
            context.__exit__(None, None, None)


def get_profile_overview(user_id: str, conn=None) -> dict[str, Any]:
    user_id = normalize_user_id(user_id)
    if not user_id:
        raise ValueError("Usuario invalido.")

    owns_connection = conn is None
    context = get_connection() if owns_connection else None
    if owns_connection:
        conn = context.__enter__()
    try:
        profile = buscar_usuario_por_id(conn, user_id)
        stats = estatisticas_inputs_usuario(conn, user_id)
        history = listar_inputs_usuario(conn, user_id, limit=60)
        payments = listar_pagamentos_usuario(conn, user_id, limit=20)
        entitlement = get_user_entitlement(profile or {"id": user_id}, conn=conn)
        return {
            "profile": profile,
            "stats": stats,
            "history": history,
            "payments": payments,
            "entitlement": entitlement,
        }
    finally:
        if owns_connection and context is not None:
            context.__exit__(None, None, None)


def get_public_profile_index(conn=None) -> dict[str, dict[str, Any]]:
    owns_connection = conn is None
    context = get_connection() if owns_connection else None
    if owns_connection:
        conn = context.__enter__()
    try:
        profiles: dict[str, dict[str, Any]] = {}
        for profile in listar_perfis_publicos_usuario(conn):
            key = normalize_nickname_match_key(profile.get("nickname"))
            if key and key not in profiles:
                profiles[key] = {
                    "nickname": profile.get("nickname"),
                    "pais": profile.get("pais"),
                    "estado": profile.get("estado"),
                    "cidade": profile.get("cidade"),
                    "is_premium": bool(profile.get("is_premium")),
                    "premium_status": profile.get("premium_status"),
                    "created_at": profile.get("created_at"),
                    "updated_at": profile.get("updated_at"),
                }
        return profiles
    finally:
        if owns_connection and context is not None:
            context.__exit__(None, None, None)


def user_can_moderate(profile: dict[str, Any] | None) -> bool:
    role = str((profile or {}).get("role") or "jogador").lower()
    return role in {"admin", "moderador"}


def user_is_admin(profile: dict[str, Any] | None) -> bool:
    role = str((profile or {}).get("role") or "jogador").lower()
    return role == "admin"


def profile_has_location(profile: dict[str, Any] | None) -> bool:
    return profile_location_is_complete(profile)
