from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Mapping

from aval.domain.enums import (
    DisputeStatus,
    EscalationStatus,
    MandateStatus,
    ReservationStatus,
    RevocationRole,
)
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
    allowed_categories: frozenset[str]
    limit: Money
    expires_at: datetime
    policy_version: int
    revocation_metadata: Mapping[str, object]
    authorities: tuple[RevocationAuthority, ...]
    ceiling: Money | None = None
    status: MandateStatus = MandateStatus.ACTIVE

    def __post_init__(self) -> None:
        if not self.id:
            raise DomainError("mandate id is required")
        if not self.allowed_merchant_ids:
            raise DomainError("mandate must allow at least one merchant")
        if not self.allowed_categories:
            raise DomainError("mandate must declare at least one allowed category")
        if self.ceiling is not None and (self.ceiling.currency, self.ceiling.scale) != (
            self.limit.currency,
            self.limit.scale,
        ):
            raise DomainError("mandate ceiling must share the limit money unit")
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


@dataclass(frozen=True)
class Dispute:
    """A later denial of a purchase, resolved by reading the trail rather than by trust."""

    id: str
    mandate_id: str
    reservation_id: str
    reason: str
    opened_at: datetime
    status: DisputeStatus = DisputeStatus.OPEN
    resolution: str | None = None
    resolved_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.reservation_id:
            raise DomainError("a dispute must name the reservation it denies")
        if not self.reason:
            raise DomainError("a dispute must carry the reason it was opened")

    def resolve(self, status: DisputeStatus, resolution: str, resolved_at: datetime) -> "Dispute":
        if self.status is not DisputeStatus.OPEN:
            raise DomainError("only an open dispute may be resolved")
        if status is DisputeStatus.OPEN:
            raise DomainError("a dispute resolution must be conclusive")
        return replace(self, status=status, resolution=resolution, resolved_at=resolved_at)


@dataclass(frozen=True)
class Escalation:
    """A purchase the core refused to decide alone.

    It freezes what was asked. The approval that arrives later is checked against these
    fields, so approving cannot become a way to buy something bigger.
    """

    id: str
    mandate_id: str
    checkout_id: str
    merchant_id: str
    category: str
    amount: Money
    reason_code: str
    created_at: datetime
    expires_at: datetime
    status: EscalationStatus = EscalationStatus.OPEN
    agent_id: str | None = None
    approval_jws: str | None = None
    decided_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.reason_code:
            raise DomainError("an escalation must carry the reason it was raised")
        if self.expires_at <= self.created_at:
            raise DomainError("an escalation must expire after it was created")

    def is_expired_at(self, instant: datetime) -> bool:
        return instant >= self.expires_at
