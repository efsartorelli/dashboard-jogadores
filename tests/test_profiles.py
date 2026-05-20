import unittest
from unittest.mock import patch

from src.services.users import ensure_profile, profile_has_location, update_user_profile
from src.validation.profiles import validate_profile_fields


class FakeConn:
    def __init__(self):
        self.commits = 0
        self.rollbacks = 0

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class ProfileValidationTest(unittest.TestCase):
    def test_profile_fields_are_required_and_normalized(self):
        normalized, errors = validate_profile_fields("  Kendo4687  ", "Brasil", "sp", "  Sao Paulo  ")

        self.assertEqual(errors, [])
        self.assertEqual(normalized["nickname"], "Kendo4687")
        self.assertEqual(normalized["pais"], "Brasil")
        self.assertEqual(normalized["estado"], "SP")
        self.assertEqual(normalized["cidade"], "Sao Paulo")

    def test_profile_fields_reject_problematic_nickname_and_empty_city(self):
        _, errors = validate_profile_fields("<script>", "Brasil", "SP", "")

        self.assertTrue(any("Nickname" in error for error in errors))
        self.assertTrue(any("Cidade" in error for error in errors))

    def test_profile_location_completion(self):
        self.assertTrue(profile_has_location({"pais": "Brasil", "estado": "SP", "cidade": "Sao Paulo"}))
        self.assertFalse(profile_has_location({"pais": "Brasil", "estado": "SP", "cidade": ""}))

    def test_ensure_profile_saves_auth_metadata(self):
        conn = FakeConn()
        auth_user = {
            "id": "00000000-0000-0000-0000-000000000001",
            "email": "user@example.com",
            "user_metadata": {
                "nickname": "Kendo4687",
                "pais": "Brasil",
                "estado": "SP",
                "cidade": "Sao Paulo",
            },
            "email_confirmed_at": "2026-05-01",
        }

        with patch("src.services.users.upsert_usuario_profile", return_value={"id": auth_user["id"]}) as upsert:
            result = ensure_profile(auth_user, conn=conn)

        self.assertEqual(result["id"], auth_user["id"])
        self.assertEqual(upsert.call_args.kwargs["nickname"], "Kendo4687")
        self.assertEqual(upsert.call_args.kwargs["pais"], "Brasil")
        self.assertEqual(upsert.call_args.kwargs["estado"], "SP")
        self.assertEqual(upsert.call_args.kwargs["cidade"], "Sao Paulo")
        self.assertEqual(conn.commits, 0)

    def test_update_user_profile_validates_required_fields(self):
        conn = FakeConn()
        with patch("src.services.users.buscar_usuario_por_id", return_value={"id": "u"}), \
            patch("src.services.users.atualizar_usuario_profile") as update_profile:
            with self.assertRaises(ValueError):
                update_user_profile(
                    "00000000-0000-0000-0000-000000000001",
                    "Nome",
                    "",
                    "Brasil",
                    "SP",
                    "Sao Paulo",
                    conn=conn,
                )

        update_profile.assert_not_called()


if __name__ == "__main__":
    unittest.main()
