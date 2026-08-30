from __future__ import annotations

from enum import Enum


class MandateStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class ReservationStatus(str, Enum):
    PENDING = "PENDING"
    COMMITTED = "COMMITTED"
    SETTLED = "SETTLED"
    RELEASED = "RELEASED"


class RevocationRole(str, Enum):
    HOLDER = "holder"
    GUARDIAN = "guardian"
    ISSUER = "issuer"
    OPERATOR = "operator"


class AvalCheckoutStatus(str, Enum):
    READY = "ready"
    AWAITING_HUMAN = "awaiting_human"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    REJECTED = "rejected"


class AuthorizationDecision(str, Enum):
    AUTHORIZED = "authorized"
    AWAITING_HUMAN = "awaiting_human"
    REJECTED = "rejected"


class DisputeStatus(str, Enum):
    OPEN = "OPEN"
    MANDATE_HELD = "MANDATE_HELD"
    MANDATE_FAILED = "MANDATE_FAILED"


class EscalationStatus(str, Enum):
    OPEN = "OPEN"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
