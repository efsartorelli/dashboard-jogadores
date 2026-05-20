from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import json
from typing import Any
from urllib.parse import urlencode

from src.config import (
    PAYMENT_CANCEL_URL,
    PAYMENT_CHECKOUT_URL,
    PAYMENT_PROVIDER,
    PAYMENT_SUCCESS_URL,
    PAYMENT_WEBHOOK_SECRET,
)


@dataclass(frozen=True)
class CheckoutRequest:
    user_id: str
    email: str
    external_reference: str
    amount_cents: int
    currency: str
    plan_code: str


@dataclass(frozen=True)
class CheckoutResult:
    provider: str
    checkout_url: str | None
    external_reference: str


class PaymentProvider:
    name = "manual"

    def create_checkout(self, request: CheckoutRequest) -> CheckoutResult:
        if not PAYMENT_CHECKOUT_URL:
            return CheckoutResult(self.name, None, request.external_reference)

        params = {
            "reference": request.external_reference,
            "email": request.email,
            "user_id": request.user_id,
            "plan": request.plan_code,
            "amount_cents": request.amount_cents,
            "currency": request.currency,
        }
        if PAYMENT_SUCCESS_URL:
            params["success_url"] = PAYMENT_SUCCESS_URL
        if PAYMENT_CANCEL_URL:
            params["cancel_url"] = PAYMENT_CANCEL_URL

        separator = "&" if "?" in PAYMENT_CHECKOUT_URL else "?"
        return CheckoutResult(
            self.name,
            f"{PAYMENT_CHECKOUT_URL}{separator}{urlencode(params)}",
            request.external_reference,
        )

    def verify_webhook_signature(self, raw_body: bytes, headers: dict[str, str]) -> bool:
        secret = PAYMENT_WEBHOOK_SECRET
        if not secret:
            return False

        normalized_headers = {key.lower(): value for key, value in headers.items()}
        signature = (
            normalized_headers.get("x-webhook-signature")
            or normalized_headers.get("x-cacto-signature")
            or normalized_headers.get("x-pagseguro-signature")
            or normalized_headers.get("stripe-signature")
        )
        if not signature:
            return False

        expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
        provided = signature.split(",", 1)[0].split("=", 1)[-1].strip()
        return hmac.compare_digest(expected, provided)

    def parse_webhook(self, raw_body: bytes) -> dict[str, Any]:
        payload = json.loads(raw_body.decode("utf-8"))
        data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
        status = str(data.get("status") or payload.get("status") or "").lower()

        approved_statuses = {"approved", "paid", "succeeded", "success", "completed"}
        failed_statuses = {"failed", "canceled", "cancelled", "refused", "chargeback"}
        normalized_status = "pending"
        if status in approved_statuses:
            normalized_status = "paid"
        elif status in failed_statuses:
            normalized_status = "failed"

        return {
            "event_id": str(payload.get("id") or payload.get("event_id") or data.get("id") or ""),
            "external_reference": str(
                data.get("external_reference")
                or data.get("reference")
                or data.get("checkout_id")
                or metadata.get("external_reference")
                or metadata.get("reference")
                or ""
            ),
            "provider_payment_id": str(
                data.get("payment_id")
                or data.get("transaction_id")
                or data.get("id")
                or ""
            ),
            "status": normalized_status,
            "raw_status": status,
            "payload": payload,
        }


class CactoProvider(PaymentProvider):
    name = "cacto"


class PagSeguroProvider(PaymentProvider):
    name = "pagseguro"


class StripeProvider(PaymentProvider):
    name = "stripe"


def get_payment_provider(provider: str | None = None) -> PaymentProvider:
    selected = (provider or PAYMENT_PROVIDER or "manual").strip().lower()
    if selected == "cacto":
        return CactoProvider()
    if selected == "pagseguro":
        return PagSeguroProvider()
    if selected == "stripe":
        return StripeProvider()
    return PaymentProvider()
