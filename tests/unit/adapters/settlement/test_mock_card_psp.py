from __future__ import annotations

from datetime import UTC, datetime

from aval.adapters.settlement.mock_card_psp import MockCardPSP
from aval.domain.entities import Reservation
from aval.domain.money import Money
from aval.security.authorization_proof import AuthorizationProofService
from aval.security.key_custody import KeyCustodyService


def test_psp_accepts_only_a_committed_reservation_with_a_valid_bound_proof() -> None:
    now = datetime(2026, 8, 29, tzinfo=UTC)
    custody = KeyCustodyService()
    custody.generate_es256("aval-proof")
    proof_service = AuthorizationProofService(
        clock=lambda: now,
        custody=custody,
        kid="aval-proof",
        consume_jti=lambda _jti: True,
    )
    pending = Reservation("rsv_1", "mandate_1", "checkout_1", Money(5_000, "BRL", 2))
    committed = pending.commit("transaction_hash")
    proof = proof_service.issue(committed, policy_version=3, revocation_epoch=2)
    verifier = lambda token, reservation: proof_service.verify_and_consume(
        token,
        reservation=reservation,
        policy_version=3,
        revocation_epoch=2,
    )
    psp = MockCardPSP(proof_verifier=verifier)

    assert psp.authorize(pending, proof.signed_proof).approved is False
    assert psp.authorize(committed, f"{proof.signed_proof}tampered").approved is False

    approved = psp.authorize(committed, proof.signed_proof)

    assert approved.approved is True
    assert approved.reference is not None
    assert approved.reference.startswith("psp_mock_")
