from __future__ import annotations

import pytest

from aval.domain.checkout_status import to_acp_status, to_ucp_status
from aval.domain.enums import AvalCheckoutStatus
from aval.domain.errors import DomainError


def test_each_aval_status_has_one_validated_ucp_projection():
    assert to_ucp_status(AvalCheckoutStatus.READY) == "ready_for_complete"
    assert to_ucp_status(AvalCheckoutStatus.AWAITING_HUMAN) == "requires_escalation"
    assert to_ucp_status(AvalCheckoutStatus.REJECTED) == "canceled"


def test_each_aval_status_has_one_validated_acp_projection():
    assert to_acp_status(AvalCheckoutStatus.READY) == "ready_for_payment"
    assert to_acp_status(AvalCheckoutStatus.AWAITING_HUMAN) == "requires_escalation"
    assert to_acp_status(AvalCheckoutStatus.REJECTED) == "canceled"


def test_unknown_checkout_status_is_rejected():
    with pytest.raises(DomainError):
        to_ucp_status("unknown")  # type: ignore[arg-type]
