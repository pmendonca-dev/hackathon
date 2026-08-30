from __future__ import annotations

from datetime import UTC, datetime

import pytest

from aval.adapters.settlement.mock_card_psp import MockCardPSP
from aval.application.authorization_core import AuthorizationCore, CaptureCommand
from aval.domain.entities import Mandate, Principal, Reservation, RevocationAuthority
from aval.domain.enums import RevocationRole
from aval.domain.money import Money
from aval.infrastructure.sqlite.engine import create_sqlite_engine
from aval.infrastructure.sqlite.idempotency_repository import SqliteIdempotencyRepository
from aval.infrastructure.sqlite.models import metadata
from aval.infrastructure.sqlite.transaction import run_in_write_transaction
from aval.security.authorization_proof import AuthorizationProofService
from aval.security.jws import verify_compact_jws
from aval.security.key_custody import KeyCustodyService
from aval.security.key_custody import public_key_from_jwk


def test_authorization_proof_consumption_is_durable_and_checks_bindings(tmp_path):
    now = datetime(2026, 8, 29, tzinfo=UTC)
    engine = create_sqlite_engine(tmp_path / "proofs.db")
    metadata.create_all(engine)
    custody = KeyCustodyService()
    custody.generate_es256("proof-key")
    consume = lambda jti: run_in_write_transaction(
        engine, lambda connection: SqliteIdempotencyRepository(connection).consume_once("authorization_proof", jti)
    )
    issued_by = AuthorizationProofService(clock=lambda: now, custody=custody, kid="proof-key", consume_jti=consume)
    verified_by_new_instance = AuthorizationProofService(
        clock=lambda: now, custody=custody, kid="proof-key", consume_jti=consume
    )
    reservation = Reservation("rsv_1", "mandate_1", "checkout_1", Money(500, "BRL", 2)).commit("tx_hash")

    proof = issued_by.issue(reservation, policy_version=7, revocation_epoch=3)

    assert issued_by.verify_and_consume(
        proof.signed_proof,
        reservation=reservation,
        policy_version=7,
        revocation_epoch=3,
    )["amount"] == {"minor_units": 500, "currency": "BRL", "scale": 2}
    with pytest.raises(ValueError, match="already used"):
        verified_by_new_instance.verify_and_consume(
            proof.signed_proof,
            reservation=reservation,
            policy_version=7,
            revocation_epoch=3,
        )


def test_authorization_proof_rejects_a_valid_proof_with_different_bindings(tmp_path):
    now = datetime(2026, 8, 29, tzinfo=UTC)
    engine = create_sqlite_engine(tmp_path / "proof-bindings.db")
    metadata.create_all(engine)
    custody = KeyCustodyService()
    custody.generate_es256("proof-key")
    consume = lambda jti: run_in_write_transaction(
        engine, lambda connection: SqliteIdempotencyRepository(connection).consume_once("authorization_proof", jti)
    )
    service = AuthorizationProofService(clock=lambda: now, custody=custody, kid="proof-key", consume_jti=consume)
    reservation = Reservation("rsv_1", "mandate_1", "checkout_1", Money(500, "BRL", 2)).commit("tx_hash")
    proof = service.issue(reservation, policy_version=7, revocation_epoch=3)

    with pytest.raises(ValueError, match="binding"):
        service.verify_and_consume(
            proof.signed_proof,
            reservation=reservation,
            policy_version=8,
            revocation_epoch=3,
        )


def test_core_issued_proof_is_single_use_at_the_mock_psp_boundary(tmp_path):
    """The Core-to-PSP proof is internal and a captured proof cannot authorize the committed reservation twice."""
    now = datetime(2026, 8, 29, tzinfo=UTC)
    engine = create_sqlite_engine(tmp_path / "proof-psp.db")
    metadata.create_all(engine)
    custody = KeyCustodyService()
    custody.generate_es256("proof-key")
    custody.generate_es256("holder-key")
    consume = lambda jti: run_in_write_transaction(
        engine, lambda connection: SqliteIdempotencyRepository(connection).consume_once("authorization_proof", jti)
    )
    proof_service = AuthorizationProofService(clock=lambda: now, custody=custody, kid="proof-key", consume_jti=consume)

    def verify_for_psp(proof: str, reservation: Reservation):
        claims = verify_compact_jws(proof, public_key_from_jwk(custody.public_jwk("proof-key")))
        return proof_service.verify_and_consume(
            proof, reservation=reservation,
            policy_version=int(claims["policy_version"]), revocation_epoch=int(claims["revocation_epoch"]),
        )

    class RecordingPsp:
        def __init__(self) -> None:
            self.inner = MockCardPSP(proof_verifier=verify_for_psp)
            self.proof: str | None = None

        def authorize(self, reservation: Reservation, proof: str):
            self.proof = proof
            return self.inner.authorize(reservation, proof)

    psp = RecordingPsp()
    core = AuthorizationCore(
        clock=lambda: now, engine=engine, settlement_adapter=psp, authorization_proof_issuer=proof_service,
    )
    core.register_mandate(Mandate(
        "m1", Principal("p1", "Marta"), frozenset({"merchant"}), Money(1_000, "BRL", 2),
        datetime(2026, 8, 30, tzinfo=UTC), 1, {"revocation_id": "r1", "epoch": 0},
        (RevocationAuthority("a1", "holder-key", RevocationRole.HOLDER, custody.public_jwk("holder-key"), frozenset({"mandate"})),),
    ))

    result = core.capture(CaptureCommand("m1", "checkout", "merchant", Money(500, "BRL", 2), "capture-1"))

    assert result.approved is True
    assert result.reservation is not None
    assert psp.proof is not None
    assert psp.inner.authorize(result.reservation, psp.proof).approved is False
