"""Request and response shapes.

These validate *form* only. Every decision about authority stays in the core, so
nothing in this module is allowed to grow an `if` about limits or revocation.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pydantic import BaseModel, Field, StrictInt, field_validator

from aval.domain.money import Money


class MoneyIn(BaseModel):
    """Integer minor units only. A float here is a rounding bug waiting for a demo."""

    minor_units: StrictInt
    currency: str
    scale: StrictInt

    def to_money(self) -> Money:
        return Money(self.minor_units, self.currency, self.scale)


class MoneyOut(BaseModel):
    minor_units: int
    currency: str
    scale: int

    @classmethod
    def of(cls, money: Money) -> "MoneyOut":
        return cls(minor_units=money.minor_units, currency=money.currency, scale=money.scale)


class PrincipalIn(BaseModel):
    id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)


class RevocationAuthorityIn(BaseModel):
    kid: str = Field(min_length=1)
    role: str
    public_jwk: dict[str, str]
    allowed_scopes: list[str] = Field(min_length=1)
    id: str | None = None


class CreateMandateRequest(BaseModel):
    principal: PrincipalIn
    allowed_merchant_ids: list[str] = Field(min_length=1)
    allowed_categories: list[str] = Field(min_length=1)
    limit: MoneyIn
    expires_at: datetime
    authorities: list[RevocationAuthorityIn] = Field(min_length=1)
    ceiling: MoneyIn | None = None

    @field_validator("expires_at")
    @classmethod
    def as_utc_instant(cls, value: datetime) -> datetime:
        """A naive timestamp is read as UTC; an offset one is converted. Either way the
        stored value is the same instant the caller meant, never a wall-clock string."""
        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)


class CreateMandateResponse(BaseModel):
    mandate_id: str
    policy_version: int
    revocation_id: str


class ReplaceLimitRequest(BaseModel):
    limit: MoneyIn
    # Compact JWS ES256 signed by a holder authority of this mandate, over
    # {mandate_id, limit_minor_units, currency, scale}. Required: moving the budget is
    # moving spending authority, so it is proved by the holder, not by the operator.
    authorization_jws: str | None = None


class ReplaceLimitResponse(BaseModel):
    policy_version: int
    epoch: int


class RevocationRequest(BaseModel):
    token: str = Field(min_length=1)


class RevocationResponse(BaseModel):
    revoked: bool
    epoch: int


class PurchaseRequest(BaseModel):
    mandate_id: str = Field(min_length=1)
    checkout_id: str = Field(min_length=1)
    merchant_id: str = Field(min_length=1)
    category: str = Field(min_length=1)
    total: MoneyIn
    # The signed offer being bought. Optional: the mandate is what authorizes, the
    # offer is what binds the terms. A purchase without one is recorded as unbound.
    merchant_authorization: str | None = None


class CaptureRequest(PurchaseRequest):
    idempotency_key: str = Field(min_length=1)
    terms_hash: str | None = None


class AuthorizationResponse(BaseModel):
    decision: str
    reason_code: str
    human_summary: str
    escalation_id: str | None = None


class CaptureResponse(BaseModel):
    approved: bool
    reason_code: str
    settlement_reference: str | None = None
    reservation_id: str | None = None
    escalation_id: str | None = None
    authorization_proof: str | None = None


class MandateView(BaseModel):
    """What a mandate looks like right now, budget included. Human and auditor only."""

    mandate_id: str
    status: str
    principal: dict[str, str]
    allowed_merchant_ids: list[str]
    allowed_categories: list[str]
    limit: MoneyOut
    ceiling: MoneyOut | None
    spent: MoneyOut
    remaining: MoneyOut
    expires_at: datetime
    policy_version: int
    revocation_epoch: int
