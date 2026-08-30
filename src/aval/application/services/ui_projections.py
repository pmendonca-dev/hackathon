from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from aval.application.authorization_core import AuthorizationCore
from aval.application.services.dispute import DisputeService
from aval.application.services.ui_sessions import UiPrincipal
from aval.domain.entities import Mandate


HOLDER_PRINCIPAL_ID = "principal_01"

# Ledger summaries can contain display names or third-party supplied text. Browser
# output uses this closed vocabulary instead of reflecting those stored strings.
SAFE_EVENT_SUMMARIES = {
    "mandate_registered": "Mandate registered.",
    "mandate.revoked": "Mandate revoked.",
    "purchase_authorized": "Purchase authorized.",
    "purchase_committed": "Purchase committed.",
    "purchase_settled": "Payment settled.",
    "purchase_declined": "Payment declined.",
    "dispute_opened": "Dispute opened.",
    "dispute_resolved": "Dispute resolved.",
}


@dataclass(frozen=True)
class UiProjectionError(Exception):
    status_code: int
    code: str


class UiProjectionService:
    """Read-only browser views selected from the Core's durable facts."""

    def __init__(self, *, core: AuthorizationCore, disputes: DisputeService) -> None:
        self._core = core
        self._disputes = disputes

    def workspace(self, principal: UiPrincipal) -> dict[str, object]:
        mandates = [
            self._workspace_mandate(principal, mandate)
            for mandate in self._core.mandates()
            if self._can_list(principal, mandate)
        ]
        return {"role": principal.role, "mandates": mandates}

    def audit(self, principal: UiPrincipal, mandate_id: str) -> dict[str, object]:
        mandate = self._authorize_read(principal, mandate_id)
        return {
            "mandate_id": mandate.id,
            "timeline": [
                self._safe_timeline_entry(entry)
                for entry in self._core.timeline_for(mandate.id)
            ],
        }

    def dispute(self, principal: UiPrincipal, mandate_id: str) -> dict[str, object]:
        mandate = self._authorize_read(principal, mandate_id)
        verdict = self._disputes.reconstruct(mandate.id)
        return {
            "mandate_id": mandate.id,
            "status": verdict.status,
            "reason_code": verdict.reason_code,
            "human_summary": verdict.human_summary,
            "post_commit_note": verdict.post_commit_note,
            "timeline": [self._safe_timeline_entry(entry) for entry in verdict.timeline],
        }

    def _authorize_read(self, principal: UiPrincipal, mandate_id: str) -> Mandate:
        mandate = self._core.mandate(mandate_id)
        if mandate is None:
            raise UiProjectionError(404, "mandate_not_found")
        if principal.role == "merchant":
            # A multi-merchant mandate's shared timeline cannot be safely partitioned
            # by the current evidence reader, so do not expose any of it to one seller.
            if mandate.allowed_merchant_ids != frozenset({principal.merchant_id}):
                raise UiProjectionError(403, "ui_role_not_authorized")
        elif principal.role == "holder":
            if mandate.principal.id != HOLDER_PRINCIPAL_ID:
                raise UiProjectionError(403, "ui_role_not_authorized")
        elif principal.role != "auditor":
            raise UiProjectionError(403, "ui_role_not_authorized")
        return mandate

    @staticmethod
    def _can_list(principal: UiPrincipal, mandate: Mandate) -> bool:
        if principal.role == "merchant":
            return principal.merchant_id in mandate.allowed_merchant_ids
        if principal.role == "holder":
            return mandate.principal.id == HOLDER_PRINCIPAL_ID
        return principal.role in {"auditor", "operator"}

    def _workspace_mandate(self, principal: UiPrincipal, mandate: Mandate) -> dict[str, object]:
        result: dict[str, object] = {
            "mandate_id": mandate.id,
            "status": mandate.status.value.lower(),
        }
        if principal.role == "merchant":
            result["merchant_id"] = principal.merchant_id
        elif principal.role == "holder":
            snapshot = self._core.snapshot(mandate.id)
            assert snapshot is not None
            result.update(
                available_amount=snapshot.remaining.minor_units,
                currency=snapshot.remaining.currency,
            )
        return result

    @staticmethod
    def _safe_timeline_entry(entry) -> dict[str, object]:
        allowed_detail = {
            "agent_id",
            "checkout_id",
            "merchant_id",
            "category",
            "amount_minor_units",
            "currency",
            "scale",
            "decision",
            "reason_code",
            "reservation_id",
            "transaction_hash",
            "policy_version",
            "revocation_epoch",
            "settlement_reference",
            "scope",
            "authority_role",
            "status",
        }
        detail: dict[str, Any] = {
            key: value
            for key, value in dict(getattr(entry, "detail", {})).items()
            if key in allowed_detail
        }
        result: dict[str, object] = {
            "event_type": entry.event_type,
            "human_summary": SAFE_EVENT_SUMMARIES.get(entry.event_type, "Recorded audit event."),
            "occurred_at": entry.occurred_at.isoformat(),
            "detail": detail,
        }
        sequence = getattr(entry, "sequence", None)
        if sequence is not None:
            result["sequence"] = sequence
        return result
