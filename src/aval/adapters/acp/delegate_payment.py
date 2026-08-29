from __future__ import annotations

from datetime import UTC
import secrets

from aval.application.services.vault import DelegatedPayment


class OpaqueTestCredentialTokenizer:
    """Produces non-redeemable local tokens and deliberately retains no PAN."""

    def tokenize(self, card_number: str) -> str:
        if not card_number.isascii() or not card_number.isdigit() or not 12 <= len(card_number) <= 19:
            raise ValueError("test card number must contain 12 to 19 ASCII digits")
        return f"vt_{secrets.token_urlsafe(18)}"


def serialize_delegated_payment(payment: DelegatedPayment) -> dict[str, object]:
    expires_at = payment.allowance.expires_at
    if expires_at.tzinfo is None:
        raise ValueError("allowance expiry must be timezone-aware")
    return {
        "token": payment.token,
        "allowance": {
            "reason": payment.allowance.reason,
            "max_amount": payment.allowance.max_amount,
            "currency": payment.allowance.currency,
            "checkout_session_id": payment.allowance.checkout_session_id,
            "merchant_id": payment.allowance.merchant_id,
            "expires_at": expires_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        },
    }
