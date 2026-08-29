from __future__ import annotations

from aval.domain.enums import AvalCheckoutStatus
from aval.domain.errors import DomainError


_UCP_STATUS_BY_AVAL_STATUS = {
    AvalCheckoutStatus.READY: "ready_for_complete",
    AvalCheckoutStatus.AWAITING_HUMAN: "requires_escalation",
    AvalCheckoutStatus.IN_PROGRESS: "complete_in_progress",
    AvalCheckoutStatus.COMPLETED: "completed",
    AvalCheckoutStatus.REJECTED: "canceled",
}

_ACP_STATUS_BY_AVAL_STATUS = {
    AvalCheckoutStatus.READY: "ready_for_payment",
    AvalCheckoutStatus.AWAITING_HUMAN: "requires_escalation",
    AvalCheckoutStatus.IN_PROGRESS: "complete_in_progress",
    AvalCheckoutStatus.COMPLETED: "completed",
    AvalCheckoutStatus.REJECTED: "canceled",
}


def to_ucp_status(status: AvalCheckoutStatus) -> str:
    try:
        return _UCP_STATUS_BY_AVAL_STATUS[status]
    except (KeyError, TypeError) as error:
        raise DomainError("unknown AVAL checkout status") from error


def to_acp_status(status: AvalCheckoutStatus) -> str:
    try:
        return _ACP_STATUS_BY_AVAL_STATUS[status]
    except (KeyError, TypeError) as error:
        raise DomainError("unknown AVAL checkout status") from error
