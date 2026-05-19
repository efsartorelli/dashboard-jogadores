from __future__ import annotations

from datetime import date
from typing import Any

from src.database.connection import get_connection
from src.database.repositories import (
    buscar_jogador_por_nickname,
    buscar_ultimo_catches,
    inserir_nickname_jogador,
    inserir_novo_jogador,
    inserir_registro_periodico,
    verificar_duplicidade_registro,
)
from src.validation.submissions import Submission, normalize_nickname, sanitize_text, validate_submission


def _parse_date(value) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def parse_submission_payload(payload: dict[str, Any]) -> Submission:
    return Submission(
        nickname=normalize_nickname(str(payload.get("nickname", ""))),
        data_referencia=_parse_date(payload.get("data_referencia")),
        catches=int(payload.get("catches")),
        periodo_tipo=str(payload.get("periodo_tipo", "mensal")).strip().lower(),
        state=sanitize_text(payload.get("state"), max_length=30),
    )


def submit_player_record(
    payload: dict[str, Any],
    conn=None,
    allow_validated: bool = False,
) -> dict[str, Any]:
    try:
        submission = parse_submission_payload(payload)
    except Exception as exc:
        return {"success": False, "errors": [f"Dados invalidos: {exc}"], "record_id": None}

    owns_connection = conn is None
    context = get_connection() if owns_connection else None
    if owns_connection:
        conn = context.__enter__()

    try:
        player = buscar_jogador_por_nickname(conn, submission.nickname)

        errors = validate_submission(submission, previous_catches=None)
        if errors:
            return {"success": False, "errors": errors, "record_id": None}

        jogador_criado = False
        if player:
            jogador_id = int(player["id"])
        else:
            jogador_id = inserir_novo_jogador(
                conn,
                nickname=submission.nickname,
                state=submission.state,
                mostrar=True,
                ativo=True,
            )
            inserir_nickname_jogador(conn, jogador_id, submission.nickname)
            jogador_criado = True

        if verificar_duplicidade_registro(
            conn,
            jogador_id,
            submission.periodo_tipo,
            submission.data_referencia,
            statuses=("pendente", "validado"),
        ):
            return {
                "success": False,
                "errors": ["Ja existe registro pendente ou validado para este jogador neste periodo."],
                "record_id": None,
            }

        previous_catches = buscar_ultimo_catches(conn, jogador_id, submission.periodo_tipo)
        consistency_errors = validate_submission(submission, previous_catches=previous_catches)
        if consistency_errors:
            return {"success": False, "errors": consistency_errors, "record_id": None}

        status = str(payload.get("status", "pendente")).strip().lower()
        if not allow_validated and status == "validado":
            status = "pendente"
        if status not in {"pendente", "validado"}:
            return {
                "success": False,
                "errors": ["Status deve ser pendente ou validado."],
                "record_id": None,
            }

        fonte = str(payload.get("fonte", "site")).strip().lower() or "site"

        record_id = inserir_registro_periodico(
            conn,
            jogador_id=jogador_id,
            periodo_tipo=submission.periodo_tipo,
            data_referencia=submission.data_referencia,
            catches=submission.catches,
            fonte=fonte,
            status=status,
            created_by=payload.get("created_by"),
            observacao=sanitize_text(payload.get("observacao"), max_length=500),
            contato_envio=sanitize_text(payload.get("contato_envio"), max_length=120),
        )
        if record_id is None:
            conn.rollback()
            return {
                "success": False,
                "errors": ["Ja existe registro para este jogador neste periodo."],
                "record_id": None,
            }

        conn.commit()
        return {
            "success": True,
            "errors": [],
            "record_id": record_id,
            "jogador_id": jogador_id,
            "jogador_criado": jogador_criado,
            "status": status,
        }
    except Exception:
        conn.rollback()
        return {
            "success": False,
            "errors": ["Nao foi possivel salvar o registro agora. Tente novamente mais tarde."],
            "record_id": None,
        }
    finally:
        if owns_connection and context is not None:
            context.__exit__(None, None, None)
