from __future__ import annotations

from datetime import UTC
import secrets

from aval.application.services.vault import DelegatedPayment


class OpaqueDelegationTokenMinter:
    """Mints the unguessable handle one delegation is presented under.

    It takes no card, holds no card and could not leak one. What it produces is
    meaningless on its own: the scope that makes it spendable lives in the vault
    record, and the card it delegates lives on the mandate.
    """

    def mint(self) -> str:
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
