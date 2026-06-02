from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any
from urllib.parse import quote

import requests

from src.config import (
    AUTH_SESSION_REFRESH_MARGIN_SECONDS,
    get_setting,
)
from src.security import sanitize_error_message


class AuthError(RuntimeError):
    """Raised for user-facing authentication failures."""


@dataclass(frozen=True)
class AuthSession:
    access_token: str
    refresh_token: str
    expires_at: int
    user: dict[str, Any]

    @property
    def expires_in(self) -> int:
        return max(0, self.expires_at - int(time.time()))

    @property
    def should_refresh(self) -> bool:
        return self.expires_in <= AUTH_SESSION_REFRESH_MARGIN_SECONDS

    @classmethod
    def from_token_response(cls, payload: dict[str, Any]) -> "AuthSession":
        access_token = str(payload.get("access_token") or "")
        refresh_token = str(payload.get("refresh_token") or "")
        user = payload.get("user") or {}
        if not access_token or not refresh_token or not user:
            raise AuthError("Sessao de autenticacao incompleta.")

        expires_in = int(payload.get("expires_in") or 3600)
        return cls(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=int(time.time()) + expires_in,
            user=dict(user),
        )

    def with_user(self, user: dict[str, Any]) -> "AuthSession":
        return AuthSession(
            access_token=self.access_token,
            refresh_token=self.refresh_token,
            expires_at=self.expires_at,
            user=dict(user),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at": self.expires_at,
            "user": self.user,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "AuthSession | None":
        if not payload:
            return None
        try:
            return cls(
                access_token=str(payload["access_token"]),
                refresh_token=str(payload["refresh_token"]),
                expires_at=int(payload["expires_at"]),
                user=dict(payload["user"]),
            )
        except Exception:
            return None


class SupabaseAuthClient:
    def __init__(self, url: str | None = None, anon_key: str | None = None, timeout: int = 12):
        self.url = (url or get_setting("SUPABASE_URL") or "").rstrip("/")
        self.anon_key = anon_key or get_setting("SUPABASE_ANON_KEY") or ""
        self.timeout = timeout

    @property
    def is_configured(self) -> bool:
        return bool(self.url and self.anon_key)

    def _headers(self, bearer_token: str | None = None) -> dict[str, str]:
        headers = {
            "apikey": self.anon_key,
            "Content-Type": "application/json",
        }
        if bearer_token:
            headers["Authorization"] = f"Bearer {bearer_token}"
        return headers

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        bearer_token: str | None = None,
    ) -> dict[str, Any]:
        if not self.is_configured:
            raise AuthError("Supabase Auth nao configurado.")

        try:
            response = requests.request(
                method,
                f"{self.url}{path}",
                headers=self._headers(bearer_token),
                json=json,
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise AuthError("Nao foi possivel conectar ao Supabase Auth.") from exc

        try:
            payload = response.json() if response.content else {}
        except ValueError:
            payload = {}

        if response.status_code >= 400:
            message = (
                payload.get("msg")
                or payload.get("message")
                or payload.get("error_description")
                or payload.get("error")
                or "Falha de autenticacao."
            )
            raise AuthError(sanitize_error_message(str(message), [self.anon_key]))

        return dict(payload)

    def sign_up(
        self,
        email: str,
        password: str,
        name: str | None = None,
        nickname: str | None = None,
        pais: str | None = None,
        estado: str | None = None,
        cidade: str | None = None,
        redirect_to: str | None = None,
    ) -> AuthSession | None:
        payload = {
            "email": email.strip().lower(),
            "password": password,
            "data": {
                "nome": (name or "").strip(),
                "full_name": (name or "").strip(),
                "nickname": (nickname or "").strip(),
                "pais": (pais or "").strip(),
                "estado": (estado or "").strip(),
                "cidade": (cidade or "").strip(),
            },
        }
        path = "/auth/v1/signup"
        if redirect_to:
            path = f"{path}?redirect_to={quote(redirect_to, safe='')}"
        response = self._request("POST", path, json=payload)
        if response.get("access_token"):
            return AuthSession.from_token_response(response)
        return None

    def sign_in(self, email: str, password: str) -> AuthSession:
        response = self._request(
            "POST",
            "/auth/v1/token?grant_type=password",
            json={"email": email.strip().lower(), "password": password},
        )
        return AuthSession.from_token_response(response)

    def refresh(self, refresh_token: str) -> AuthSession:
        response = self._request(
            "POST",
            "/auth/v1/token?grant_type=refresh_token",
            json={"refresh_token": refresh_token},
        )
        return AuthSession.from_token_response(response)

    def get_user(self, access_token: str) -> dict[str, Any]:
        response = self._request("GET", "/auth/v1/user", bearer_token=access_token)
        user = response.get("user") if "user" in response else response
        if not user:
            raise AuthError("Sessao invalida ou expirada.")
        return dict(user)

    def sign_out(self, access_token: str) -> None:
        self._request("POST", "/auth/v1/logout", bearer_token=access_token)

    def recover_password(self, email: str, redirect_to: str | None = None) -> None:
        payload: dict[str, Any] = {"email": email.strip().lower()}
        if redirect_to:
            payload["redirect_to"] = redirect_to
        self._request("POST", "/auth/v1/recover", json=payload)

    def update_password(self, access_token: str, password: str) -> None:
        self._request(
            "PUT",
            "/auth/v1/user",
            json={"password": password},
            bearer_token=access_token,
        )


def get_auth_client() -> SupabaseAuthClient:
    return SupabaseAuthClient()
