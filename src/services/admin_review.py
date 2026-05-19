from __future__ import annotations

from datetime import date
from typing import Any

from src.database.connection import get_connection
from src.database.repositories import (
    alterar_status_registro,
    atualizar_registro,
    buscar_registro_por_id,
    listar_registros_pendentes,
    registrar_auditoria,
    verificar_duplicidade_registro,
)


def _parse_date(value) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _audit_payload(record: dict[str, Any] | None, admin_note: str | None = None) -> dict[str, Any]:
    payload = dict(record or {})
    if admin_note:
        payload["admin_note"] = admin_note
    for key, value in list(payload.items()):
        if isinstance(value, (date,)):
            payload[key] = value.isoformat()
        elif not isinstance(value, (str, int, float, bool, type(None), dict, list)):
            payload[key] = str(value)
    return payload


def list_pending_records(conn=None) -> list[dict[str, Any]]:
    owns_connection = conn is None
    context = get_connection() if owns_connection else None
    if owns_connection:
        conn = context.__enter__()
    try:
        return listar_registros_pendentes(conn)
    finally:
        if owns_connection and context is not None:
            context.__exit__(None, None, None)


def approve_record(record_id: int, admin_note: str | None = None, conn=None) -> dict[str, Any]:
    owns_connection = conn is None
    context = get_connection() if owns_connection else None
    if owns_connection:
        conn = context.__enter__()
    try:
        record = buscar_registro_por_id(conn, record_id)
        if not record:
            return {"success": False, "errors": ["Registro não encontrado."]}
        if record["status"] != "pendente":
            return {"success": False, "errors": ["Apenas registros pendentes podem ser aprovados."]}
        if not record["ativo"]:
            return {"success": False, "errors": ["Jogador não está ativo."]}
        if int(record["catches"]) <= 0:
            return {"success": False, "errors": ["Capturas devem ser maiores que zero."]}

        duplicated = verificar_duplicidade_registro(
            conn,
            int(record["jogador_id"]),
            record["periodo_tipo"],
            record["data_referencia"],
            exclude_record_id=record_id,
        )
        if duplicated:
            return {"success": False, "errors": ["Já existe registro validado para este jogador, data e período."]}

        before = _audit_payload(record, admin_note)
        alterar_status_registro(conn, record_id, "validado")
        after = dict(before)
        after["status"] = "validado"
        registrar_auditoria(conn, record_id, "aprovado", before, after)
        conn.commit()
        return {"success": True, "errors": [], "record_id": record_id, "status": "validado"}
    except Exception as exc:
        conn.rollback()
        return {"success": False, "errors": [str(exc)]}
    finally:
        if owns_connection and context is not None:
            context.__exit__(None, None, None)


def reject_record(record_id: int, admin_note: str | None = None, conn=None) -> dict[str, Any]:
    owns_connection = conn is None
    context = get_connection() if owns_connection else None
    if owns_connection:
        conn = context.__enter__()
    try:
        record = buscar_registro_por_id(conn, record_id)
        if not record:
            return {"success": False, "errors": ["Registro não encontrado."]}
        before = _audit_payload(record, admin_note)
        alterar_status_registro(conn, record_id, "rejeitado")
        after = dict(before)
        after["status"] = "rejeitado"
        registrar_auditoria(conn, record_id, "rejeitado", before, after)
        conn.commit()
        return {"success": True, "errors": [], "record_id": record_id, "status": "rejeitado"}
    except Exception as exc:
        conn.rollback()
        return {"success": False, "errors": [str(exc)]}
    finally:
        if owns_connection and context is not None:
            context.__exit__(None, None, None)


def update_pending_record(record_id: int, payload: dict[str, Any], conn=None) -> dict[str, Any]:
    owns_connection = conn is None
    context = get_connection() if owns_connection else None
    if owns_connection:
        conn = context.__enter__()
    try:
        record = buscar_registro_por_id(conn, record_id)
        if not record:
            return {"success": False, "errors": ["Registro não encontrado."]}
        if record["status"] != "pendente":
            return {"success": False, "errors": ["Apenas registros pendentes podem ser editados."]}

        data_referencia = _parse_date(payload.get("data_referencia", record["data_referencia"]))
        catches = int(payload.get("catches", record["catches"]))
        periodo_tipo = str(payload.get("periodo_tipo", record["periodo_tipo"])).strip().lower()
        state = str(payload.get("state", record["state"])).strip()
        observacao = payload.get("observacao", record.get("observacao"))

        errors = []
        if catches <= 0:
            errors.append("Capturas devem ser maiores que zero.")
        if periodo_tipo not in {"mensal", "semanal"}:
            errors.append("Tipo de período deve ser mensal ou semanal.")
        if not state:
            errors.append("Estado é obrigatório.")
        if errors:
            return {"success": False, "errors": errors}

        duplicated = verificar_duplicidade_registro(
            conn,
            int(record["jogador_id"]),
            periodo_tipo,
            data_referencia,
            exclude_record_id=record_id,
        )
        if duplicated:
            return {"success": False, "errors": ["Já existe registro validado para este jogador, data e período."]}

        before = _audit_payload(record, payload.get("admin_note"))
        atualizar_registro(conn, record_id, data_referencia, catches, periodo_tipo, state, observacao)
        updated = buscar_registro_por_id(conn, record_id)
        registrar_auditoria(conn, record_id, "alterado", before, _audit_payload(updated, payload.get("admin_note")))
        conn.commit()
        return {"success": True, "errors": [], "record_id": record_id}
    except Exception as exc:
        conn.rollback()
        return {"success": False, "errors": [str(exc)]}
    finally:
        if owns_connection and context is not None:
            context.__exit__(None, None, None)
