from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Callable

from fastapi import FastAPI

from aval.adapters.ap2.mandates import ClosedCheckoutMandateVerifier
from aval.adapters.ap2.merchant_authorization import MerchantAuthorizationSigner, MerchantAuthorizationVerifier
from aval.adapters.ucp.http_signatures import Rfc9421Verifier
from aval.api.middleware.raw_body import RawBodyMiddleware
from aval.api.routers.ucp_checkout import create_ucp_checkout_router
from aval.api.routers.ucp_discovery import create_ucp_discovery_router
from aval.api.routers.delegate_payment import create_delegate_payment_router
from aval.api.routers.payment_capture import create_payment_capture_router
from aval.api.routers.audit import create_audit_router
from aval.application.authorization_core import AuthorizationCore
from aval.application.services.checkout import CheckoutService
from aval.application.services.delegation import CoreDelegationAuthorizer, DurableDelegationService
from aval.application.services.vault import VaultService
from aval.adapters.acp.delegate_payment import OpaqueTestCredentialTokenizer
from aval.adapters.settlement.mock_card_psp import MockCardPSP
from aval.application.services.payment_runtime import PaymentRuntime
from aval.application.services.receipts import ReceiptService
from aval.application.services.dispute import DisputeService
from aval.adapters.ap2.receipts import Ap2ReceiptIssuer
from aval.infrastructure.sqlite.dispute_evidence_reader import SqliteDisputeEvidenceReader
from aval.security.jws import verify_compact_jws
from aval.security.key_custody import public_key_from_jwk
from aval.infrastructure.sqlite.idempotency_repository import SqliteIdempotencyRepository
from aval.security.authorization_proof import AuthorizationProofService
from aval.domain.entities import AgentIdentity, Mandate, Principal, RevocationAuthority
from aval.domain.enums import RevocationRole
from aval.domain.money import Money
from aval.infrastructure.sqlite.agent_registry_repository import (
    SqliteAgentRegistryRepository,
    SqliteTrustedAgentRegistry,
)
from aval.infrastructure.sqlite.checkout_repository import SqliteCheckoutRepository
from aval.infrastructure.sqlite.mandate_repository import SqliteMandateRepository
from aval.infrastructure.sqlite.engine import create_sqlite_engine
from aval.infrastructure.sqlite.models import metadata
from aval.infrastructure.sqlite.transaction import run_in_write_transaction
from aval.security.key_custody import KeyCustodyService


@dataclass(frozen=True)
class AvalRuntime:
    custody: KeyCustodyService
    core: AuthorizationCore


def _now() -> datetime:
    return datetime.now(UTC)


def _seed_runtime(*, core: AuthorizationCore, custody: KeyCustodyService, engine, clock: Callable[[], datetime]) -> None:
    with engine.connect() as connection:
        mandate_exists = SqliteMandateRepository(connection).get("mandate_01") is not None
    if not mandate_exists:
        core.register_mandate(
            Mandate(
                id="mandate_01",
                principal=Principal("principal_01", "Marta"),
                allowed_merchant_ids=frozenset({"merchant_01"}),
                limit=Money(10_000, "BRL", 2),
                expires_at=clock() + timedelta(days=1),
                policy_version=1,
                revocation_metadata={"revocation_id": "revocation_01", "epoch": 0},
                authorities=(
                    RevocationAuthority(
                        id="authority_01",
                        kid="holder-key",
                        role=RevocationRole.HOLDER,
                        public_jwk=custody.public_jwk("holder-key"),
                        allowed_scopes=frozenset({"mandate"}),
                    ),
                ),
            ),
        )
    identities = (
        AgentIdentity("agent_01", "https://agent.aval.local/.well-known/ucp", custody.public_jwk("agent-key"), True),
        AgentIdentity("holder_01", "https://holder.aval.local/.well-known/ucp", custody.public_jwk("holder-key"), True),
        AgentIdentity("auditor_01", "https://auditor.aval.local/.well-known/ucp", custody.public_jwk("auditor-key"), True),
    )
    def seed_identities(connection) -> None:
        repository = SqliteAgentRegistryRepository(connection)
        for identity in identities:
            repository.put(identity)
    run_in_write_transaction(engine, seed_identities)


