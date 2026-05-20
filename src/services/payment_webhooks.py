from __future__ import annotations

from typing import Any

from src.database.connection import get_connection
from src.database.repositories import (
    ativar_premium_usuario,
    atualizar_pagamento_status,
    buscar_pagamento_por_referencia,
    registrar_webhook_pagamento,
)
from src.payments.providers import get_payment_provider


def handle_payment_webhook(
    provider_name: str,
    raw_body: bytes,
    headers: dict[str, str],
    conn=None,
) -> dict[str, Any]:
    provider = get_payment_provider(provider_name)
    signature_valid = provider.verify_webhook_signature(raw_body, headers)
    parsed = provider.parse_webhook(raw_body)
    event_id = parsed.get("event_id") or None
    external_reference = parsed.get("external_reference")

    owns_connection = conn is None
    context = get_connection() if owns_connection else None
    if owns_connection:
        conn = context.__enter__()

    try:
        if not signature_valid:
            registrar_webhook_pagamento(
                conn,
                provider.name,
                event_id,
                False,
                "rejected",
                parsed.get("payload") or {},
                error="invalid_signature",
            )
            if owns_connection:
                conn.commit()
            return {"success": False, "status": "rejected", "error": "invalid_signature"}

        payment = buscar_pagamento_por_referencia(conn, external_reference)
        if not payment:
            registrar_webhook_pagamento(
                conn,
                provider.name,
                event_id,
                True,
                "ignored",
                parsed.get("payload") or {},
                error="payment_not_found",
            )
            if owns_connection:
                conn.commit()
            return {"success": False, "status": "ignored", "error": "payment_not_found"}

        normalized_status = parsed.get("status") or "pending"
        updated_payment = atualizar_pagamento_status(
            conn,
            int(payment["id"]),
            normalized_status,
            provider_payment_id=parsed.get("provider_payment_id") or None,
            raw_payload=parsed.get("payload") or {},
        )
        if normalized_status == "paid":
            ativar_premium_usuario(conn, str(payment["user_id"]), provider.name)

        registrar_webhook_pagamento(
            conn,
            provider.name,
            event_id,
            True,
            normalized_status,
            parsed.get("payload") or {},
            user_id=str(payment["user_id"]),
            payment_id=int(payment["id"]),
        )
        if owns_connection:
            conn.commit()
        return {
            "success": True,
            "status": normalized_status,
            "payment": updated_payment,
            "premium_activated": normalized_status == "paid",
        }
    except Exception:
        if owns_connection:
            conn.rollback()
        raise
    finally:
        if owns_connection and context is not None:
            context.__exit__(None, None, None)
