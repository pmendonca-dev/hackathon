from __future__ import annotations

from decimal import Decimal

import pytest

from rail_selector import RailSelectionRequest, select_rail


def request(
    *,
    operation_type: str = "checkout",
    allowed_rails: tuple[str, ...] = ("ucp_ap2",),
    amount: object = "120.00",
    checkout_context: dict[str, object] | None = None,
    feature_flags: dict[str, object] | None = None,
) -> RailSelectionRequest:
    resolved_context = (
        {
            "checkout_id": "checkout-123",
            "merchant_id": "merchant-456",
            "currency": "USD",
            "ap2_version": "0.2",
        }
        if checkout_context is None
        else checkout_context
    )
    resolved_flags = (
        {
            "ucp_ap2_enabled": True,
            "acp_delegate_payment_enabled": False,
            "x402_enabled": False,
            "task_12_e2e_green": False,
        }
        if feature_flags is None
        else feature_flags
    )
    return RailSelectionRequest(
        operation_type=operation_type,
        mandate_allowed_rails=allowed_rails,
        amount=amount,
        checkout_context=resolved_context,
        feature_flags=resolved_flags,
    )


def test_selects_ucp_ap2_as_primary_checkout_rail() -> None:
    result = select_rail(request())

    assert result.status == "selected"
    assert result.checkout_rail == "ucp_ap2"
    assert result.credential_mode is None
    assert result.x402_status == "x402_disabled"
    assert result.reason_code == "UCP_AP2_SELECTED"


def test_acp_is_only_delegated_tokenization_alongside_ucp_ap2() -> None:
    result = select_rail(
        request(
            operation_type="delegate_payment",
            allowed_rails=("ucp_ap2", "acp_delegate_payment"),
            feature_flags={
                "ucp_ap2_enabled": True,
                "acp_delegate_payment_enabled": True,
                "x402_enabled": False,
                "task_12_e2e_green": False,
            },
        )
    )

    assert result.status == "selected"
    assert result.checkout_rail == "ucp_ap2"
    assert result.credential_mode == "acp_delegate_payment"
    assert result.reason_code == "UCP_AP2_WITH_ACP_DELEGATED_TOKENIZATION"


@pytest.mark.parametrize(
    "feature_flags",
    [
        {},
        {"x402_enabled": False, "task_12_e2e_green": False},
        {"x402_enabled": True, "task_12_e2e_green": True},
    ],
)
def test_x402_is_hard_disabled_while_task_12_is_not_green(
    feature_flags: dict[str, object],
) -> None:
    result = select_rail(
        request(
            operation_type="x402",
            allowed_rails=("x402",),
            amount="not-used-for-x402-block",
            checkout_context={"untrusted": "ignored"},
            feature_flags=feature_flags,
        )
    )

    assert result.status == "disabled"
    assert result.checkout_rail is None
    assert result.credential_mode is None
    assert result.x402_status == "x402_disabled"
    assert result.reason_code == "X402_BLOCKED_TASK12_NOT_GREEN"


def test_fails_closed_when_ucp_ap2_is_not_allowed() -> None:
    result = select_rail(request(allowed_rails=("acp_delegate_payment",)))

    assert result.status == "rejected"
    assert result.checkout_rail is None
    assert result.reason_code == "UCP_AP2_NOT_ALLOWED"


def test_fails_closed_when_ucp_ap2_feature_is_disabled() -> None:
    result = select_rail(
        request(
            feature_flags={
                "ucp_ap2_enabled": False,
                "acp_delegate_payment_enabled": False,
                "x402_enabled": False,
                "task_12_e2e_green": False,
            }
        )
    )

    assert result.status == "rejected"
    assert result.reason_code == "UCP_AP2_FEATURE_DISABLED"


def test_fails_closed_when_acp_delegation_is_not_allowed() -> None:
    result = select_rail(request(operation_type="delegate_payment"))

    assert result.status == "rejected"
    assert result.reason_code == "ACP_DELEGATE_PAYMENT_NOT_ALLOWED"


