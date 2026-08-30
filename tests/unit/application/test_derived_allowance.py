from __future__ import annotations

from datetime import UTC, datetime

import pytest

from aval.application.services.vault import derive_allowance
from aval.domain.money import Money


def test_allowance_is_derived_from_the_smallest_live_amount() -> None:
    allowance = derive_allowance(
        live_balance=Money(8_000, "BRL", 2),
        mandate_ceiling=Money(12_000, "BRL", 2),
        checkout_total=Money(9_500, "BRL", 2),
        merchant_id="merchant_aval",
        checkout_id="checkout_42",
        expires_at=datetime(2026, 8, 30, tzinfo=UTC),
    )

    assert allowance.max_amount == 8_000
    assert allowance.currency == "brl"
    assert allowance.checkout_session_id == "checkout_42"
    assert allowance.merchant_id == "merchant_aval"
    assert allowance.reason == "one_time"


def test_allowance_rejects_mixed_money_units() -> None:
    with pytest.raises(ValueError, match="currency and scale"):
        derive_allowance(
            live_balance=Money(8_000, "BRL", 2),
            mandate_ceiling=Money(12_000, "USD", 2),
            checkout_total=Money(9_500, "BRL", 2),
            merchant_id="merchant_aval",
            checkout_id="checkout_42",
            expires_at=datetime(2026, 8, 30, tzinfo=UTC),
        )
