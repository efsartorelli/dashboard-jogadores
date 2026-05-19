import unittest
from datetime import date, timedelta
from unittest.mock import patch

from src.services.submissions import parse_submission_payload, submit_player_record
from src.validation.submissions import Submission, validate_submission


class FakeConn:
    def __init__(self):
        self.commits = 0
        self.rollbacks = 0

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class SubmissionValidationTest(unittest.TestCase):
    def test_valid_payload_is_normalized(self):
        submission = parse_submission_payload({
            "nickname": "  Kendo4687  ",
            "data_referencia": "2026-04-30",
            "catches": "3063000",
            "periodo_tipo": "Mensal",
            "state": "SP",
        })

        self.assertEqual(submission.nickname, "Kendo4687")
        self.assertEqual(submission.data_referencia, date(2026, 4, 30))
        self.assertEqual(submission.catches, 3_063_000)
        self.assertEqual(submission.periodo_tipo, "mensal")

    def test_validation_rejects_inconsistent_payload(self):
        submission = Submission(
            nickname="",
            data_referencia=date.today() + timedelta(days=1),
            catches=100,
            periodo_tipo="diario",
        )

        errors = validate_submission(submission, previous_catches=200)
        self.assertGreaterEqual(len(errors), 4)
        self.assertTrue(any("Nickname" in error for error in errors))
        self.assertTrue(any("futura" in error for error in errors))
        self.assertTrue(any("menores" in error for error in errors))

    def test_submit_public_payload_defaults_to_pending(self):
        conn = FakeConn()
        payload = {
            "nickname": "NovoJogador",
            "state": "SP",
            "data_referencia": "2026-04-30",
            "catches": 1000,
        }

        with patch("src.services.submissions.buscar_jogador_por_nickname", return_value=None), \
            patch("src.services.submissions.buscar_ultimo_catches", return_value=None), \
            patch("src.services.submissions.inserir_novo_jogador", return_value=999), \
            patch("src.services.submissions.inserir_nickname_jogador"), \
            patch("src.services.submissions.verificar_duplicidade_registro", return_value=False), \
            patch("src.services.submissions.inserir_registro_periodico", return_value=123) as insert_record:
            result = submit_player_record(payload, conn=conn)

        self.assertTrue(result["success"])
        self.assertEqual(result["status"], "pendente")
        self.assertTrue(result["jogador_criado"])
        self.assertEqual(conn.commits, 1)
        self.assertEqual(insert_record.call_args.kwargs["status"], "pendente")
        self.assertEqual(insert_record.call_args.kwargs["periodo_tipo"], "mensal")
        self.assertEqual(insert_record.call_args.kwargs["contato_envio"], "")

    def test_public_payload_cannot_force_validated_without_explicit_period_or_contact(self):
        conn = FakeConn()
        payload = {
            "nickname": "NovoJogador",
            "state": "SP",
            "data_referencia": "2026-04-30",
            "catches": 1000,
            "status": "validado",
            "observacao": "<b>print</b>",
        }

        with patch("src.services.submissions.buscar_jogador_por_nickname", return_value=None), \
            patch("src.services.submissions.buscar_ultimo_catches", return_value=None), \
            patch("src.services.submissions.inserir_novo_jogador", return_value=999), \
            patch("src.services.submissions.inserir_nickname_jogador"), \
            patch("src.services.submissions.verificar_duplicidade_registro", return_value=False), \
            patch("src.services.submissions.inserir_registro_periodico", return_value=123) as insert_record:
            result = submit_player_record(payload, conn=conn)

        self.assertTrue(result["success"])
        self.assertEqual(result["status"], "pendente")
        self.assertEqual(insert_record.call_args.kwargs["status"], "pendente")
        self.assertEqual(insert_record.call_args.kwargs["periodo_tipo"], "mensal")
        self.assertEqual(insert_record.call_args.kwargs["contato_envio"], "")
        self.assertEqual(insert_record.call_args.kwargs["observacao"], "print")

    def test_submit_admin_payload_can_be_validated(self):
        conn = FakeConn()
        payload = {
            "nickname": "Kendo4687",
            "state": "SP",
            "data_referencia": "2026-05-01",
            "catches": 3_100_000,
            "periodo_tipo": "mensal",
            "status": "validado",
            "fonte": "admin",
        }

        with patch("src.services.submissions.buscar_jogador_por_nickname", return_value={"id": 2}), \
            patch("src.services.submissions.buscar_ultimo_catches", return_value=3_063_000), \
            patch("src.services.submissions.verificar_duplicidade_registro", return_value=False), \
            patch("src.services.submissions.inserir_registro_periodico", return_value=124) as insert_record:
            result = submit_player_record(payload, conn=conn, allow_validated=True)

        self.assertTrue(result["success"])
        self.assertEqual(result["status"], "validado")
        self.assertFalse(result["jogador_criado"])
        self.assertEqual(insert_record.call_args.kwargs["status"], "validado")
        self.assertEqual(insert_record.call_args.kwargs["fonte"], "admin")

    def test_submit_duplicate_payload_returns_clear_error(self):
        conn = FakeConn()
        payload = {
            "nickname": "Kendo4687",
            "state": "SP",
            "data_referencia": "2026-04-30",
            "catches": 3_063_000,
            "periodo_tipo": "mensal",
        }

        with patch("src.services.submissions.buscar_jogador_por_nickname", return_value={"id": 2}), \
            patch("src.services.submissions.buscar_ultimo_catches", return_value=3_000_000), \
            patch("src.services.submissions.verificar_duplicidade_registro", return_value=True) as duplicate_check:
            result = submit_player_record(payload, conn=conn)

        self.assertFalse(result["success"])
        self.assertTrue(any("existe registro" in error for error in result["errors"]))
        self.assertEqual(duplicate_check.call_args.kwargs["statuses"], ("pendente", "validado"))
        self.assertEqual(conn.commits, 0)

    def test_submit_invalid_payload_returns_validation_errors(self):
        conn = FakeConn()
        payload = {
            "nickname": "",
            "state": "",
            "data_referencia": "2026-04-30",
            "catches": 0,
            "periodo_tipo": "mensal",
        }

        with patch("src.services.submissions.buscar_jogador_por_nickname", return_value=None):
            result = submit_player_record(payload, conn=conn)

        self.assertFalse(result["success"])
        self.assertTrue(any("Nickname" in error for error in result["errors"]))
        self.assertTrue(any("Estado" in error for error in result["errors"]))
        self.assertTrue(any("maiores que zero" in error for error in result["errors"]))


if __name__ == "__main__":
    unittest.main()