def test_fails_closed_when_acp_delegation_feature_is_disabled() -> None:
    result = select_rail(
        request(
            operation_type="delegate_payment",
            allowed_rails=("ucp_ap2", "acp_delegate_payment"),
        )
    )

    assert result.status == "rejected"
    assert result.reason_code == "ACP_DELEGATE_PAYMENT_FEATURE_DISABLED"


@pytest.mark.parametrize(
    "operation_type",
    ["", "refund", "UCP_AP2", None, ["checkout"], {"type": "checkout"}],
)
def test_unknown_operation_fails_closed(operation_type: object) -> None:
    result = select_rail(request(operation_type=operation_type))

    assert result.status == "rejected"
    assert result.reason_code == "UNSUPPORTED_OPERATION"


def test_unknown_mandate_rail_fails_closed() -> None:
    result = select_rail(request(allowed_rails=("ucp_ap2", "future_rail")))

    assert result.status == "rejected"
    assert result.reason_code == "UNKNOWN_MANDATE_RAIL"


@pytest.mark.parametrize(
    "amount",
    ["0", "-0.01", "NaN", "Infinity", "not-a-number", 1.1, None, True],
)
def test_invalid_amount_fails_closed(amount: object) -> None:
    result = select_rail(request(amount=amount))

    assert result.status == "rejected"
    assert result.reason_code == "INVALID_AMOUNT"


@pytest.mark.parametrize("amount", ["0.01", "999999999999.99", 42, Decimal("12.34")])
def test_valid_amount_is_only_validated_not_used_as_authorization(amount: object) -> None:
    result = select_rail(request(amount=amount))

    assert result.status == "selected"
    assert result.checkout_rail == "ucp_ap2"


@pytest.mark.parametrize(
    "checkout_context",
    [
        {},
        {"checkout_id": "checkout-123"},
        {
            "checkout_id": "checkout-123",
            "merchant_id": "merchant-456",
            "currency": "usd",
            "ap2_version": "0.2",
        },
        {
            "checkout_id": "checkout-123",
            "merchant_id": "merchant-456",
            "currency": "USD",
            "ap2_version": "0.1",
        },
    ],
)
def test_invalid_checkout_context_fails_closed(
    checkout_context: dict[str, object],
) -> None:
    result = select_rail(request(checkout_context=checkout_context))

    assert result.status == "rejected"
    assert result.reason_code == "INVALID_CHECKOUT_CONTEXT"


@pytest.mark.parametrize(
    "sensitive_key",
    ["pan", "card_number", "cvv", "token", "api_key", "private_key", "secret"],
)
def test_sensitive_checkout_input_is_rejected(sensitive_key: str) -> None:
    context = {
        "checkout_id": "checkout-123",
        "merchant_id": "merchant-456",
        "currency": "USD",
        "ap2_version": "0.2",
        "nested": {sensitive_key: "must-not-enter-selector"},
    }

    result = select_rail(request(checkout_context=context))

    assert result.status == "rejected"
    assert result.reason_code == "SENSITIVE_INPUT_REJECTED"
    assert "must-not-enter-selector" not in result.to_json()


def test_unknown_feature_flag_fails_closed() -> None:
    result = select_rail(
        request(
            feature_flags={
                "ucp_ap2_enabled": True,
                "experimental_magic": True,
            }
        )
    )

    assert result.status == "rejected"
    assert result.reason_code == "UNKNOWN_FEATURE_FLAG"


def test_non_boolean_feature_flag_fails_closed() -> None:
    result = select_rail(
        request(feature_flags={"ucp_ap2_enabled": "true"})
    )

    assert result.status == "rejected"
    assert result.reason_code == "INVALID_FEATURE_FLAG"


def test_same_request_produces_same_result_without_mutating_input() -> None:
    context = {
        "checkout_id": "checkout-123",
        "merchant_id": "merchant-456",
        "currency": "USD",
        "ap2_version": "0.2",
    }
    flags = {"ucp_ap2_enabled": True}
    selection_request = request(checkout_context=context, feature_flags=flags)

    first = select_rail(selection_request)
    second = select_rail(selection_request)

    assert first == second
    assert context == {
        "checkout_id": "checkout-123",
        "merchant_id": "merchant-456",
        "currency": "USD",
        "ap2_version": "0.2",
    }
    assert flags == {"ucp_ap2_enabled": True}
