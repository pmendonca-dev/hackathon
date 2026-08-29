from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
import base64
import json
from typing import Protocol
from uuid import uuid4

from aval.domain.entities import Mandate, Reservation
from aval.domain.enums import AuthorizationDecision, MandateStatus, ReservationStatus
from aval.domain.money import Money
from aval.security.jws import verify_compact_jws
from aval.security.key_custody import public_key_from_jwk


@dataclass(frozen=True)
class AuthorizationCommand:
    mandate_id: str
    checkout_id: str
    merchant_id: str
    total: Money


@dataclass(frozen=True)
class CaptureCommand(AuthorizationCommand):
    idempotency_key: str


@dataclass(frozen=True)
class AuthorizationResult:
    decision: AuthorizationDecision
    reason_code: str
    human_summary: str


@dataclass(frozen=True)
class SettlementResult:
    approved: bool
    reference: str | None = None


@dataclass(frozen=True)
class CaptureResult:
    approved: bool
    reason_code: str
    reservation: Reservation | None = None
    settlement_reference: str | None = None


class SettlementAdapter(Protocol):
    def authorize(self, reservation: Reservation, proof: str) -> SettlementResult: ...


class AuthorizationCore:
    """The sole writer for the in-process authorization state used by the MVP."""

    def __init__(
        self,
        *,
        clock: Callable[[], datetime],
        settlement_adapter: SettlementAdapter | None = None,
    ) -> None:
        self._clock = clock
        self._settlement_adapter = settlement_adapter
        self._mandates: dict[str, Mandate] = {}
        self._reservations: dict[str, Reservation] = {}
        self._idempotency: dict[str, CaptureResult] = {}

    def register_mandate(self, mandate: Mandate) -> None:
        self._mandates[mandate.id] = mandate

    def submit_signed_revocation(self, token: str) -> None:
        try:
            encoded_header = token.split(".")[0]
            header = json.loads(base64.urlsafe_b64decode(encoded_header + "=" * (-len(encoded_header) % 4)))
            kid = header["kid"]
        except (IndexError, KeyError, ValueError, json.JSONDecodeError) as error:
            raise ValueError("malformed revocation JWS") from error
        for mandate in self._mandates.values():
            for authority in mandate.authorities:
                if authority.kid != kid:
                    continue
                payload = verify_compact_jws(token, public_key_from_jwk(dict(authority.public_jwk)))
                if payload.get("mandate_id") != mandate.id:
                    raise ValueError("revocation mandate does not match authority")
                if payload.get("scope") not in authority.allowed_scopes:
                    raise ValueError("revocation scope is not allowed")
                if not payload.get("reason") or not isinstance(payload.get("epoch"), int):
                    raise ValueError("revocation payload is incomplete")
                self._mandates[mandate.id] = mandate.revoke()
                return
        raise ValueError("unknown revocation authority")

    def evaluate(self, command: AuthorizationCommand) -> AuthorizationResult:
        mandate = self._mandates.get(command.mandate_id)
        if mandate is None:
            return self._reject("mandate_not_found", "Mandato não encontrado.")
        if mandate.status is MandateStatus.REVOKED:
            return self._reject("mandate_revoked", "Mandato revogado.")
        if mandate.status is MandateStatus.EXPIRED or self._clock() >= mandate.expires_at:
            return self._reject("mandate_expired", "Mandato expirado.")
        if command.merchant_id not in mandate.allowed_merchant_ids:
            return AuthorizationResult(
                AuthorizationDecision.AWAITING_HUMAN,
                "merchant_out_of_scope",
                "Merchant fora do escopo do mandato; aprovação humana necessária.",
            )
        if (command.total.currency, command.total.scale) != (mandate.limit.currency, mandate.limit.scale):
            return self._reject("money_unit_mismatch", "Moeda ou escala incompatível com o mandato.")
        if command.total.minor_units <= 0:
            return self._reject("invalid_amount", "Valor de captura inválido.")
        if self._spent(mandate.id).add(command.total).minor_units > mandate.limit.minor_units:
            return AuthorizationResult(
                AuthorizationDecision.AWAITING_HUMAN,
                "budget_exceeded",
                "Compra excede o orçamento vivo do mandato.",
            )
        return AuthorizationResult(AuthorizationDecision.AUTHORIZED, "authorized", "Compra autorizada.")

    def capture(self, command: CaptureCommand) -> CaptureResult:
        if cached := self._idempotency.get(command.idempotency_key):
            return cached
        decision = self.evaluate(command)
        if decision.decision is not AuthorizationDecision.AUTHORIZED:
            result = CaptureResult(False, decision.reason_code)
            self._idempotency[command.idempotency_key] = result
            return result
        reservation = Reservation(
            id=f"rsv_{uuid4().hex}",
            mandate_id=command.mandate_id,
            checkout_intent_id=command.checkout_id,
            amount=command.total,
        ).commit(transaction_hash=uuid4().hex)
        self._reservations[reservation.id] = reservation
        if self._settlement_adapter is None:
            result = CaptureResult(True, "committed", reservation)
        else:
            settlement = self._settlement_adapter.authorize(reservation, f"proof_{reservation.id}")
            final_reservation = reservation.settle() if settlement.approved else reservation.release()
            self._reservations[reservation.id] = final_reservation
            result = CaptureResult(
                settlement.approved,
                "settled" if settlement.approved else "settlement_declined",
                final_reservation,
                settlement.reference,
            )
        self._idempotency[command.idempotency_key] = result
        return result

    def _spent(self, mandate_id: str) -> Money:
        mandate = self._mandates[mandate_id]
        spent = Money(0, mandate.limit.currency, mandate.limit.scale)
        for reservation in self._reservations.values():
            if reservation.mandate_id == mandate_id and reservation.status in {
                ReservationStatus.COMMITTED,
                ReservationStatus.SETTLED,
            }:
                spent = spent.add(reservation.amount)
        return spent

    @staticmethod
    def _reject(reason_code: str, human_summary: str) -> AuthorizationResult:
        return AuthorizationResult(AuthorizationDecision.REJECTED, reason_code, human_summary)
