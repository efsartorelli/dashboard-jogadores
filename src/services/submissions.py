from __future__ import annotations

from datetime import date
from typing import Any

from src.database.connection import get_connection
from src.database.repositories import (
    buscar_usuario_por_id,
    buscar_jogador_por_nickname,
    buscar_ultimo_catches,
    inserir_nickname_jogador,
    inserir_novo_jogador,
    inserir_registro_periodico,
    registrar_auditoria,
    verificar_duplicidade_registro,
)
from src.validation.submissions import (
    Submission,
    normalize_nickname,
    normalize_state,
    sanitize_text,
    validate_submission,
)
from src.services.rate_limit import check_and_record_rate_limit
from src.services.users import get_user_entitlement, normalize_user_id


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
        state=normalize_state(payload.get("state")),
    )


def _requested_status(payload: dict[str, Any], allow_validated: bool) -> str | None:
    status = str(payload.get("status", "pendente")).strip().lower()
    if not allow_validated and status == "validado":
        return "pendente"
    if status not in {"pendente", "validado"}:
        return None
    return status


def _audit_after_payload(
    jogador_id: int,
    record_id: int,
    submission: Submission,
    status: str,
    fonte: str,
) -> dict[str, Any]:
    return {
        "record_id": record_id,
        "jogador_id": jogador_id,
        "nickname": submission.nickname,
        "state": submission.state,
        "periodo_tipo": submission.periodo_tipo,
        "data_referencia": submission.data_referencia.isoformat(),
        "catches": submission.catches,
        "status": status,
        "fonte": fonte,
    }


def submit_player_record(
    payload: dict[str, Any],
    conn=None,
    allow_validated: bool = False,
    require_authenticated: bool = False,
    enforce_monthly_limit: bool = False,
    enforce_rate_limit: bool = False,
) -> dict[str, Any]:
    try:
        submission = parse_submission_payload(payload)
    except Exception:
        return {"success": False, "errors": ["Dados inválidos. Revise data e capturas."], "record_id": None}

    status = _requested_status(payload, allow_validated)
    if status is None:
        return {
            "success": False,
            "errors": ["Status deve ser pendente ou validado."],
            "record_id": None,
        }

    fonte = sanitize_text(payload.get("fonte", "site"), max_length=40).lower() or "site"
    observacao = sanitize_text(payload.get("observacao"), max_length=500)
    contato_envio = sanitize_text(payload.get("contato_envio"), max_length=120)
    country = sanitize_text(payload.get("country") or payload.get("pais"), max_length=60)
    city = sanitize_text(payload.get("city") or payload.get("cidade"), max_length=80)
    created_by = normalize_user_id(payload.get("created_by"))
    if require_authenticated and not created_by:
        return {
            "success": False,
            "errors": ["Usuario autenticado obrigatorio para enviar dados."],
            "record_id": None,
        }

    owns_connection = conn is None
    context = get_connection() if owns_connection else None
    if owns_connection:
        conn = context.__enter__()

    try:
        if enforce_rate_limit and created_by:
            decision = check_and_record_rate_limit(
                conn,
                "submission_attempt",
                user_id=created_by,
                max_events=6,
                window_seconds=600,
                metadata={"nickname": submission.nickname, "fonte": fonte},
            )
            if not decision.allowed:
                return {
                    "success": False,
                    "errors": ["Muitas tentativas em pouco tempo. Aguarde alguns minutos e tente novamente."],
                    "record_id": None,
                }

        if enforce_monthly_limit and created_by:
            profile = buscar_usuario_por_id(conn, created_by)
            if not profile:
                return {
                    "success": False,
                    "errors": ["Perfil de usuario nao encontrado. Entre novamente."],
                    "record_id": None,
                }
            entitlement = get_user_entitlement(profile, conn=conn)
            if not entitlement.can_submit:
                return {
                    "success": False,
                    "errors": ["Limite mensal de inputs atingido para o seu plano atual."],
                    "record_id": None,
                }

        player = buscar_jogador_por_nickname(conn, submission.nickname)

        errors = validate_submission(submission, previous_catches=None)
        if errors:
            return {"success": False, "errors": errors, "record_id": None}

        jogador_criado = False
        if player:
            jogador_id = int(player["id"])
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
        else:
            jogador_id = inserir_novo_jogador(
                conn,
                nickname=submission.nickname,
                state=submission.state,
                country=country or None,
                city=city or None,
                mostrar=True,
                ativo=True,
            )
            inserir_nickname_jogador(conn, jogador_id, submission.nickname)
            jogador_criado = True

        record_id = inserir_registro_periodico(
            conn,
            jogador_id=jogador_id,
            periodo_tipo=submission.periodo_tipo,
            data_referencia=submission.data_referencia,
            catches=submission.catches,
            fonte=fonte,
            status=status,
            created_by=created_by,
            observacao=observacao,
            contato_envio=contato_envio,
        )
        if record_id is None:
            conn.rollback()
            return {
                "success": False,
                "errors": ["Ja existe registro para este jogador neste periodo."],
                "record_id": None,
            }

        registrar_auditoria(
            conn,
            record_id,
            "criado",
            antes=None,
            depois=_audit_after_payload(jogador_id, record_id, submission, status, fonte),
            usuario_id=created_by,
        )
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
