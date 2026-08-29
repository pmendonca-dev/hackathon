from __future__ import annotations

from datetime import UTC, datetime

import pytest

from aval.domain.entities import Reservation
from aval.domain.money import Money
from aval.infrastructure.sqlite.engine import create_sqlite_engine
from aval.infrastructure.sqlite.idempotency_repository import SqliteIdempotencyRepository
from aval.infrastructure.sqlite.models import metadata
from aval.infrastructure.sqlite.transaction import run_in_write_transaction
from aval.security.authorization_proof import AuthorizationProofService
from aval.security.key_custody import KeyCustodyService


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
