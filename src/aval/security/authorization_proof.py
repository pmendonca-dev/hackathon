from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from uuid import uuid4

from aval.domain.entities import AuthorizationProof, Reservation
from aval.domain.enums import ReservationStatus
from aval.security.jws import sign_compact_jws, verify_compact_jws
from aval.security.key_custody import KeyCustodyService


class AuthorizationProofService:
    """Issue and consume the short-lived proof valid after the commit point."""

    def __init__(self, *, clock: Callable[[], datetime], custody: KeyCustodyService, kid: str) -> None:
        self._clock = clock
        self._custody = custody
        self._kid = kid
        self._used_jtis: set[str] = set()

    def issue(
        self, reservation: Reservation, *, policy_version: int, revocation_epoch: int
    ) -> AuthorizationProof:
        if reservation.status is not ReservationStatus.COMMITTED or not reservation.transaction_hash:
            raise ValueError("authorization proofs require a committed reservation")
        issued_at = self._clock()
        expires_at = issued_at + timedelta(seconds=60)
        jti = uuid4().hex
        payload = {
            "v": 1,
            "jti": jti,
            "reservation_id": reservation.id,
            "transaction_hash": reservation.transaction_hash,
            "policy_version": policy_version,
            "revocation_epoch": revocation_epoch,
            "iat": int(issued_at.timestamp()),
            "exp": int(expires_at.timestamp()),
        }
        return AuthorizationProof(
            id=f"proof_{uuid4().hex}",
            reservation_id=reservation.id,
            jti=jti,
            expires_at=expires_at,
            signed_proof=sign_compact_jws(payload, self._custody, self._kid),
        )

    def verify_and_consume(self, token: str) -> dict[str, object]:
        payload = verify_compact_jws(token, self._custody.public_key(self._kid))
        try:
            jti = str(payload["jti"])
            expires_at = int(payload["exp"])
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("authorization proof is incomplete") from error
        if int(self._clock().timestamp()) > expires_at:
            raise ValueError("authorization proof expired")
        if jti in self._used_jtis:
            raise ValueError("authorization proof already used")
        self._used_jtis.add(jti)
        return payload
