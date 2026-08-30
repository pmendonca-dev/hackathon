from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Mapping, Protocol

from aval.adapters.ap2.receipts import mandate_reference


@dataclass(frozen=True)
class ReadableAuditEvent:
    id: str
    mandate_id: str
    event_type: str
    reason_code: str
    human_summary: str
    actor: str
    occurred_at: datetime
    evidence_hash: str
    revocation_epoch: int


@dataclass(frozen=True)
class DisputeEvidence:
    mandate_id: str
    open_mandate: str
    revocation_authority: str
    checkout_jwt: str
    checkout_hash: str
    closed_checkout_mandate: str
    closed_payment_mandate: str
    merchant_authorization: str
    authorization_proof: str
    checkout_receipt: str
    payment_receipt: str
    commit_point_at: datetime
    events: tuple[ReadableAuditEvent, ...]


@dataclass(frozen=True)
class DisputeVerdict:
    status: str
    reason_code: str
    human_summary: str
    timeline: tuple[ReadableAuditEvent, ...]
    post_commit_note: str


class DisputeEvidenceReader(Protocol):
    def get(self, mandate_id: str) -> DisputeEvidence | None: ...


class DisputeService:
    """Reconstructs evidence without mutating the ledger, audit log, or policy."""

    def __init__(
        self,
        *,
        reader: DisputeEvidenceReader,
        checkout_receipt_verifier: Callable[[str], Mapping[str, object]],
        payment_receipt_verifier: Callable[[str], Mapping[str, object]],
    ) -> None:
        self._reader = reader
        self._checkout_receipt_verifier = checkout_receipt_verifier
        self._payment_receipt_verifier = payment_receipt_verifier

    def reconstruct(self, mandate_id: str) -> DisputeVerdict:
        evidence = self._reader.get(mandate_id)
        if evidence is None:
            return self._inconclusive(
                "evidence_not_found",
                "Dispute evidence not found.",
            )
        self._validate_timeline(evidence)
        required = (
            evidence.open_mandate,
            evidence.revocation_authority,
            evidence.closed_checkout_mandate,
            evidence.closed_payment_mandate,
            evidence.merchant_authorization,
            evidence.authorization_proof,
        )
        if not all(required):
            return self._inconclusive(
                "evidence_chain_incomplete",
                "The evidence chain is incomplete.",
                evidence,
            )
        if evidence.checkout_hash != mandate_reference(evidence.checkout_jwt):
            return self._inconclusive(
                "checkout_hash_mismatch",
                "The checkout hash does not match the JWT presented.",
                evidence,
            )
        try:
            checkout_receipt = self._checkout_receipt_verifier(evidence.checkout_receipt)
            payment_receipt = self._payment_receipt_verifier(evidence.payment_receipt)
        except ValueError:
            return self._inconclusive(
                "receipt_signature_invalid",
                "A receipt signature could not be validated.",
                evidence,
            )
        if checkout_receipt.get("reference") != mandate_reference(
            evidence.closed_checkout_mandate
        ):
            return self._inconclusive(
                "checkout_receipt_reference_unknown",
                "The checkout receipt reference does not match the mandate that was closed.",
                evidence,
            )
        if payment_receipt.get("reference") != mandate_reference(
            evidence.closed_payment_mandate
        ):
            return self._inconclusive(
                "payment_receipt_reference_unknown",
                "The payment receipt reference does not match the mandate that was closed.",
                evidence,
            )

        return DisputeVerdict(
            status="VALID",
            reason_code="evidence_chain_valid",
            human_summary="Mandate, authorization, commit and receipts validated as one chain.",
            timeline=evidence.events,
            post_commit_note=self._post_commit_note(evidence),
        )

    @staticmethod
    def _validate_timeline(evidence: DisputeEvidence) -> None:
        if any(event.mandate_id != evidence.mandate_id for event in evidence.events):
            raise ValueError("audit timeline contains another mandate")
        timestamps = tuple(event.occurred_at for event in evidence.events)
        if timestamps != tuple(sorted(timestamps)):
            raise ValueError("append-only audit timeline is out of order")

    @staticmethod
    def _post_commit_note(evidence: DisputeEvidence) -> str:
        revoked_after_commit = any(
            event.event_type == "mandate.revoked"
            and event.occurred_at > evidence.commit_point_at
            for event in evidence.events
        )
        if revoked_after_commit:
            return (
                "The revocation happened after the commit point and applies to future "
                "purchases; undoing this one needs a reversal, a refund or a dispute."
            )
        return "No revocation after the commit point was recorded."

    def _inconclusive(
        self,
        reason_code: str,
        human_summary: str,
        evidence: DisputeEvidence | None = None,
    ) -> DisputeVerdict:
        return DisputeVerdict(
            status="INCONCLUSIVE",
            reason_code=reason_code,
            human_summary=human_summary,
            timeline=() if evidence is None else evidence.events,
            post_commit_note="No automatic liability attribution was made.",
        )
