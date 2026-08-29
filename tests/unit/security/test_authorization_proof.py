from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from aval.domain.entities import Reservation
from aval.domain.money import Money
from aval.security.authorization_proof import AuthorizationProofService
from aval.security.key_custody import KeyCustodyService


def committed_reservation() -> Reservation:
    return Reservation(
        id="rsv_1",
        mandate_id="mandate_1",
        checkout_intent_id="checkout_1",
        amount=Money(500, "BRL", 2),
    ).commit("transaction_hash")


def test_proof_is_post_commit_short_lived_and_one_use():
    now = datetime(2026, 8, 29, tzinfo=UTC)
    custody = KeyCustodyService()
    custody.generate_es256("aval-proof")
    consumed: set[str] = set()
    service = AuthorizationProofService(
        clock=lambda: now,
        custody=custody,
        kid="aval-proof",
        consume_jti=lambda jti: not (jti in consumed or consumed.add(jti)),
    )

    proof = service.issue(committed_reservation(), policy_version=2, revocation_epoch=3)

    assert proof.expires_at == now + timedelta(seconds=60)
    assert service.verify_and_consume(
        proof.signed_proof, reservation=committed_reservation(), policy_version=2, revocation_epoch=3
    )["reservation_id"] == "rsv_1"
    with pytest.raises(ValueError, match="already used"):
        service.verify_and_consume(
            proof.signed_proof, reservation=committed_reservation(), policy_version=2, revocation_epoch=3
        )


def test_proof_rejects_pending_reservations_and_expired_tokens():
    now = datetime(2026, 8, 29, tzinfo=UTC)
    custody = KeyCustodyService()
    custody.generate_es256("aval-proof")
    service = AuthorizationProofService(
        clock=lambda: now, custody=custody, kid="aval-proof", consume_jti=lambda _jti: True
    )
    pending = Reservation("rsv_1", "mandate_1", "checkout_1", Money(500, "BRL", 2))

    with pytest.raises(ValueError, match="committed"):
        service.issue(pending, policy_version=1, revocation_epoch=0)

    proof = service.issue(committed_reservation(), policy_version=1, revocation_epoch=0)
    expired = AuthorizationProofService(
        clock=lambda: now + timedelta(seconds=61), custody=custody, kid="aval-proof", consume_jti=lambda _jti: True
    )
    with pytest.raises(ValueError, match="expired"):
        expired.verify_and_consume(
            proof.signed_proof, reservation=committed_reservation(), policy_version=1, revocation_epoch=0
        )
