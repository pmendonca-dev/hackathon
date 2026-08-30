from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation

from .models import RailSelectionRequest, RailSelectionResult


_SUPPORTED_OPERATIONS = frozenset({"checkout", "delegate_payment", "x402"})
_SUPPORTED_RAILS = frozenset({"ucp_ap2", "acp_delegate_payment", "x402"})
_SUPPORTED_FEATURE_FLAGS = frozenset(
    {
        "ucp_ap2_enabled",
        "acp_delegate_payment_enabled",
        "x402_enabled",
        "task_12_e2e_green",
    }
)
_SENSITIVE_KEYS = frozenset(
    {
        "api_key",
        "authorization",
        "card_number",
        "cvv",
        "pan",
        "private_key",
        "secret",
        "token",
    }
)


def select_rail(request: RailSelectionRequest) -> RailSelectionResult:
    """Select a checkout rail and optional credential mode deterministically.

    This interface performs no authorization, tokenization, persistence,
    network access, or side effect. Every unsupported input fails closed with a
    stable reason code. x402 is hard-disabled before caller-controlled feature
    flags are considered because Task 12 is not green.
    """

    if not isinstance(request, RailSelectionRequest):
        return RailSelectionResult.rejected("INVALID_REQUEST")

    operation_type = request.operation_type
    if not isinstance(operation_type, str):
        return RailSelectionResult.rejected("UNSUPPORTED_OPERATION")
    if operation_type == "x402":
        return RailSelectionResult.x402_disabled()
    if operation_type not in _SUPPORTED_OPERATIONS:
        return RailSelectionResult.rejected("UNSUPPORTED_OPERATION")

    allowed_rails = _validate_allowed_rails(request.mandate_allowed_rails)
    if allowed_rails is None:
        return RailSelectionResult.rejected("UNKNOWN_MANDATE_RAIL")

    feature_flags, feature_error = _validate_feature_flags(request.feature_flags)
    if feature_error is not None:
        return RailSelectionResult.rejected(feature_error)

    if _parse_positive_amount(request.amount) is None:
        return RailSelectionResult.rejected("INVALID_AMOUNT")

    context_error = _validate_checkout_context(request.checkout_context)
    if context_error is not None:
        return RailSelectionResult.rejected(context_error)

    if "ucp_ap2" not in allowed_rails:
        return RailSelectionResult.rejected("UCP_AP2_NOT_ALLOWED")
    if not feature_flags.get("ucp_ap2_enabled", False):
        return RailSelectionResult.rejected("UCP_AP2_FEATURE_DISABLED")

    if operation_type == "checkout":
        return RailSelectionResult.selected(reason_code="UCP_AP2_SELECTED")

    if "acp_delegate_payment" not in allowed_rails:
        return RailSelectionResult.rejected("ACP_DELEGATE_PAYMENT_NOT_ALLOWED")
    if not feature_flags.get("acp_delegate_payment_enabled", False):
        return RailSelectionResult.rejected("ACP_DELEGATE_PAYMENT_FEATURE_DISABLED")
    return RailSelectionResult.selected(
        reason_code="UCP_AP2_WITH_ACP_DELEGATED_TOKENIZATION",
        credential_mode="acp_delegate_payment",
    )


def _validate_allowed_rails(raw: object) -> frozenset[str] | None:
    if isinstance(raw, (str, bytes)) or not isinstance(raw, Sequence):
        return None
    if not all(isinstance(item, str) for item in raw):
        return None
    allowed_rails = frozenset(raw)
    if not allowed_rails.issubset(_SUPPORTED_RAILS):
        return None
    return allowed_rails


def _validate_feature_flags(raw: object) -> tuple[dict[str, bool], str | None]:
    if not isinstance(raw, Mapping):
        return {}, "INVALID_FEATURE_FLAG"
    if not all(isinstance(key, str) for key in raw):
        return {}, "UNKNOWN_FEATURE_FLAG"
    if not set(raw).issubset(_SUPPORTED_FEATURE_FLAGS):
        return {}, "UNKNOWN_FEATURE_FLAG"
    if not all(type(value) is bool for value in raw.values()):
        return {}, "INVALID_FEATURE_FLAG"
    return dict(raw), None


def _parse_positive_amount(raw: object) -> Decimal | None:
    if isinstance(raw, bool) or isinstance(raw, float) or raw is None:
        return None
    if not isinstance(raw, (str, int, Decimal)):
        return None
    if isinstance(raw, str) and not raw.strip():
        return None
    try:
        amount = raw if isinstance(raw, Decimal) else Decimal(raw)
    except (InvalidOperation, ValueError):
        return None
    if not amount.is_finite() or amount <= 0:
        return None
    return amount


def _validate_checkout_context(raw: object) -> str | None:
    if not isinstance(raw, Mapping):
        return "INVALID_CHECKOUT_CONTEXT"
    if _contains_sensitive_key(raw):
        return "SENSITIVE_INPUT_REJECTED"

    checkout_id = raw.get("checkout_id")
    merchant_id = raw.get("merchant_id")
    currency = raw.get("currency")
    ap2_version = raw.get("ap2_version")
    if not _is_nonempty_string(checkout_id) or not _is_nonempty_string(merchant_id):
        return "INVALID_CHECKOUT_CONTEXT"
    if (
        not isinstance(currency, str)
        or len(currency) != 3
        or not currency.isascii()
        or not currency.isalpha()
        or not currency.isupper()
    ):
        return "INVALID_CHECKOUT_CONTEXT"
    if ap2_version != "0.2":
        return "INVALID_CHECKOUT_CONTEXT"
    return None


def _contains_sensitive_key(value: object, seen: set[int] | None = None) -> bool:
    if seen is None:
        seen = set()
    value_id = id(value)
    if value_id in seen:
        return False
    seen.add(value_id)

    if isinstance(value, Mapping):
        for key, nested in value.items():
            if isinstance(key, str) and key.casefold() in _SENSITIVE_KEYS:
                return True
            if _contains_sensitive_key(nested, seen):
                return True
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return any(_contains_sensitive_key(item, seen) for item in value)
    return False


def _is_nonempty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())
