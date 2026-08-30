"""Composition root.

Every collaborator the running system needs is built here, once, and handed to
the HTTP layer. Nothing below this line reaches for a global.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy import Engine, create_engine
from sqlalchemy.pool import StaticPool

from aval.application.authorization_core import AuthorizationCore
from aval.domain.entities import AgentIdentity
from aval.infrastructure.psp import DemoPspAdapter, PspControl
from aval.infrastructure.stripe_psp import StripeConfigError, StripePspAdapter
from aval.infrastructure.sqlite.engine import create_sqlite_engine
from aval.infrastructure.sqlite.idempotency_repository import SqliteIdempotencyRepository
from aval.infrastructure.sqlite.models import metadata
from aval.infrastructure.sqlite.transaction import run_in_write_transaction
from aval.merchant.catalog import MERCHANTS
from aval.merchant.offers import MerchantOfferService
from aval.security.authorization_proof import AuthorizationProofService
from aval.security.clock import ClockService
from aval.security.http_signature import ReplayGuard
from aval.security.jws import verify_compact_jws
from aval.security.key_custody import KeyCustodyService
from aval.observability.metrics import MetricsRegistry
from aval.security.pairwise import resolve_pairwise_secret

PROOF_KID = "aval-proof-k1"
DEMO_AGENT_ID = "agent_aval_demo"
DEMO_AGENT_KID = "agent-demo-k1"
DEMO_AGENT_PROFILE_URL = "https://agents.aval.local/agent_aval_demo"


def resolve_operator_token() -> str:
    """Return only an explicit local operator token; missing configuration is closed."""
    return os.environ.get("AVAL_OPERATOR_TOKEN", "").strip()


def resolve_operator_authority_seed() -> str | None:
    """The explicit server-only seed for the browser operator authority, if enabled."""
    value = os.environ.get("AVAL_OPERATOR_AUTHORITY_SEED", "").strip()
    return value or None


def resolve_custody_seed() -> str | None:
    """The one secret that makes this instance's keys survive a restart.

    Unset, every custody draws fresh keys — right for a clone with no configuration,
    and wrong for anything left running. The database outlives the process: it holds the
    agent's registered public key and the offers a merchant signed, so a second boot with
    new private keys signs with something nothing on disk recognises, and every purchase
    after it fails as `signature_invalid`.

    It deliberately does **not** cover `operator-key`. That key's existence grants an
    operator the authority to revoke a mandate, and an authority must be turned on by
    the variable that names it, never acquired as a side effect of wanting stable keys.
    """
    value = os.environ.get("AVAL_CUSTODY_SEED", "").strip()
    return value or None


@dataclass(frozen=True)
class AvalRuntime:
    engine: Engine
    clock: ClockService
    custody: KeyCustodyService
    proofs: AuthorizationProofService
    psp: DemoPspAdapter
    psp_control: PspControl
    core: AuthorizationCore
    replay_guard: ReplayGuard
    merchant_custody: KeyCustodyService
    offers: MerchantOfferService
    spent_offer_nonces: ReplayGuard
    agent_custody: KeyCustodyService
    agent_kid: str
    pairwise_secret: bytes
    metrics: MetricsRegistry
    operator_token: str


def _settlement_adapter(*, proof_verifier, mode_provider, mandate_for):
    """Which processor settles, chosen once and never silently.

    `AVAL_PSP=stripe` without a key is a startup failure, not a quiet fall back to the
    demo adapter: a system that says it takes real payments and then mocks them is
    worse than one that refuses to start, because nobody finds out until the money
    was supposed to move.
    """
    selected = os.environ.get("AVAL_PSP", "demo").strip().lower()
    if selected in ("", "demo"):
        return DemoPspAdapter(mode_provider, proof_verifier=proof_verifier)
    if selected != "stripe":
        raise StripeConfigError(f"AVAL_PSP={selected!r} não é um processador conhecido")
    key = os.environ.get("AVAL_STRIPE_SECRET_KEY", "").strip()
    if not key:
        raise StripeConfigError("AVAL_PSP=stripe exige AVAL_STRIPE_SECRET_KEY")
    if key.startswith("sk_live_"):
        # A hackathon demo has no business holding a live key, and a judge pressing
        # buttons on someone's real account is not a scenario worth supporting.
        raise StripeConfigError("chave de produção recusada: use uma chave sk_test_")
    return StripePspAdapter(
        secret_key=key, mandate_for=mandate_for, proof_verifier=proof_verifier
    )


def build_runtime(
    *,
    database_path: Path | None = None,
    now_provider: Callable[[], datetime] | None = None,
    operator_token: str | None = None,
    custody: KeyCustodyService | None = None,
    extra_key_ids: tuple[str, ...] = (),
) -> AvalRuntime:
    """Wire the system. Without a path the database is in memory, which is what the
    tests want and what a judge resetting the demo gets."""
    clock = ClockService(now_provider=now_provider)
    engine = (
        create_sqlite_engine(database_path)
        if database_path is not None
        else create_engine(
            "sqlite+pysqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    )
    # A caller may hand in custody it already published: a verifier that trusted a
    # key yesterday must still find that key after a restart.
    # The core refuses to create a schema on an engine it was handed: migrations own the
    # database, not the application. The composition root is where that schema is put in
    # place, which is what main's own entrypoint did before this was factored out.
    metadata.create_all(engine)
    custody = custody or KeyCustodyService()
    operator_authority_seed = resolve_operator_authority_seed()
    custody_seed = resolve_custody_seed()

    def install(target: KeyCustodyService, key_id: str, *, domain: str) -> None:
        """Seeded when the operator kept a seed, freshly drawn otherwise."""
        if target.has(key_id):
            return
        if custody_seed is not None:
            target.derive_es256(key_id, secret=custody_seed, domain=domain)
        else:
            target.generate_es256(key_id)

    for key_id in (PROOF_KID, *extra_key_ids):
        if key_id == "operator-key" and not custody.has(key_id):
            if operator_authority_seed is not None:
                custody.derive_es256_from_secret(key_id, operator_authority_seed)
            continue
        install(custody, key_id, domain="protocol")
    # One-use proofs, remembered in the database rather than in this process: a proof
    # spent before a restart must still be spent after one.
    def consume_proof_jti(jti: str) -> bool:
        return run_in_write_transaction(
            engine,
            lambda connection: SqliteIdempotencyRepository(connection).consume_once(
                "authorization_proof", jti
            ),
        )

    proofs = AuthorizationProofService(
        clock=clock.now, custody=custody, kid=PROOF_KID, consume_jti=consume_proof_jti
    )
    # Kept in its own custody: the seller signs offers, AVAL signs authorizations,
    # and neither can produce the other side of the exchange.
    merchant_custody = KeyCustodyService()
    for merchant_kid in MERCHANTS.values():
        install(merchant_custody, merchant_kid, domain="merchant")
    psp_control = PspControl()

    def verify_proof_for_settlement(proof: str, reservation) -> None:
        """Check the proof the core issued, without spending it.

        Consumption belongs to the merchant, which presents the token once to claim the
        goods. A processor that burned the jti here would settle the payment and leave
        the merchant unable to verify the very sale it just took part in.
        """
        claims = verify_compact_jws(proof, custody.verifying_key(PROOF_KID))
        if (
            claims.get("reservation_id") != reservation.id
            or claims.get("transaction_hash") != reservation.transaction_hash
        ):
            raise ValueError("authorization proof does not bind this reservation")

    core = AuthorizationCore(
        clock=clock.now, engine=engine, authorization_proof_issuer=proofs
    )
    psp = _settlement_adapter(
        proof_verifier=verify_proof_for_settlement,
        mode_provider=lambda: psp_control.mode,
        mandate_for=core.mandate,
    )
    core.attach_settlement_adapter(psp)
    # The agent gets a key of its own. Agent identity and human identity are separate
    # things in this system, and this is where that separation starts.
    agent_custody = KeyCustodyService()
    install(agent_custody, DEMO_AGENT_KID, domain="agent")
    core.register_agent(
        AgentIdentity(
            id=DEMO_AGENT_ID,
            profile_url=DEMO_AGENT_PROFILE_URL,
            public_jwk=agent_custody.public_jwk(DEMO_AGENT_KID),
            trusted=True,
        )
    )
    return AvalRuntime(
        engine=engine,
        clock=clock,
        custody=custody,
        proofs=proofs,
        psp=psp,
        psp_control=psp_control,
        core=core,
        replay_guard=ReplayGuard(),
        merchant_custody=merchant_custody,
        offers=MerchantOfferService(clock=clock.now, custody=merchant_custody),
        spent_offer_nonces=ReplayGuard(retain_seconds=24 * 3600),
        agent_custody=agent_custody,
        agent_kid=DEMO_AGENT_KID,
        pairwise_secret=resolve_pairwise_secret(),
        metrics=MetricsRegistry(),
        operator_token=operator_token or resolve_operator_token(),
    )
