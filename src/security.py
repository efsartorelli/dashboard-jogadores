from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit


def mask_database_url(url: str | None) -> str:
    if not url:
        return "<DATABASE_URL>"

    try:
        parts = urlsplit(url)
        host = parts.hostname or "host"
        port = f":{parts.port}" if parts.port else ""
        netloc = f"***:***@{host}{port}" if parts.username else f"{host}{port}"
        return urlunsplit((parts.scheme, netloc, parts.path, "", ""))
    except Exception:
        return "<DATABASE_URL>"


def sanitize_error_message(error: BaseException | str, secrets: list[str | None] | None = None) -> str:
    message = str(error)
    for secret in secrets or []:
        if not secret:
            continue
        secret = str(secret)
        message = message.replace(secret, "<SECRET>")
        message = message.replace(mask_database_url(secret), "<SECRET>")

        if "://" in secret and "@" in secret:
            userinfo = secret.split("//", 1)[-1].split("@", 1)[0]
            message = message.replace(userinfo, "***:***")
            if ":" in userinfo:
                message = message.replace(userinfo.split(":", 1)[1], "<SECRET>")

    return message
