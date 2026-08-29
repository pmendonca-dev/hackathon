from __future__ import annotations


AP2_MANDATE_CAPABILITY = "dev.ucp.common.payment.ap2_mandate"


class UcpCheckoutError(ValueError):
    pass


class Ap2CheckoutLock:
    """Enforces the UCP AP2 security lock without making policy decisions."""

    def __init__(self, negotiated_capabilities: frozenset[str]) -> None:
        self._locked = AP2_MANDATE_CAPABILITY in negotiated_capabilities

    @property
    def locked(self) -> bool:
        return self._locked

    def require_completion(self, checkout_mandate: str | None) -> None:
        if self._locked and not checkout_mandate:
            raise UcpCheckoutError("mandate_required")
