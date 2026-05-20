from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from src.config import PREMIUM_CURRENCY, PREMIUM_PRICE_CENTS
from src.database.connection import get_connection
from src.database.repositories import criar_pagamento, listar_pagamentos_usuario
from src.payments.providers import CheckoutRequest, get_payment_provider
from src.services.users import normalize_user_id


@dataclass(frozen=True)
class UpgradeCheckout:
    payment: dict[str, Any]
    checkout_url: str | None
    provider: str


def create_upgrade_checkout(profile: dict[str, Any], conn=None) -> UpgradeCheckout:
    user_id = normalize_user_id(profile.get("id"))
    if not user_id:
        raise ValueError("Usuario invalido para pagamento.")

    email = str(profile.get("email") or "").strip().lower()
    provider = get_payment_provider()
    external_reference = f"premium:{user_id}:{uuid4().hex}"
    checkout = provider.create_checkout(
        CheckoutRequest(
            user_id=user_id,
            email=email,
            external_reference=external_reference,
            amount_cents=PREMIUM_PRICE_CENTS,
            currency=PREMIUM_CURRENCY,
            plan_code="premium_monthly",
        )
    )

    owns_connection = conn is None
    context = get_connection() if owns_connection else None
    if owns_connection:
        conn = context.__enter__()
    try:
        payment = criar_pagamento(
            conn,
            user_id=user_id,
            provider=checkout.provider,
            amount_cents=PREMIUM_PRICE_CENTS,
            currency=PREMIUM_CURRENCY,
            external_reference=external_reference,
            checkout_url=checkout.checkout_url,
            plan_code="premium_monthly",
        )
        if owns_connection:
            conn.commit()
        return UpgradeCheckout(payment=payment, checkout_url=checkout.checkout_url, provider=checkout.provider)
    except Exception:
        if owns_connection:
            conn.rollback()
        raise
    finally:
        if owns_connection and context is not None:
            context.__exit__(None, None, None)


def get_payment_history(user_id: str, conn=None) -> list[dict[str, Any]]:
    user_id = normalize_user_id(user_id)
    if not user_id:
        return []

    owns_connection = conn is None
    context = get_connection() if owns_connection else None
    if owns_connection:
        conn = context.__enter__()
    try:
        return listar_pagamentos_usuario(conn, user_id)
    finally:
        if owns_connection and context is not None:
            context.__exit__(None, None, None)
