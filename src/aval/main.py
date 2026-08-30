"""Server entrypoint — one app carrying both halves of the system.

    uvicorn aval.main:app --reload

Two lanes built against the same core meet here:

- the **protocol ingress** (UCP discovery and checkout, AP2 mandates and merchant
  authorization), mounted from `aval.api.routers`;
- the **authorization surfaces** (mandates, authorize, capture, escalations, ledger,
  merchant offers, the agent and the operator controls), mounted from `aval.api.app`.

Neither reimplements a decision. Both call `AuthorizationCore`, which stays the only
thing in the system that decides authority.

The database is a file by default so a restart does not erase the demo. Set
`AVAL_DATABASE_PATH=:memory:` for a throwaway instance — which is also what a judge
gets when the team resets between runs.

The operator surfaces (`/agents`, `/admin/psp`, `/reconcile`) need a token. Set
`AVAL_OPERATOR_TOKEN`; a default deployment starts closed rather than open.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from aval.adapters.ap2.mandates import ClosedCheckoutMandateVerifier
from aval.adapters.ap2.merchant_authorization import (
    MerchantAuthorizationSigner,
    MerchantAuthorizationVerifier,
)
from aval.adapters.ucp.http_signatures import Rfc9421Verifier
from aval.api.app import create_app as create_authorization_app
from aval.api.middleware.raw_body import RawBodyMiddleware
from aval.api.routers.audit import create_audit_router
from aval.api.routers.delegate_payment import create_delegate_payment_router
from aval.api.routers.payment_capture import create_payment_capture_router
from aval.api.routers.revocation import create_revocation_router
from aval.api.routers.ucp_checkout import create_ucp_checkout_router
from aval.api.routers.ucp_discovery import create_ucp_discovery_router
from aval.adapters.acp.delegate_payment import OpaqueTestCredentialTokenizer
from aval.adapters.ap2.receipts import Ap2ReceiptIssuer
from aval.application.services.checkout import CheckoutService
from aval.application.services.dispute import DisputeService
from aval.application.services.payment_runtime import PaymentRuntime
from aval.application.services.receipts import ReceiptService
from aval.application.services.delegation import (
    CoreDelegationAuthorizer,
    DurableDelegationService,
)
from aval.application.services.vault import VaultService
from aval.domain.entities import AgentIdentity, Mandate, Principal, RevocationAuthority
from aval.domain.enums import RevocationRole
from aval.domain.money import Money
from aval.infrastructure.sqlite.agent_registry_repository import (
    SqliteAgentRegistryRepository,
    SqliteTrustedAgentRegistry,
)
from aval.infrastructure.sqlite.checkout_repository import SqliteCheckoutRepository
from aval.infrastructure.sqlite.dispute_evidence_reader import SqliteDisputeEvidenceReader
from aval.infrastructure.sqlite.transaction import run_in_write_transaction
from aval.runtime import AvalRuntime, build_runtime
from aval.security.jws import verify_compact_jws
from aval.security.key_custody import KeyCustodyService, public_key_from_jwk

__all__ = ["app", "create_app", "database_path", "PROTOCOL_KEY_IDS"]

# The protocol lane signs and verifies with these four roles. They live in the runtime's
# custody so one process has one set of keys, whichever door a request arrives through.
# The roles the protocol lane signs and verifies with. `auditor-key` is a reader: it
# proves who is asking for a trail without ever authorizing a purchase.
PROTOCOL_KEY_IDS = (
    "merchant-key",
    "agent-key",
    "issuer-key",
    "holder-key",
    "auditor-key",
    "psp-key",
)

SEED_IDENTITIES = (
    ("agent_01", "https://agent.aval.local/.well-known/ucp", "agent-key"),
    ("holder_01", "https://holder.aval.local/.well-known/ucp", "holder-key"),
    ("auditor_01", "https://auditor.aval.local/.well-known/ucp", "auditor-key"),
)

SEED_MANDATE_ID = "mandate_01"


def _now() -> datetime:
    return datetime.now(UTC)


def _configured_database_path() -> Path | None:
    configured = os.environ.get("AVAL_DATABASE_PATH", "var/aval.db").strip()
    if configured.lower() in ("", ":memory:"):
        return None
    return Path(configured)


def database_path() -> Path | None:
    """Public accessor kept for the ASGI entrypoint and deployment tooling."""
    return _configured_database_path()


def _seed_protocol_fixtures(runtime: AvalRuntime, clock: Callable[[], datetime]) -> None:
    """The mandate and agent the protocol lane expects to find.

    Registration is idempotent in the core, so restarting against the same file re-reads
    them instead of duplicating them.
    """
    custody = runtime.custody
    runtime.core.register_mandate(
        Mandate(
            id=SEED_MANDATE_ID,
            principal=Principal("principal_01", "Marta"),
            allowed_merchant_ids=frozenset({"merchant_01"}),
            # A mandate must say what may be bought. The protocol fixture buys travel.
            allowed_categories=frozenset({"travel"}),
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
        )
    )
    identities = [
        AgentIdentity(
            id=identity_id,
            profile_url=profile_url,
            public_jwk=custody.public_jwk(key_id),
            trusted=True,
        )
        for identity_id, profile_url, key_id in SEED_IDENTITIES
    ]

    def seed_identities(connection) -> None:
        repository = SqliteAgentRegistryRepository(connection)
        for identity in identities:
            repository.put(identity)

    # Two registries, one set of identities: the protocol lane reads through its own
    # repository, the authorization edge through `agent_for_kid`. Writing both keeps a
    # single agent recognisable at either door.
    run_in_write_transaction(runtime.engine, seed_identities)
    for identity in identities:
        runtime.core.register_agent(identity)


def _mount_protocol_lane(app: FastAPI, runtime: AvalRuntime, clock: Callable[[], datetime]) -> None:
    custody = runtime.custody
    checkout_service = CheckoutService(
        core=runtime.core,
        store=SqliteCheckoutRepository(runtime.engine),
        merchant_authorization=MerchantAuthorizationSigner(custody=custody, key_id="merchant-key"),
        merchant_authorization_verifier=MerchantAuthorizationVerifier(
            custody.public_jwk("merchant-key")
        ),
        mandate_verifier=ClosedCheckoutMandateVerifier(
            issuer_jwk=custody.public_jwk("issuer-key"),
            holder_jwk=custody.public_jwk("holder-key"),
            clock=clock,
        ),
        clock=clock,
        engine=runtime.engine,
    )
    # The scoped payment credential: the agent is handed a token that works at this
    # merchant, for this checkout, up to this amount — never a card.
    delegation_service = DurableDelegationService(
        vault=VaultService(
            authorizer=CoreDelegationAuthorizer(
                core=runtime.core, checkouts=SqliteCheckoutRepository(runtime.engine)
            ),
            tokenizer=OpaqueTestCredentialTokenizer(),
        ),
        engine=runtime.engine,
    )
    # Two receipts, two issuers: the merchant attests what was sold, the processor what
    # was paid. A dispute is answered by reading both, not by trusting either.
    receipts = ReceiptService(
        checkout_issuer=Ap2ReceiptIssuer(
            issuer="merchant_aval", custody=custody, kid="merchant-key", clock=clock
        ),
        payment_issuer=Ap2ReceiptIssuer(
            issuer="psp_mock", custody=custody, kid="psp-key", clock=clock
        ),
    )

    # The capture reads its facts from the stored checkout, so it is handed the same
    # store and the same verifiers the checkout was created with.
    payment_runtime = PaymentRuntime(
        core=runtime.core,
        engine=runtime.engine,
        clock=clock,
        receipts=receipts,
        checkouts=SqliteCheckoutRepository(runtime.engine),
        merchant_authorization_verifier=MerchantAuthorizationVerifier(
            custody.public_jwk("merchant-key")
        ),
        mandate_verifier=ClosedCheckoutMandateVerifier(
            issuer_jwk=custody.public_jwk("issuer-key"),
            holder_jwk=custody.public_jwk("holder-key"),
            clock=clock,
        ),
    )
    # One verifier for every protocol door. Payment and audit are agent traffic too, so
    # they answer the same question the checkout does: is the caller who it claims to be.
    agent_verifier = Rfc9421Verifier(SqliteTrustedAgentRegistry(runtime.engine))

    # RFC 9421 over UCP needs the unparsed bytes, which FastAPI would otherwise consume.
    app.add_middleware(RawBodyMiddleware)
    app.include_router(create_ucp_discovery_router(custody=custody, key_id="merchant-key"))
    app.include_router(create_ucp_checkout_router(checkout_service, verifier=agent_verifier))
    app.include_router(create_delegate_payment_router(delegation_service, verifier=agent_verifier))
    app.include_router(create_payment_capture_router(payment_runtime, verifier=agent_verifier))
    app.include_router(create_revocation_router(runtime.core, verifier=agent_verifier))
    app.include_router(
        create_audit_router(
            DisputeService(
                reader=SqliteDisputeEvidenceReader(runtime.engine),
                checkout_receipt_verifier=lambda token: verify_compact_jws(
                    token, public_key_from_jwk(custody.public_jwk("merchant-key"))
                ),
                payment_receipt_verifier=lambda token: verify_compact_jws(
                    token, public_key_from_jwk(custody.public_jwk("psp-key"))
                ),
            ),
            verifier=agent_verifier,
            # An agent reads the trail of a mandate it actually took part in, and no
            # other. Authentication says who is asking; this says what they may see.
            can_read=lambda identity_id, mandate_id: payment_runtime.can_read_mandate(
                identity_id=identity_id, mandate_id=mandate_id
            ),
            mandate_exists=payment_runtime.mandate_exists,
        )
    )


def create_app(
    *,
    database_path: Path | None = None,
    clock: Callable[[], datetime] = _now,
    custody: KeyCustodyService | None = None,
) -> FastAPI:
    """Build the whole system: authorization surfaces plus protocol ingress.

    `custody` is accepted so a caller can restart against the same database and keep the
    keys it published — a verifier that trusted a key yesterday must still find it today.
    """
    runtime = build_runtime(
        database_path=database_path or _configured_database_path(),
        now_provider=clock,
        custody=custody,
        extra_key_ids=PROTOCOL_KEY_IDS,
    )
    app = create_authorization_app(runtime)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_: Request, __: RequestValidationError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": {"code": "request_invalid"}})

    _seed_protocol_fixtures(runtime, clock)
    _mount_protocol_lane(app, runtime, clock)
    return app


_runtime = build_runtime(database_path=database_path(), extra_key_ids=PROTOCOL_KEY_IDS)
app = create_authorization_app(_runtime)
_seed_protocol_fixtures(_runtime, _runtime.clock.now)
_mount_protocol_lane(app, _runtime, _runtime.clock.now)
