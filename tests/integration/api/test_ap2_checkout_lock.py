from __future__ import annotations

import pytest

from aval.adapters.ucp.ap2_extension import AP2_MANDATE_CAPABILITY, Ap2CheckoutLock, UcpCheckoutError


def test_negotiated_ap2_capability_blocks_completion_without_a_checkout_mandate() -> None:
    """Catches a downgrade from a negotiated AP2 checkout into an unprotected completion."""
    lock = Ap2CheckoutLock(frozenset({AP2_MANDATE_CAPABILITY}))

    assert lock.locked
    with pytest.raises(UcpCheckoutError, match="mandate_required"):
        lock.require_completion(None)