def create_app(
    *,
    database_path: Path | None = None,
    clock: Callable[[], datetime] = _now,
    custody: KeyCustodyService | None = None,
) -> FastAPI:
    database_path = database_path or Path(".aval") / "runtime.sqlite3"
    engine = create_sqlite_engine(database_path)
    metadata.create_all(engine)
    if custody is None:
        custody = KeyCustodyService()
        for key_id in ("merchant-key", "agent-key", "issuer-key", "holder-key", "auditor-key", "proof-key", "psp-key"):
            custody.generate_es256(key_id)
    proof_service = AuthorizationProofService(
        clock=clock, custody=custody, kid="proof-key",
        consume_jti=lambda jti: run_in_write_transaction(
            engine, lambda connection: SqliteIdempotencyRepository(connection).consume_once("authorization_proof", jti)
        ),
    )
    def verify_proof_for_psp(proof: str, reservation) -> object:
        claims = verify_compact_jws(proof, public_key_from_jwk(custody.public_jwk("proof-key")))
        return proof_service.verify_and_consume(
            proof, reservation=reservation,
            policy_version=int(claims["policy_version"]),
            revocation_epoch=int(claims["revocation_epoch"]),
        )

    psp = MockCardPSP(proof_verifier=verify_proof_for_psp)
    core = AuthorizationCore(
        clock=clock, engine=engine, settlement_adapter=psp,
        authorization_proof_issuer=proof_service,
    )
    _seed_runtime(core=core, custody=custody, engine=engine, clock=clock)
    checkout_service = CheckoutService(
        core=core,
        store=SqliteCheckoutRepository(engine),
        merchant_authorization=MerchantAuthorizationSigner(custody=custody, key_id="merchant-key"),
        merchant_authorization_verifier=MerchantAuthorizationVerifier(custody.public_jwk("merchant-key")),
        mandate_verifier=ClosedCheckoutMandateVerifier(
            issuer_jwk=custody.public_jwk("issuer-key"),
            holder_jwk=custody.public_jwk("holder-key"),
            clock=clock,
        ),
        clock=clock,
    )
    delegation_authorizer = CoreDelegationAuthorizer(
        core=core, checkouts=SqliteCheckoutRepository(engine)
    )
    delegation_service = DurableDelegationService(
        vault=VaultService(
            authorizer=delegation_authorizer, tokenizer=OpaqueTestCredentialTokenizer()
        ),
        engine=engine,
    )
    app = FastAPI(title="AVAL")
    app.state.runtime = AvalRuntime(custody=custody, core=core)
    app.add_middleware(RawBodyMiddleware)
    app.include_router(create_ucp_discovery_router(custody=custody, key_id="merchant-key"))
    agent_verifier = Rfc9421Verifier(SqliteTrustedAgentRegistry(engine))
    app.include_router(
        create_ucp_checkout_router(
            checkout_service,
            verifier=agent_verifier,
        )
    )
    app.include_router(create_delegate_payment_router(delegation_service, verifier=agent_verifier))
    receipt_service = ReceiptService(
        checkout_issuer=Ap2ReceiptIssuer(issuer="merchant_aval", custody=custody, kid="merchant-key", clock=clock),
        payment_issuer=Ap2ReceiptIssuer(issuer="psp_mock", custody=custody, kid="psp-key", clock=clock),
    )
    payment_runtime = PaymentRuntime(
        core=core, engine=engine, clock=clock, receipts=receipt_service,
        checkouts=SqliteCheckoutRepository(engine),
        merchant_authorization_verifier=MerchantAuthorizationVerifier(custody.public_jwk("merchant-key")),
        mandate_verifier=ClosedCheckoutMandateVerifier(
            issuer_jwk=custody.public_jwk("issuer-key"), holder_jwk=custody.public_jwk("holder-key"),
            clock=clock,
        ),
    )
    app.include_router(create_payment_capture_router(payment_runtime, verifier=agent_verifier))
    app.include_router(create_audit_router(DisputeService(
        reader=SqliteDisputeEvidenceReader(engine),
        checkout_receipt_verifier=lambda token: verify_compact_jws(token, public_key_from_jwk(custody.public_jwk("merchant-key"))),
        payment_receipt_verifier=lambda token: verify_compact_jws(token, public_key_from_jwk(custody.public_jwk("psp-key"))),
    ), verifier=agent_verifier, can_read=lambda identity_id, mandate_id: payment_runtime.can_read_mandate(
        identity_id=identity_id, mandate_id=mandate_id
    )))

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
