import unittest
from unittest.mock import Mock, patch

from src.auth.client import SupabaseAuthClient


class SupabaseAuthClientTest(unittest.TestCase):
    def test_recover_password_sends_redirect_to(self):
        client = SupabaseAuthClient(url="https://example.supabase.co", anon_key="anon")
        response = Mock()
        response.status_code = 200
        response.content = b"{}"
        response.json.return_value = {}

        with patch("src.auth.client.requests.request", return_value=response) as request:
            client.recover_password("User@Email.com", redirect_to="https://app.test/?page=reset-password")

        self.assertEqual(
            request.call_args.args[:2],
            ("POST", "https://example.supabase.co/auth/v1/recover?redirect_to=https%3A%2F%2Fapp.test%2F%3Fpage%3Dreset-password"),
        )
        self.assertEqual(request.call_args.kwargs["json"], {"email": "user@email.com"})

    def test_update_password_uses_authenticated_user_endpoint(self):
        client = SupabaseAuthClient(url="https://example.supabase.co", anon_key="anon")
        response = Mock()
        response.status_code = 200
        response.content = b"{}"
        response.json.return_value = {}

        with patch("src.auth.client.requests.request", return_value=response) as request:
            client.update_password("access-token", "new-password")

        self.assertEqual(request.call_args.args[:2], ("PUT", "https://example.supabase.co/auth/v1/user"))
        self.assertEqual(request.call_args.kwargs["json"], {"password": "new-password"})
        self.assertEqual(request.call_args.kwargs["headers"]["Authorization"], "Bearer access-token")


if __name__ == "__main__":
    unittest.main()
