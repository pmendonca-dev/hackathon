"""There is no PAN to redact any more, and that is the property now.

This file used to prove the edge tokenizer forgot a card number it had been handed.
The stronger version of that guarantee is that no request anywhere carries one: the
card is typed on the processor's own page and reaches this system already vaulted, so
there is nothing to forget, leak, or log.
"""

from __future__ import annotations

from datetime import UTC, datetime
import json

import pytest

from aval.adapters.acp.delegate_payment import (
    OpaqueDelegationTokenMinter,
    serialize_delegated_payment,
)
from aval.application.services.vault import (
    ApprovedPaymentContext,
    DelegationRejected,
    VaultService,
)
from aval.domain.money import Money


class MockApprovedAuthorizer:
    def __init__(self, instrument_token: str | None = "pm_vaulted_1") -> None:
        self._instrument_token = instrument_token

    def authorize_delegation(self, *, mandate_id: str, checkout_id: str, merchant_id: str):
        return ApprovedPaymentContext(
            live_balance=Money(5_000, "BRL", 2),
            mandate_ceiling=Money(5_000, "BRL", 2),
            checkout_total=Money(5_000, "BRL", 2),
            merchant_id=merchant_id,
            checkout_id=checkout_id,
            expires_at=datetime(2026, 8, 30, tzinfo=UTC),
            instrument_token=self._instrument_token,
        )


def _delegate(authorizer: MockApprovedAuthorizer):
    return VaultService(
        authorizer=authorizer, tokenizer=OpaqueDelegationTokenMinter()
    ).delegate(
        mandate_id="mandate_1", checkout_id="checkout_42", merchant_id="merchant_aval"
    )


def test_the_delegation_boundary_cannot_be_handed_a_card_number() -> None:
    """Not "forgets it" — cannot be given one. The parameter no longer exists."""
    with pytest.raises(TypeError):
        VaultService(
            authorizer=MockApprovedAuthorizer(), tokenizer=OpaqueDelegationTokenMinter()
        ).delegate(
            mandate_id="mandate_1",
            checkout_id="checkout_42",
            merchant_id="merchant_aval",
            card_number="4242424242424242",
        )


def test_the_minted_handle_carries_nothing_about_the_card() -> None:
    minter = OpaqueDelegationTokenMinter()
    delegated = _delegate(MockApprovedAuthorizer())

    wire_payload = json.dumps(serialize_delegated_payment(delegated), sort_keys=True)

    assert "pm_vaulted_1" not in wire_payload
    assert repr(vars(minter)) == "{}"
    assert delegated.token.startswith("vt_")


def test_a_mandate_naming_no_card_has_nothing_to_delegate() -> None:
    """The hole this closed: the lane used to vault whatever card was typed at it."""
    with pytest.raises(DelegationRejected) as refused:
        _delegate(MockApprovedAuthorizer(instrument_token=None))

    assert refused.value.reason_code == "instrument_not_in_mandate"
