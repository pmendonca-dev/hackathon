from __future__ import annotations

import asyncio
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta

import pytest

from aval.adapters.ap2.receipts import Ap2ReceiptIssuer, mandate_reference
from aval.api.routers.audit import create_audit_router
from aval.application.services.dispute import (
    DisputeEvidence,
    DisputeService,
    ReadableAuditEvent,
)
from aval.security.jws import verify_compact_jws
from aval.security.key_custody import KeyCustodyService, public_key_from_jwk


def _build_service(*, unknown_payment_reference: bool = False) -> tuple[DisputeService, ReadableAuditEvent]:
    committed_at = datetime(2026, 8, 29, 18, 0, tzinfo=UTC)
    custody = KeyCustodyService()
    custody.generate_es256("merchant-receipts")
    custody.generate_es256("psp-receipts")
    merchant_issuer = Ap2ReceiptIssuer(
        issuer="merchant_aval",
        custody=custody,
        kid="merchant-receipts",
        clock=lambda: committed_at,
    )
    psp_issuer = Ap2ReceiptIssuer(
        issuer="psp_mock",
        custody=custody,
        kid="psp-receipts",
        clock=lambda: committed_at,
    )
    closed_checkout = "closed-checkout-mandate"
    closed_payment = "unknown-payment-mandate" if unknown_payment_reference else "closed-payment-mandate"
    checkout_receipt = merchant_issuer.issue_checkout(
        closed_mandate=closed_checkout,
        order_id="order_1",
    )
    payment_receipt = psp_issuer.issue_payment(
        closed_mandate=closed_payment,
        payment_id="cap_1",
        psp_confirmation_id="psp_mock_123",
    )
    committed = ReadableAuditEvent(
        id="aud_1",
        mandate_id="mandate_1",
        event_type="reservation.committed",
        reason_code="authorized",
        human_summary="Reserva comprometida antes da liquidação.",
        actor="authorization_core",
        occurred_at=committed_at,
        evidence_hash="hash-proof",
        revocation_epoch=0,
    )
    revoked = ReadableAuditEvent(
        id="aud_2",
        mandate_id="mandate_1",
        event_type="mandate.revoked",
        reason_code="operator_revocation",
        human_summary="Mandato revogado para compras futuras.",
        actor="operator",
        occurred_at=committed_at + timedelta(seconds=1),
        evidence_hash="hash-revocation",
        revocation_epoch=1,
    )
    settled = ReadableAuditEvent(
        id="aud_3",
        mandate_id="mandate_1",
        event_type="capture.settled",
        reason_code="settled",
        human_summary="Captura liquidada pelo PSP mock.",
        actor="psp_mock",
        occurred_at=committed_at + timedelta(seconds=2),
        evidence_hash="hash-payment-receipt",
        revocation_epoch=0,
    )
    evidence = DisputeEvidence(
        mandate_id="mandate_1",
        open_mandate="open-mandate",
        revocation_authority="operator-key",
        checkout_jwt="checkout-jwt",
        checkout_hash=mandate_reference("checkout-jwt"),
        closed_checkout_mandate=closed_checkout,
        closed_payment_mandate="closed-payment-mandate",
        merchant_authorization="merchant-authorization",
        authorization_proof="authorization-proof",
        checkout_receipt=checkout_receipt,
        payment_receipt=payment_receipt,
        commit_point_at=committed_at,
        events=(committed, revoked, settled),
    )

    class MockEvidenceReader:
        def get(self, mandate_id: str) -> DisputeEvidence | None:
            return evidence if mandate_id == evidence.mandate_id else None

    service = DisputeService(
        reader=MockEvidenceReader(),
        checkout_receipt_verifier=lambda token: verify_compact_jws(
            token,
            public_key_from_jwk(custody.public_jwk("merchant-receipts")),
        ),
        payment_receipt_verifier=lambda token: verify_compact_jws(
            token,
            public_key_from_jwk(custody.public_jwk("psp-receipts")),
        ),
    )
    return service, committed


def test_audit_timeline_is_immutable_legible_and_explains_post_commit_revocation() -> None:
    service, committed = _build_service()

    verdict = service.reconstruct("mandate_1")

    assert verdict.status == "VALID"
    assert [event.id for event in verdict.timeline] == ["aud_1", "aud_2", "aud_3"]
    assert verdict.timeline[1].reason_code == "operator_revocation"
    assert verdict.timeline[1].human_summary == "Mandato revogado para compras futuras."
    assert "reversal, refund ou disputa" in verdict.post_commit_note
    with pytest.raises(FrozenInstanceError):
        committed.human_summary = "alterado"  # type: ignore[misc]


def test_audit_router_exposes_the_same_read_only_timeline() -> None:
    service, _ = _build_service()
    router = create_audit_router(service)
    endpoint = next(route.endpoint for route in router.routes if route.path == "/audit/mandates/{mandate_id}")

    response = asyncio.run(endpoint("mandate_1"))

    assert response["status"] == "VALID"
    assert response["timeline"][0]["actor"] == "authorization_core"

