from __future__ import annotations

import base64
from collections.abc import Callable
from datetime import datetime
import hashlib

from aval.security.jws import sign_compact_jws
from aval.security.key_custody import KeyCustodyService


def mandate_reference(closed_mandate: str) -> str:
    digest = hashlib.sha256(closed_mandate.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


class Ap2ReceiptIssuer:
    """Issues the normative AP2 v0.2 receipt claims as compact ES256 JWTs."""

    def __init__(
        self,
        *,
        issuer: str,
        custody: KeyCustodyService,
        kid: str,
        clock: Callable[[], datetime],
    ) -> None:
        self._issuer = issuer
        self._custody = custody
        self._kid = kid
        self._clock = clock

    def issue_checkout(self, *, closed_mandate: str, order_id: str) -> str:
        return self._sign(
            {
                "status": "Success",
                "iss": self._issuer,
                "iat": int(self._clock().timestamp()),
                "reference": mandate_reference(closed_mandate),
                "order_id": order_id,
            }
        )

    def issue_payment(
        self,
        *,
        closed_mandate: str,
        payment_id: str,
        psp_confirmation_id: str,
    ) -> str:
        return self._sign(
            {
                "status": "Success",
                "iss": self._issuer,
                "iat": int(self._clock().timestamp()),
                "reference": mandate_reference(closed_mandate),
                "payment_id": payment_id,
                "psp_confirmation_id": psp_confirmation_id,
            }
        )

    def _sign(self, claims: dict[str, object]) -> str:
        return sign_compact_jws(claims, self._custody, self._kid)
