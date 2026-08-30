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


class UsageLimitIn(BaseModel):
    """The case's "up to 3 times a month", as a rolling window.

    Both fields are positive; the domain refuses anything else, so a mandate cannot be
    created carrying a frequency rule that authorizes nothing.
    """

    max_uses: int
    window_seconds: int


class UsageLimitOut(BaseModel):
    max_uses: int
    window_seconds: int


class PaymentMethodIn(BaseModel):
    """A card the holder already vaulted, named by its token and its last four digits.

    This used to take the number itself, tokenizing it at the edge. That was the one
    place a PAN legitimately appeared — and one place is one more than this system
    needs, now that the card is typed on the processor's own page and arrives here
    already vaulted. There is no longer any request, anywhere, that carries a card
    number: nothing can leak what nothing receives.
    """

    token: str = Field(min_length=4, max_length=255)
    label: str = Field(min_length=1, max_length=64)


class CreateMandateRequest(BaseModel):
    principal: PrincipalIn
    allowed_merchant_ids: list[str] = Field(min_length=1)
    allowed_categories: list[str] = Field(min_length=1)
    limit: MoneyIn
    expires_at: datetime
    authorities: list[RevocationAuthorityIn] = Field(min_length=1)
    ceiling: MoneyIn | None = None
    usage_limit: UsageLimitIn | None = None
    payment_method: PaymentMethodIn | None = None

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
    # The scope a holder signs to cancel the card without ending the mandate. Returned
    # because it names a token the caller has never seen and could not otherwise build.
    instrument_revocation_scope: str | None = None


class ReplaceLimitRequest(BaseModel):
    limit: MoneyIn
    # Compact JWS ES256 signed by a holder authority of this mandate, over
    # {mandate_id, limit_minor_units, currency, scale, policy_version}. Required: moving
    # the budget is moving spending authority, so it is proved by the holder, not by the
    # operator. `policy_version` is the version being superseded, and it is what makes
    # the token single-use — a limit change is reversible, so a replayable one would let
    # an old, higher limit be restored after the holder lowered it.
    authorization_jws: str | None = None


class BindInstrumentRequest(BaseModel):
    """A payment method the holder registered, arriving as a token and four digits.

    There is no card number here on purpose. The number is typed into the processor's
    own page and never reaches this service, so what a mandate can be handed is a
    credential someone else already vaulted — which is also the only kind of credential
    this endpoint could safely accept from an agent-facing surface.
    """

    token: str = Field(min_length=4, max_length=255)
    label: str = Field(min_length=1, max_length=64)
    # Compact JWS ES256 signed by a holder authority of this mandate, over
    # {mandate_id, scope: "instrument", instrument_token, instrument_label, supersedes}.
    # `supersedes` names the token bound right now, or null for a mandate with none:
    # a compare-and-swap, so a captured binding dies the moment any other one lands.
    authorization_jws: str | None = None


class InstrumentSessionRequest(BaseModel):
    """Ask the processor for a page where the holder types their card.

    Signed for the same reason the binding is: this creates objects on our processor
    account, and an endpoint anyone who guesses a mandate id can drive is an abuse
    surface. The JWS is over {mandate_id, scope: "instrument_session"}.
    """

    authorization_jws: str | None = None
    return_url: str | None = None


class InstrumentSessionResponse(BaseModel):
    session_id: str
    url: str


class InstrumentSessionStatusResponse(BaseModel):
    """What the processor holds for a registration that may not be finished yet."""

    ready: bool
    token: str | None = None
    label: str | None = None


class BindInstrumentResponse(BaseModel):
    instrument_label: str
    instrument_revocation_scope: str
    replaced_label: str | None = None


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
    # There is deliberately no `terms_hash` here. The terms hash is what the merchant
    # verifies a purchase against, so it may only ever be derived from the offer this
    # edge verified — never asserted by the caller. A caller that could name it could
    # mint a proof binding an offer whose nonce was never spent, and redeem the same
    # signed offer as many times as it liked.
    # Which payment method is paying. A mandate that names one refuses any other, and
    # refuses a capture that presents none.
    instrument_id: str | None = None


class EvaluationStepOut(BaseModel):
    """One rung of the authorization ladder as the core walked it."""

    check: str
    passed: bool
    detail: str | None = None


class AuthorizationResponse(BaseModel):
    decision: str
    reason_code: str
    human_summary: str
    escalation_id: str | None = None
    # The ladder, in order, stopping where it stopped. It names the live limit and the
    # ceiling, so it is served to the agent and the holder and never to the merchant.
    evaluation_trace: list[EvaluationStepOut] = []


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
    usage_limit: UsageLimitOut | None = None
    # How many uses the live window has already consumed. Read at the same instant
    # as the budget, so the two never disagree about what is left.
    uses_in_window: int = 0
    # The card the mandate names, as four digits. The token is never served: a client
    # that could read it could present it, and only the agent needs to.
    instrument_label: str | None = None
    # Whether that card has been cancelled. The label stays — the holder still needs to
    # know which card it was — but nothing may present it as the live way to pay.
    instrument_revoked: bool = False


class MandateListView(BaseModel):
    """The mandates of one principal. The scope is echoed back so a client cannot
    mistake a listing for somebody else's inbox."""

    principal_id: str
    mandates: list[MandateView]
