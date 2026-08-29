from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Mapping

from aval.domain.enums import MandateStatus, ReservationStatus, RevocationRole
from aval.domain.errors import DomainError
from aval.domain.money import Money


@dataclass(frozen=True)
class Principal:
    id: str
    display_name: str


@dataclass(frozen=True)
class AgentIdentity:
    id: str
    profile_url: str
    public_jwk: Mapping[str, str]
    trusted: bool


@dataclass(frozen=True)
class RevocationAuthority:
    id: str
    kid: str
    role: RevocationRole
    public_jwk: Mapping[str, str]
    allowed_scopes: frozenset[str]


@dataclass(frozen=True)
class Mandate:
    id: str
    principal: Principal
    allowed_merchant_ids: frozenset[str]
    limit: Money
    expires_at: datetime
    policy_version: int
    revocation_metadata: Mapping[str, object]
    authorities: tuple[RevocationAuthority, ...]
    status: MandateStatus = MandateStatus.ACTIVE

    def __post_init__(self) -> None:
        if not self.id:
            raise DomainError("mandate id is required")
        if not self.allowed_merchant_ids:
            raise DomainError("mandate must allow at least one merchant")
        if not self.authorities:
            raise DomainError("mandate requires at least one revocation authority")
        if not self.revocation_metadata.get("revocation_id"):
            raise DomainError("mandate requires aval.revocation metadata")
        if self.policy_version < 1:
            raise DomainError("mandate policy version must be positive")

    def revoke(self) -> "Mandate":
        if self.status is not MandateStatus.ACTIVE:
            raise DomainError("only an active mandate may be revoked")
        return replace(self, status=MandateStatus.REVOKED)

    def expire(self) -> "Mandate":
        if self.status is not MandateStatus.ACTIVE:
            raise DomainError("only an active mandate may expire")
        return replace(self, status=MandateStatus.EXPIRED)


@dataclass(frozen=True)
class Revocation:
    id: str
    mandate_id: str
    authority_id: str
    scope: str
    reason: str
    epoch: int
    signed_jws: str
    revoked_at: datetime


@dataclass(frozen=True)
class CheckoutIntent:
    id: str
    mandate_id: str
    merchant_id: str
    total: Money

    def __post_init__(self) -> None:
        if not self.mandate_id:
            raise DomainError("checkout intent requires a mandate id")
        if not self.merchant_id:
            raise DomainError("checkout intent requires a merchant id")


@dataclass(frozen=True)
class Reservation:
    id: str
    mandate_id: str
    checkout_intent_id: str
    amount: Money
    status: ReservationStatus = ReservationStatus.PENDING
    transaction_hash: str | None = None

    def commit(self, transaction_hash: str) -> "Reservation":
        if self.status is not ReservationStatus.PENDING or not transaction_hash:
            raise DomainError("only a pending reservation with a transaction hash may commit")
        return replace(
            self,
            status=ReservationStatus.COMMITTED,
            transaction_hash=transaction_hash,
        )

    def settle(self) -> "Reservation":
        if self.status is not ReservationStatus.COMMITTED:
            raise DomainError("only a committed reservation may settle")
        return replace(self, status=ReservationStatus.SETTLED)

    def release(self) -> "Reservation":
        if self.status not in (ReservationStatus.PENDING, ReservationStatus.COMMITTED):
            raise DomainError("only a pending or committed reservation may release")
        return replace(self, status=ReservationStatus.RELEASED)


@dataclass(frozen=True)
class AuthorizationProof:
    id: str
    reservation_id: str
    jti: str
    expires_at: datetime
    signed_proof: str


@dataclass(frozen=True)
class CaptureAttempt:
    id: str
    reservation_id: str
    idempotency_key: str
    status: str


@dataclass(frozen=True)
class Evidence:
    id: str
    kind: str
    origin: str
    sha256: str
    payload: str


@dataclass(frozen=True)
class AuditEvent:
    id: str
    mandate_id: str
    event_type: str
    human_summary: str
    occurred_at: datetime
    evidence_id: str | None = None
