import unittest
from datetime import date
from unittest.mock import patch

from src.services.admin_review import (
    approve_record,
    list_curation_records,
    list_pending_records,
    reject_record,
    update_pending_record,
)


class FakeConn:
    def __init__(self):
        self.commits = 0
        self.rollbacks = 0

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


PENDING_RECORD = {
    "id": 10,
    "jogador_id": 2,
    "nickname": "Kendo4687",
    "state": "SP",
    "ativo": True,
    "periodo_tipo": "mensal",
    "data_referencia": date(2026, 5, 1),
    "catches": 3_100_000,
    "observacao": "teste",
    "status": "pendente",
    "created_at": "2026-05-01",
}


class AdminReviewTest(unittest.TestCase):
    def test_list_pending_records(self):
        conn = FakeConn()
        with patch("src.services.admin_review.listar_registros_pendentes", return_value=[PENDING_RECORD]):
            rows = list_pending_records(conn=conn)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "pendente")

    def test_list_curation_records_requires_admin(self):
        conn = FakeConn()
        with patch("src.services.admin_review.buscar_usuario_por_id", return_value={"role": "jogador"}), \
            patch("src.services.admin_review.listar_registros_curadoria") as list_records:
            result = list_curation_records("00000000-0000-0000-0000-000000000001", conn=conn)

        self.assertFalse(result["success"])
        self.assertEqual(result["records"], [])
        list_records.assert_not_called()

    def test_list_curation_records_supports_pagination_for_admin(self):
        conn = FakeConn()
        with patch("src.services.admin_review.buscar_usuario_por_id", return_value={"role": "admin"}), \
            patch("src.services.admin_review.contar_registros_curadoria", return_value=1) as count_records, \
            patch("src.services.admin_review.listar_registros_curadoria", return_value=[PENDING_RECORD]) as list_records:
            result = list_curation_records(
                "00000000-0000-0000-0000-000000000001",
                status="pending",
                search="kendo",
                page=2,
                page_size=10,
                conn=conn,
            )

        self.assertTrue(result["success"])
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["records"][0]["status"], "pendente")
        count_records.assert_called_once()
        self.assertEqual(list_records.call_args.kwargs["status"], "pendente")
        self.assertEqual(list_records.call_args.kwargs["offset"], 20)

    def test_approve_record_changes_status_and_audits(self):
        conn = FakeConn()
        with patch("src.services.admin_review.buscar_registro_por_id", return_value=PENDING_RECORD), \
            patch("src.services.admin_review.verificar_duplicidade_registro", return_value=False), \
            patch("src.services.admin_review.alterar_status_registro") as change_status, \
            patch("src.services.admin_review.registrar_auditoria") as audit:
            result = approve_record(10, admin_note="ok", conn=conn)

        self.assertTrue(result["success"])
        change_status.assert_called_once_with(conn, 10, "validado")
        self.assertEqual(audit.call_args.args[2], "aprovado")
        self.assertEqual(conn.commits, 1)

    def test_approve_record_requires_admin_when_enabled(self):
        conn = FakeConn()
        with patch("src.services.admin_review.buscar_usuario_por_id", return_value={"role": "moderador"}), \
            patch("src.services.admin_review.buscar_registro_por_id") as get_record:
            result = approve_record(
                10,
                admin_user_id="00000000-0000-0000-0000-000000000001",
                require_admin=True,
                conn=conn,
            )

        self.assertFalse(result["success"])
        self.assertTrue(any("administradores" in error for error in result["errors"]))
        get_record.assert_not_called()

    def test_reject_record_changes_status_and_audits(self):
        conn = FakeConn()
        with patch("src.services.admin_review.buscar_registro_por_id", return_value=PENDING_RECORD), \
            patch("src.services.admin_review.alterar_status_registro") as change_status, \
            patch("src.services.admin_review.registrar_auditoria") as audit:
            result = reject_record(10, admin_note="erro", conn=conn)

        self.assertTrue(result["success"])
        change_status.assert_called_once_with(conn, 10, "rejeitado")
        self.assertEqual(audit.call_args.args[2], "rejeitado")
        self.assertEqual(conn.commits, 1)

    def test_approve_record_blocks_duplicate(self):
        conn = FakeConn()
        with patch("src.services.admin_review.buscar_registro_por_id", return_value=PENDING_RECORD), \
            patch("src.services.admin_review.verificar_duplicidade_registro", return_value=True), \
            patch("src.services.admin_review.alterar_status_registro") as change_status:
            result = approve_record(10, conn=conn)

        self.assertFalse(result["success"])
        self.assertTrue(any("registro validado" in error for error in result["errors"]))
        change_status.assert_not_called()
        self.assertEqual(conn.commits, 0)

    def test_update_pending_record_validates_and_audits(self):
        conn = FakeConn()
        updated = dict(PENDING_RECORD)
        updated["catches"] = 3_200_000
        with patch("src.services.admin_review.buscar_registro_por_id", side_effect=[PENDING_RECORD, updated]), \
            patch("src.services.admin_review.verificar_duplicidade_registro", return_value=False), \
            patch("src.services.admin_review.atualizar_registro") as update_record, \
            patch("src.services.admin_review.registrar_auditoria") as audit:
            result = update_pending_record(10, {"catches": 3_200_000}, conn=conn)

        self.assertTrue(result["success"])
        update_record.assert_called_once()
        self.assertEqual(audit.call_args.args[2], "alterado")
        self.assertEqual(conn.commits, 1)


if __name__ == "__main__":
    unittest.main()
