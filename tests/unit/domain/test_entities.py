from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta

import pytest

from aval.domain.entities import (
    AuditEvent,
    CheckoutIntent,
    Mandate,
    Principal,
    Reservation,
    RevocationAuthority,
)
from aval.domain.enums import MandateStatus, ReservationStatus, RevocationRole
from aval.domain.errors import DomainError
from aval.domain.money import Money


def authority() -> RevocationAuthority:
    return RevocationAuthority(
        id="authority_holder",
        kid="holder-key",
        role=RevocationRole.HOLDER,
        public_jwk={"kty": "EC", "crv": "P-256", "kid": "holder-key"},
        allowed_scopes=frozenset({"mandate"}),
    )


def mandate() -> Mandate:
    return Mandate(
        id="mandate_1",
        principal=Principal(id="principal_1", display_name="Marta"),
        allowed_merchant_ids=frozenset({"merchant_1"}),
        allowed_categories=frozenset({"travel"}),
        limit=Money(minor_units=10_000, currency="BRL", scale=2),
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        policy_version=1,
        revocation_metadata={"revocation_id": "rev_1", "epoch": 0},
        authorities=(authority(),),
    )


def test_money_uses_explicit_integer_units_and_rejects_float():
    assert Money(minor_units=1234, currency="BRL", scale=2).minor_units == 1234

    with pytest.raises(DomainError):
        Money(minor_units=12.34, currency="BRL", scale=2)  # type: ignore[arg-type]


def test_mandate_requires_revocation_metadata_and_authority():
    valid = mandate()
    assert valid.status is MandateStatus.ACTIVE

    with pytest.raises(DomainError):
        Mandate(
            id="mandate_without_authority",
            principal=valid.principal,
            allowed_merchant_ids=valid.allowed_merchant_ids,
            allowed_categories=valid.allowed_categories,
            limit=valid.limit,
            expires_at=valid.expires_at,
            policy_version=1,
            revocation_metadata={},
            authorities=(),
        )


def test_mandate_must_declare_what_may_be_bought():
    valid = mandate()

    with pytest.raises(DomainError):
        Mandate(
            id="mandate_without_category",
            principal=valid.principal,
            allowed_merchant_ids=valid.allowed_merchant_ids,
            allowed_categories=frozenset(),
            limit=valid.limit,
            expires_at=valid.expires_at,
            policy_version=1,
            revocation_metadata=valid.revocation_metadata,
            authorities=valid.authorities,
        )


def test_a_mandate_ceiling_must_share_the_limit_money_unit():
    valid = mandate()

    with pytest.raises(DomainError):
        Mandate(
            id="mandate_with_foreign_ceiling",
            principal=valid.principal,
            allowed_merchant_ids=valid.allowed_merchant_ids,
            allowed_categories=valid.allowed_categories,
            limit=valid.limit,
            expires_at=valid.expires_at,
            policy_version=1,
            revocation_metadata=valid.revocation_metadata,
            authorities=valid.authorities,
            ceiling=Money(minor_units=50_000, currency="USD", scale=2),
        )


def test_checkout_cannot_exist_without_mandate():
    with pytest.raises(DomainError):
        CheckoutIntent(
            id="checkout_1",
            mandate_id="",
            merchant_id="merchant_1",
            total=Money(minor_units=500, currency="BRL", scale=2),
        )


def test_only_reservations_have_a_commit_transition():
    active_mandate = mandate()
    assert not hasattr(active_mandate, "commit")

    reservation = Reservation(
        id="reservation_1",
        mandate_id=active_mandate.id,
        checkout_intent_id="checkout_1",
        amount=Money(minor_units=500, currency="BRL", scale=2),
    )
    committed = reservation.commit("transaction-hash")
    settled = committed.settle()

    assert committed.status is ReservationStatus.COMMITTED
    assert settled.status is ReservationStatus.SETTLED
    with pytest.raises(DomainError):
        settled.release()


def test_audit_event_is_immutable():
    event = AuditEvent(
        id="audit_1",
        mandate_id="mandate_1",
        event_type="mandate_issued",
        human_summary="Mandato emitido.",
        occurred_at=datetime.now(UTC),
    )

    with pytest.raises(FrozenInstanceError):
        event.human_summary = "alterado"  # type: ignore[misc]


def test_a_mandate_limit_must_be_positive():
    """A mandate that authorizes zero or less authorizes nothing, and must say so at
    creation rather than turning every purchase into an approval request."""
    for amount in (0, -1):
        with pytest.raises(DomainError):
            replace(mandate(), limit=Money(amount, "BRL", 2))


def test_a_mandate_ceiling_must_be_positive():
    for amount in (0, -1):
        with pytest.raises(DomainError):
            replace(mandate(), ceiling=Money(amount, "BRL", 2))
