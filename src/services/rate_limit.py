from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
from typing import Any

from src.database.repositories import contar_eventos_seguranca, registrar_evento_seguranca


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    remaining: int
    retry_after_seconds: int


def hash_subject(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.strip().lower()
    if not normalized:
        return None
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def check_and_record_rate_limit(
    conn,
    event_type: str,
    *,
    user_id: str | None = None,
    subject: str | None = None,
    max_events: int = 5,
    window_seconds: int = 300,
    metadata: dict[str, Any] | None = None,
) -> RateLimitDecision:
    subject_hash = hash_subject(subject)
    since = datetime.now(timezone.utc) - timedelta(seconds=window_seconds)
    current = contar_eventos_seguranca(
        conn,
        event_type,
        since,
        user_id=user_id,
        subject_hash=subject_hash,
    )

    if current >= max_events:
        return RateLimitDecision(False, 0, window_seconds)

    registrar_evento_seguranca(
        conn,
        event_type,
        user_id=user_id,
        subject_hash=subject_hash,
        metadata=metadata,
    )
    return RateLimitDecision(True, max(0, max_events - current - 1), 0)
