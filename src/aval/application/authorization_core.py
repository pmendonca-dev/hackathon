from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any
import base64
import hashlib
import json
from uuid import uuid4

from sqlalchemy import Engine, create_engine, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import StaticPool

from aval.application.ports import AuthorizationProofIssuer, SettlementAdapter
from aval.domain.entities import (
    AgentIdentity,
    Dispute,
    Escalation,
    Mandate,
    Reservation,
    Revocation,
)
from aval.domain.enums import (
    AuthorizationDecision,
    DisputeStatus,
    EscalationStatus,
    MandateStatus,
    ReservationStatus,
    RevocationRole,
)
from aval.domain.money import Money
from aval.security.jws import verify_compact_jws
from aval.security.key_custody import public_key_from_jwk
from aval.infrastructure.sqlite.mandate_repository import SqliteMandateRepository
from aval.infrastructure.sqlite.models import (
    authorization_proofs,
    capture_attempts,
    checkout_intents,
    disputes,
    escalations,
    mandate_creation_proofs,
    metadata,
    reservations,
    revocations,
)
from aval.infrastructure.sqlite.agent_repository import SqliteAgentProfileRepository
from aval.infrastructure.sqlite.audit_ledger import LedgerEntry, SqliteAuditLedger, verify_chain
from aval.infrastructure.sqlite.escalation_repository import SqliteEscalationRepository
from aval.infrastructure.sqlite.ledger_repository import SqliteLedgerRepository
from aval.infrastructure.sqlite.idempotency_repository import SqliteIdempotencyRepository
from aval.infrastructure.sqlite.capture_repository import SqliteCaptureRepository
from aval.infrastructure.sqlite.policy_repository import SqlitePolicyRepository
from aval.infrastructure.sqlite.revocation_repository import SqliteRevocationRepository
from aval.infrastructure.sqlite.lock_repository import SqliteMandateLockRepository
from aval.infrastructure.sqlite.transaction import run_in_write_transaction


# Only these three refusals are a question for a person. The others are answers.
# A ceiling, a revocation, an expiry and a malformed amount are not negotiable, and
# offering an approve button beside them would be a lie about what the mandate says.
# Every reason the ladder answers with AWAITING_HUMAN has to appear here, or the holder
# taps Aprovar, the escalation closes as APPROVED, and the resumed capture is refused by
# the very rung that opened it — a purchase that can never complete and can never be
# retried. What is *not* approvable must be REJECTED on the ladder instead of escalated:
# the ceiling, a mandate revocation, an expiry and a broken amount are refusals, and they
# are deliberately absent from this set because they never reach it.
APPROVABLE_REASONS = frozenset(
    {
        "merchant_out_of_scope",
        "category_not_allowed",
        "budget_exceeded",
        # Authority over *how often*, the way the budget is authority over *how much*.
        # A human may say yes to a fourth purchase.
        "usage_limit_exceeded",
        # `budget:zero` is the scope a holder picks when they want spending frozen but
        # not the agent killed — so the holder who froze it is the one who may still
        # wave a single purchase through. Revoking the mandate itself remains the hard
        # stop, and it is refused, never escalated.
        "budget_revoked",
    }
)

ESCALATION_WINDOW = timedelta(hours=1)


class ApprovalError(Exception):
    """A refusal to act on an escalation, carrying the answer the edge should give."""

    def __init__(self, status_code: int, reason_code: str, human_summary: str) -> None:
        super().__init__(reason_code)
        self.status_code = status_code
        self.reason_code = reason_code
        self.human_summary = human_summary


@dataclass(frozen=True)
class AuthorizationCommand:
    mandate_id: str
    checkout_id: str
    merchant_id: str
    total: Money
    category: str


@dataclass(frozen=True)
class CaptureCommand(AuthorizationCommand):
    idempotency_key: str
    # `terms_hash` and `canonical_offer` bind the purchase to the merchant's signed
    # offer; `instrument_id` names the scoped payment credential. They answer different
    # questions — what was sold, and what pays for it — so both travel here.
    terms_hash: str | None = None
    canonical_offer: str | None = None
    instrument_id: str | None = None
    idempotency_fingerprint: str | None = None


@dataclass(frozen=True)
class EvaluationStep:
    """One rung of the authorization ladder, and what it compared.

    The ladder is walked in a fixed order and stops at the first failure, so a trace
    that ends at `mandate_not_revoked` is proof that no money check was ever consulted.
    That is the property the whole design rests on; publishing the steps is what turns
    it from a claim into something a reader can check.
    """

    check: str
    passed: bool
    detail: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {"check": self.check, "passed": self.passed, "detail": self.detail}


@dataclass(frozen=True)
class AuthorizationResult:
    decision: AuthorizationDecision
    reason_code: str
    human_summary: str
    escalation_id: str | None = None
    # Carries the live limit, ceiling and spend, so it is for the holder and the
    # auditor. It must never be projected into the merchant view.
    trace: tuple[EvaluationStep, ...] = ()


@dataclass(frozen=True)
class SettlementResult:
    approved: bool
    reference: str | None = None


@dataclass(frozen=True)
class MandateSnapshot:
    """What a mandate is worth right now.

    `limit` is the *active* policy limit, not the one the mandate was born with, so a
    judge who moves the limit sees the budget move with it on the very next read.
    """

    mandate: Mandate
    limit: Money
    spent: Money
    # Uses already consumed inside the frequency window, read at the same instant
    # as the spend so a listing cannot show a budget and a count from two moments.
    uses_in_window: int = 0
    # Whether the card the mandate names has been cancelled. The mandate keeps its
    # instrument — rewriting it would erase what the holder actually authorized — so
    # the revocation is a separate fact, and a view that does not carry it advertises
    # a card every purchase is about to be refused for.
    instrument_revoked: bool = False

    @property
    def remaining(self) -> Money:
        return self.limit.subtract(self.spent)


@dataclass(frozen=True)
class CaptureResult:
    approved: bool
    reason_code: str
    reservation: Reservation | None = None
    settlement_reference: str | None = None
    escalation_id: str | None = None
    authorization_proof: str | None = None
    # True when this result was replayed from a completed idempotency record rather than
    # computed now. The outcome is identical by construction; only the caller's framing
    # differs, and a protocol that advertises replays needs to know which it is.
    replayed: bool = False


@dataclass(frozen=True)
class LiveAuthorizationContext:
    """Current Core facts safe to project into a short-lived edge allowance."""

    mandate_ceiling: Money
    live_balance: Money
    expires_at: datetime


@dataclass(frozen=True)
class RevocationResult:
    mandate_id: str | None
    reason_code: str | None = None
    replayed: bool = False


class AuthorizationCore:
    """The sole writer for the in-process authorization state used by the MVP."""

    def __init__(
        self,
        *,
        clock: Callable[[], datetime],
        engine: Engine | None = None,
        settlement_adapter: SettlementAdapter | None = None,
        authorization_proof_issuer: AuthorizationProofIssuer | None = None,
        max_live_reservations: int = 3,
    ) -> None:
        self._clock = clock
        self._max_live_reservations = max_live_reservations
        if engine is None:
            self._engine = create_engine(
                "sqlite+pysqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
            )
            metadata.create_all(self._engine)
        else:
            self._engine = engine
        self._settlement_adapter = settlement_adapter
        self._authorization_proof_issuer = authorization_proof_issuer

    def register_mandate(self, mandate: Mandate, *, creation_proof: str | None = None) -> None:
        """Write a mandate into existence, with the holder's signature over its terms.

        `creation_proof` is a compact JWS ES256 by a holder authority *of this mandate*
        over the terms it is born with. It is verified against the very authorities
        being registered — the key that will be able to revoke tomorrow is the key that
        authorizes existence today — and it is verified before a single row is written,
        so a refused creation leaves nothing behind.

        Without it the trail could prove the agent stayed inside the mandate and could
        not prove the person created it: naming a principal is not holding their key,
        and an operator able to mint mandates in someone else's name would be an
        operator able to spend other people's money by writing a row.

        `creation_proof=None` is the in-process path the core's own tests use, the same
        seam `replace_live_limit` has. Every HTTP caller goes through the signed path.
        """

        def operation(connection) -> None:
            proof: dict[str, Any] | None = None
            if creation_proof is not None:
                proof = self._verified_creation(creation_proof, mandate)
            policies = SqlitePolicyRepository(connection)
            if policies.latest_version(mandate.id) is not None:
                # Registering is creation, not update. Writing the row again would reset
                # whatever the mandate has become since — its status, its epoch, and its
                # expiry above all: a process that re-seeds on every start would quietly
                # keep a mandate alive forever. Limits move through the signed live-policy
                # path; revocation is irreversible by design.
                return
            SqliteMandateRepository(connection).put(mandate)
            # The limit a mandate is born with is policy version 1. Recording it keeps the
            # version meaningful from the first decision: without this row the first live
            # change would also land on version 1, and nothing downstream could tell the
            # two policies apart.
            policies.record(mandate.id, mandate.limit, mandate.policy_version)
            if proof is not None:
                # Inside the same transaction as the mandate, so a nonce that loses the
                # race takes the mandate down with it. The unique index is what makes a
                # captured creation single-use; checking first and inserting later would
                # leave the window this is written to close.
                try:
                    connection.execute(
                        mandate_creation_proofs.insert().values(
                            mandate_id=mandate.id,
                            kid=proof["kid"],
                            nonce=proof["nonce"],
                            signed_jws=creation_proof,
                            created_at=self._clock(),
                        )
                    )
                except IntegrityError as error:
                    raise ApprovalError(
                        409,
                        "mandate_creation_replayed",
                        "Esta autorização de criação já foi usada.",
                    ) from error
            SqliteAuditLedger(connection).append(
                mandate_id=mandate.id,
                event_type="mandate_registered",
                human_summary=f"Mandato criado por {mandate.principal.display_name}.",
                actor=f"principal:{mandate.principal.id}",
                detail={
                    "allowed_merchant_ids": sorted(mandate.allowed_merchant_ids),
                    "allowed_categories": sorted(mandate.allowed_categories),
                    "limit_minor_units": mandate.limit.minor_units,
                    "currency": mandate.limit.currency,
                    "scale": mandate.limit.scale,
                    "ceiling_minor_units": None
                    if mandate.ceiling is None
                    else mandate.ceiling.minor_units,
                    "expires_at": mandate.expires_at.astimezone(UTC).isoformat(),
                    "policy_version": mandate.policy_version,
                    # Position 0 of the chain carries the signature the whole mandate
                    # hangs from. An auditor reading the trail from the top starts at
                    # the holder's own consent, not at someone's claim about it.
                    "creation_proof": creation_proof,
                    "creation_kid": None if proof is None else proof["kid"],
                },
                occurred_at=self._clock(),
            )

        run_in_write_transaction(self._engine, operation)

    def configure_operator_revocation_authority(self, mandate_id: str, authority: RevocationAuthority) -> None:
        """Apply explicit server operator-key configuration without rewriting a mandate."""
        if authority.role is not RevocationRole.OPERATOR or authority.allowed_scopes != frozenset({"mandate"}):
            raise ValueError("invalid operator revocation authority")

        def operation(connection) -> None:
            mandates = SqliteMandateRepository(connection)
            mandate = mandates.get(mandate_id)
            if mandate is None:
                raise ValueError("mandate not found")
            current = next((item for item in mandate.authorities if item.id == authority.id), None)
            if current == authority:
                return
            mandates.upsert_authority(mandate.id, authority)
            SqliteAuditLedger(connection).append(
                mandate_id=mandate.id,
                event_type="operator_authority.configured",
                human_summary="Operator revocation authority configured.",
                actor="system:key_custody",
                detail={"authority_role": authority.role.value},
                occurred_at=self._clock(),
            )

        run_in_write_transaction(self._engine, operation)

    def register_agent(self, identity: AgentIdentity) -> None:
        run_in_write_transaction(
            self._engine, lambda connection: SqliteAgentProfileRepository(connection).put(identity)
        )

    def agent_for_profile_url(self, profile_url: str) -> AgentIdentity | None:
        with self._engine.connect() as connection:
            return SqliteAgentProfileRepository(connection).find_by_profile_url(profile_url)

    def agent_for_kid(self, kid: str) -> AgentIdentity | None:
        with self._engine.connect() as connection:
            return SqliteAgentProfileRepository(connection).find_by_kid(kid)

    def mandate(self, mandate_id: str) -> Mandate | None:
        """Read-only view for the surfaces. Reads never go through the writer lock."""
        with self._engine.connect() as connection:
            return SqliteMandateRepository(connection).get(mandate_id)

    def mandates(self) -> list[Mandate]:
        """Read-only mandate state for the already-authenticated BFF projections."""
        with self._engine.connect() as connection:
            return SqliteMandateRepository(connection).all()

    def replace_live_limit(
        self, mandate_id: str, limit: Money, *, authorization_jws: str | None = None
    ) -> None:
        """Move the live budget.

        Raising a limit is raising how much of someone else's money an agent may spend,
        so it is proved the same way a revocation is: with the holder's own key over a
        payload that names this mandate and this exact amount. An operator credential is
        deliberately not accepted here — running the service is not the same as owning
        the mandate.

        The payload also names the `policy_version` it supersedes, and that is what makes
        it single-use. A revocation is irreversible, so replaying one changes nothing; a
        limit change is *reversible*, so without a version binding a captured JWS for an
        old, higher limit could be replayed to undo the holder lowering it — the exact
        move the trial by fire asks a judge to make. Versions only go up, so a token
        signed against version N is dead the moment version N+1 exists.

        `authorization_jws=None` is the in-process path used by the core's own tests and
        by trusted callers that have already established authority; every HTTP caller
        goes through the signed path.
        """

        def operation(connection) -> None:
            mandate = SqliteMandateRepository(connection).get(mandate_id)
            if mandate is None:
                raise ValueError("mandate not found")
            if authorization_jws is not None:
                claims = self._verified_approval(
                    authorization_jws, mandate, kind="limit_change"
                )
                if claims.get("mandate_id") != mandate_id:
                    raise ApprovalError(
                        403, "limit_change_mandate_mismatch", "A autorização não é deste mandato."
                    )
                signed_unit = (
                    claims.get("limit_minor_units"),
                    claims.get("currency"),
                    claims.get("scale"),
                )
                if signed_unit != (limit.minor_units, limit.currency, limit.scale):
                    raise ApprovalError(
                        403, "limit_change_amount_mismatch", "O limite assinado não confere."
                    )
                # The version the holder was looking at when they signed. Anything else
                # is a token from before some other change — replaying it would move the
                # budget back to a limit the holder has already left behind.
                if claims.get("policy_version") != mandate.policy_version:
                    raise ApprovalError(
                        403,
                        "limit_change_version_stale",
                        "A autorização foi assinada sobre uma política anterior.",
                    )
            version = SqlitePolicyRepository(connection).replace_limit(mandate_id, limit)
            metadata = dict(mandate.revocation_metadata)
            metadata["epoch"] = int(metadata.get("epoch", 0)) + 1
            SqliteMandateRepository(connection).put(
                replace(mandate, policy_version=version, revocation_metadata=metadata)
            )
            SqliteAuditLedger(connection).append(
                mandate_id=mandate_id,
                event_type="mandate_limit_replaced",
                human_summary="Limite vivo do mandato alterado.",
                actor=(
                    f"principal:{mandate.principal.id}"
                    if authorization_jws is not None
                    else "operator:live_policy"
                ),
                detail={
                    "limit_minor_units": limit.minor_units,
                    "currency": limit.currency,
                    "scale": limit.scale,
                    "policy_version": version,
                    "epoch": int(metadata["epoch"]),
                },
                occurred_at=self._clock(),
            )
        run_in_write_transaction(self._engine, operation)

    def submit_signed_revocation(self, token: str) -> None:
        run_in_write_transaction(
            self._engine, lambda connection: self._submit_signed_revocation(connection, token)
        )

    def submit_signed_revocation_idempotent(
        self,
        *,
        mandate_id: str,
        token: str,
        idempotency_key: str,
        authenticated_kid: str | None,
        idempotency_scope: str = "mandate_revocation",
        idempotency_fingerprint: str | None = None,
    ) -> RevocationResult:
        """Apply a registered authority's JWS once, retaining the stable response durably."""
        request_hash = idempotency_fingerprint or hashlib.sha256(
            json.dumps({"mandate_id": mandate_id, "signed_revocation": token}, sort_keys=True).encode()
        ).hexdigest()

        def operation(connection) -> RevocationResult:
            idem = SqliteIdempotencyRepository(connection)
            try:
                claim = idem.get_or_claim(idempotency_scope, idempotency_key, request_hash)
            except Exception:
                return RevocationResult(None, "idempotency_unavailable")
            if claim.state == "REPLAY":
                return self._deserialize_revocation_result(claim.response_body, replayed=True)
            if claim.state == "MISMATCH":
                return RevocationResult(None, "idempotency_key_reused")
            if claim.state == "IN_FLIGHT":
                return RevocationResult(None, "idempotency_in_flight")
            try:
                revoked_mandate_id = self._submit_signed_revocation(
                    connection,
                    token,
                    expected_mandate_id=mandate_id,
                    authenticated_kid=authenticated_kid,
                )
                result = RevocationResult(revoked_mandate_id)
            except ValueError as error:
                result = RevocationResult(None, self._stable_revocation_error(str(error)))
            idem.complete(idempotency_scope, idempotency_key, self._serialize_revocation_result(result))
            return result

        try:
            return run_in_write_transaction(self._engine, operation)
        except Exception:
            return RevocationResult(None, "idempotency_unavailable")

    def _submit_signed_revocation(
        self,
        connection,
        token: str,
        *,
        expected_mandate_id: str | None = None,
        authenticated_kid: str | None = None,
    ) -> str:
        try:
            encoded_header = token.split(".")[0]
            header = json.loads(
                base64.urlsafe_b64decode(encoded_header + "=" * (-len(encoded_header) % 4))
            )
            kid = header["kid"]
        except (IndexError, KeyError, ValueError, json.JSONDecodeError) as error:
            raise ValueError("malformed revocation JWS") from error
        if not isinstance(kid, str):
            raise ValueError("malformed revocation JWS")
        if authenticated_kid is not None and kid != authenticated_kid:
            raise ValueError("revocation authority does not match authenticated identity")
        signature_failure: ValueError | None = None
        signed_for_another_mandate = False
        for mandate in SqliteMandateRepository(connection).for_authority_kid(kid):
            for authority in mandate.authorities:
                if authority.kid != kid:
                    continue
                try:
                    payload = verify_compact_jws(token, public_key_from_jwk(dict(authority.public_jwk)))
                except ValueError as error:
                    signature_failure = error
                    continue
                if payload.get("mandate_id") != mandate.id:
                    signed_for_another_mandate = True
                    continue
                if expected_mandate_id is not None and mandate.id != expected_mandate_id:
                    raise ValueError("revocation mandate does not match request path")
                scope = payload.get("scope")
                if not isinstance(scope, str) or not self._is_canonical_revocation_scope(scope):
                    raise ValueError("invalid revocation scope")
                if scope not in authority.allowed_scopes:
                    raise ValueError("revocation scope is not allowed")
                if authority.role in (RevocationRole.GUARDIAN, RevocationRole.ISSUER) and scope != "mandate":
                    raise ValueError("guardian and issuer may only revoke the mandate")
                if not payload.get("reason") or not isinstance(payload.get("epoch"), int):
                    raise ValueError("revocation payload is incomplete")
                SqliteMandateLockRepository(connection).acquire(mandate.id, touched_at=self._clock())
                revocation = Revocation(
                    id=f"rev_{uuid4().hex}",
                    mandate_id=mandate.id,
                    authority_id=authority.id,
                    scope=scope,
                    reason=str(payload["reason"]),
                    epoch=int(payload["epoch"]),
                    signed_jws=token,
                    revoked_at=self._clock(),
                )
                SqliteRevocationRepository(connection).append(revocation)
                metadata = dict(mandate.revocation_metadata)
                metadata["epoch"] = revocation.epoch
                if scope == "mandate":
                    mandate = replace(mandate, status=MandateStatus.REVOKED, revocation_metadata=metadata)
                else:
                    mandate = replace(mandate, revocation_metadata=metadata)
                SqliteMandateRepository(connection).put(mandate)
                SqliteAuditLedger(connection).append(
                    mandate_id=mandate.id,
                    event_type="mandate.revoked" if scope == "mandate" else f"revocation.{authority.role.value}",
                    human_summary=f"Revogação de escopo {scope} por {authority.role.value} aceita.",
                    actor=("operator_01" if authority.role is RevocationRole.OPERATOR else f"authority:{authority.kid}"),
                    detail={
                        "scope": revocation.scope,
                        "reason": revocation.reason,
                        "epoch": revocation.epoch,
                        "authority_role": authority.role.value,
                    },
                    occurred_at=self._clock(),
                )
                return mandate.id
        if signed_for_another_mandate:
            if expected_mandate_id is not None:
                raise ValueError("revocation mandate does not match request path")
            raise ValueError("revocation mandate does not match authority")
        if signature_failure is not None:
            raise signature_failure
        raise ValueError("unknown revocation authority")

    @staticmethod
    def _stable_revocation_error(error: str) -> str:
        if "unknown revocation authority" in error or "does not match authenticated identity" in error:
            return "revocation_authority_unknown"
        if "mandate does not match" in error:
            return "revocation_mandate_mismatch"
        if "scope" in error:
            return "revocation_scope_not_allowed"
        return "revocation_invalid"

    @staticmethod
    def _serialize_revocation_result(result: RevocationResult) -> str:
        return json.dumps({"mandate_id": result.mandate_id, "reason_code": result.reason_code})

    @staticmethod
    def _deserialize_revocation_result(body: str | None, *, replayed: bool) -> RevocationResult:
        value = json.loads(body or "{}")
        return RevocationResult(value.get("mandate_id"), value.get("reason_code"), replayed)

    def mandates_readable_by(self, token: str, principal_id: str) -> list[str]:
        """Which of this buyer's mandates the signer of `token` is entitled to see.

        The reach is decided exactly the way a revocation's is — by verifying the
        signature against each mandate's *own* registered holder authority — so a key
        sees the mandates it could already have ended, and not one more. Holding a key
        for one of a person's mandates never becomes sight of the rest of them.

        A key that is an authority on nothing gets an empty list rather than a refusal.
        That is deliberate: a distinct answer for "wrong key" and "no mandates yet"
        would turn this into an oracle for which buyers exist, and it is also what lets
        a holder open the page before they have created anything.

        The token names the buyer it is being presented for, so it cannot be lifted from
        one listing and replayed against another. It is not otherwise time-bound, and it
        does not need to be: its entire reach is *the mandates this key already
        controls*, so replaying it grants nothing the key does not already grant.
        """
        try:
            encoded_header = token.split(".")[0]
            header = json.loads(
                base64.urlsafe_b64decode(encoded_header + "=" * (-len(encoded_header) % 4))
            )
            kid = header["kid"]
        except (IndexError, KeyError, ValueError, json.JSONDecodeError) as error:
            raise ValueError("malformed read authorization") from error

        readable: list[str] = []
        with self._engine.connect() as connection:
            for mandate in SqliteMandateRepository(connection).for_authority_kid(kid):
                if mandate.principal.id != principal_id:
                    continue
                for authority in mandate.authorities:
                    if authority.kid != kid or authority.role is not RevocationRole.HOLDER:
                        continue
                    try:
                        claims = verify_compact_jws(
                            token, public_key_from_jwk(dict(authority.public_jwk))
                        )
                    except ValueError:
                        continue
                    # The token has to be about this buyer, or a listing signed for one
                    # person would answer for another.
                    if claims.get("principal_id") == principal_id:
                        readable.append(mandate.id)
                        break
        return readable

    def submit_principal_revocation(self, token: str) -> list[str]:
        """End every mandate this key is an authority on, under one signature.

        Someone who thinks their agent has been taken over should not have to revoke
        six mandates one at a time while it keeps spending. The reach of the token is
        decided the same way a single revocation is — by verifying it against each
        mandate's own registered authority — so it touches exactly the mandates that
        key could already have ended one by one, and not one more. Holding a key for
        one of a person's mandates never becomes authority over the rest of them.

        Returns the mandates actually revoked. An empty list is a refusal, not a
        success with nothing to do: it means no mandate accepted this signature.
        """
        try:
            encoded_header = token.split(".")[0]
            header = json.loads(
                base64.urlsafe_b64decode(encoded_header + "=" * (-len(encoded_header) % 4))
            )
            kid = header["kid"]
        except (IndexError, KeyError, ValueError, json.JSONDecodeError) as error:
            raise ValueError("malformed revocation JWS") from error

        revoked: list[str] = []

        def operation(connection) -> None:
            repository = SqliteMandateRepository(connection)
            for mandate in repository.for_authority_kid(kid):
                for authority in mandate.authorities:
                    if authority.kid != kid:
                        continue
                    try:
                        payload = verify_compact_jws(
                            token, public_key_from_jwk(dict(authority.public_jwk))
                        )
                    except ValueError:
                        continue
                    if payload.get("principal_id") != mandate.principal.id:
                        continue
                    if "mandate" not in authority.allowed_scopes:
                        continue
                    if not payload.get("reason") or not isinstance(payload.get("epoch"), int):
                        raise ValueError("revocation payload is incomplete")
                    if mandate.status is not MandateStatus.ACTIVE:
                        continue
                    SqliteMandateLockRepository(connection).acquire(
                        mandate.id, touched_at=self._clock()
                    )
                    revocation = Revocation(
                        id=f"rev_{uuid4().hex}",
                        mandate_id=mandate.id,
                        authority_id=authority.id,
                        scope="mandate",
                        reason=str(payload["reason"]),
                        epoch=int(payload["epoch"]),
                        signed_jws=token,
                        revoked_at=self._clock(),
                    )
                    SqliteRevocationRepository(connection).append(revocation)
                    metadata = dict(mandate.revocation_metadata)
                    metadata["epoch"] = revocation.epoch
                    repository.put(
                        replace(
                            mandate,
                            status=MandateStatus.REVOKED,
                            revocation_metadata=metadata,
                        )
                    )
                    # One entry per mandate, on that mandate's own chain. A shared
                    # "everything was revoked" event would sit on no chain at all and
                    # would be invisible to an auditor reading a single mandate.
                    SqliteAuditLedger(connection).append(
                        mandate_id=mandate.id,
                        event_type=f"revocation.{authority.role.value}",
                        human_summary="Revogação total do titular aceita.",
                        actor=f"authority:{authority.kid}",
                        detail={
                            "scope": "mandate",
                            "reason": revocation.reason,
                            "epoch": revocation.epoch,
                            "authority_role": authority.role.value,
                            "principal_wide": True,
                        },
                        occurred_at=self._clock(),
                    )
                    revoked.append(mandate.id)
                    break

        run_in_write_transaction(self._engine, operation)
        return revoked

    def open_dispute(self, *, reservation_id: str, reason: str) -> Dispute:
        """Record a later denial. Opening a dispute decides nothing on its own."""

        def operation(connection) -> Dispute:
            mandate_id = connection.execute(
                select(reservations.c.mandate_id).where(reservations.c.id == reservation_id)
            ).scalar_one_or_none()
            if mandate_id is None:
                raise ValueError("dispute references an unknown reservation")
            dispute = Dispute(
                id=f"dsp_{uuid4().hex}", mandate_id=mandate_id, reservation_id=reservation_id,
                reason=reason, opened_at=self._clock(),
            )
            connection.execute(disputes.insert().values(
                id=dispute.id, mandate_id=dispute.mandate_id, reservation_id=dispute.reservation_id,
                reason=dispute.reason, status=dispute.status.value, resolution=None,
                opened_at=dispute.opened_at, resolved_at=None,
            ))
            SqliteAuditLedger(connection).append(
                mandate_id=dispute.mandate_id,
                event_type="dispute_opened",
                human_summary="Compra contestada pelo titular.",
                actor="principal:disputant",
                detail={
                    "dispute_id": dispute.id,
                    "reservation_id": dispute.reservation_id,
                    "reason": dispute.reason,
                },
                occurred_at=dispute.opened_at,
            )
            return dispute

        return run_in_write_transaction(self._engine, operation)

    def resolve_dispute(self, dispute_id: str) -> Dispute:
        """Resolve by reading the trail: an authorization proof bound to a committed
        reservation answers the claim; its absence answers it the other way."""

        def operation(connection) -> Dispute:
            row = connection.execute(
                select(disputes).where(disputes.c.id == dispute_id)
            ).mappings().one_or_none()
            if row is None:
                raise ValueError("dispute not found")
            liability = self._liability_with(connection, row["reservation_id"])
            dispute = Dispute(
                id=row["id"], mandate_id=row["mandate_id"], reservation_id=row["reservation_id"],
                reason=row["reason"], opened_at=row["opened_at"], status=DisputeStatus(row["status"]),
                resolution=row["resolution"], resolved_at=row["resolved_at"],
            )
            proof = connection.execute(
                select(authorization_proofs.c.jti, authorization_proofs.c.signed_proof)
                .where(authorization_proofs.c.reservation_id == dispute.reservation_id)
            ).mappings().first()
            reservation_status = connection.execute(
                select(reservations.c.status).where(reservations.c.id == dispute.reservation_id)
            ).scalar_one()
            settled = reservation_status in (
                ReservationStatus.COMMITTED.value, ReservationStatus.SETTLED.value
            )
            if proof is None or not settled:
                resolved = dispute.resolve(
                    DisputeStatus.MANDATE_FAILED,
                    "Nenhuma prova de autorização vincula esta compra.",
                    self._clock(),
                )
            else:
                bound = self._proof_payload(proof["signed_proof"])
                resolved = dispute.resolve(
                    DisputeStatus.MANDATE_HELD,
                    "Prova {jti} vincula merchant {merchant}, valor {amount} e terms_hash {terms}.".format(
                        jti=proof["jti"], merchant=bound.get("merchant_id"),
                        amount=bound.get("amount_minor_units"), terms=bound.get("terms_hash"),
                    ),
                    self._clock(),
                )
            connection.execute(disputes.update().where(disputes.c.id == dispute.id).values(
                status=resolved.status.value, resolution=resolved.resolution,
                resolved_at=resolved.resolved_at,
            ))
            SqliteAuditLedger(connection).append(
                mandate_id=resolved.mandate_id,
                event_type="dispute_resolved",
                human_summary=resolved.resolution or "Disputa resolvida.",
                actor="auditor:aval",
                detail={
                    "dispute_id": resolved.id,
                    "reservation_id": resolved.reservation_id,
                    "status": resolved.status.value,
                    "resolution": resolved.resolution,
                    # What the trail decided about *who answers*, recorded as of now.
                    # The live verdict is always recomputed; this is the snapshot an
                    # auditor reads to see what was concluded on the day.
                    "liability": liability,
                },
                occurred_at=resolved.resolved_at,
            )
            return resolved, liability

        resolved, liability = run_in_write_transaction(self._engine, operation)
        # The verdict moves money, and it moves it outside the write transaction that
        # produced it: the processor is I/O, and holding the single writer open across a
        # network call is how a demo deadlocks in front of an audience.
        if liability["verdict"] not in ("HOLDER_LIABLE", "NO_CHARGE"):
            self._reverse(resolved.mandate_id, resolved.reservation_id, liability["verdict"])
        # The verdict is handed back with the dispute because it is the verdict this
        # resolution *acted on*. Recomputing it afterwards would read a world the
        # reversal already changed — after money goes back the live answer is NO_CHARGE,
        # which is true and is not what was decided here.
        return resolved

    def liability_recorded_for(self, dispute_id: str) -> dict[str, Any] | None:
        """The verdict written into the trail when this dispute was resolved.

        Read from the chain rather than recomputed, so a reversal that already happened
        cannot rewrite the answer that caused it.
        """
        with self._engine.connect() as connection:
            row = connection.execute(
                select(disputes.c.mandate_id).where(disputes.c.id == dispute_id)
            ).mappings().one_or_none()
            if row is None:
                return None
            for entry in reversed(SqliteAuditLedger(connection).timeline_for(row["mandate_id"])):
                if (
                    entry.event_type == "dispute_resolved"
                    and entry.detail.get("dispute_id") == dispute_id
                ):
                    liability = entry.detail.get("liability")
                    return liability if isinstance(liability, dict) else None
        return None

    def _reverse(self, mandate_id: str, reservation_id: str, verdict: str) -> None:
        """Give back money this layer cannot justify holding.

        Only reached for a verdict that does not put the charge on the holder. The
        reservation is re-read at every step, so resolving the same dispute three times
        reverses once: the second pass finds money already returned and has nothing to
        do. A processor that does not answer leaves the money exactly where it is and
        says so in the trail — silence is not a refund, the same way it is not a decline.
        """
        with self._engine.connect() as connection:
            row = connection.execute(
                select(reservations.c.status, reservations.c.amount_minor_units).where(
                    reservations.c.id == reservation_id
                )
            ).mappings().one_or_none()
        if row is None or row["status"] not in (
            ReservationStatus.COMMITTED.value,
            ReservationStatus.SETTLED.value,
        ):
            return

        refund = getattr(self._settlement_adapter, "refund", None)
        outcome: str
        reference: str | None = None
        if refund is None:
            outcome = "reversal_unsupported"
        else:
            try:
                settlement = refund(
                    Reservation(
                        id=reservation_id,
                        mandate_id=mandate_id,
                        checkout_intent_id="",
                        amount=Money(int(row["amount_minor_units"]), "USD", 2),
                        status=ReservationStatus(row["status"]),
                    )
                )
            except Exception:
                outcome = "reversal_in_doubt"
            else:
                outcome = "purchase_reversed" if settlement.approved else "reversal_refused"
                reference = settlement.reference

        def commit(connection) -> None:
            fresh = SqliteLedgerRepository(connection).get(
                reservation_id, Money(0, "USD", 2)
            )
            if fresh is None or fresh.status not in (
                ReservationStatus.COMMITTED,
                ReservationStatus.SETTLED,
            ):
                return
            if outcome == "purchase_reversed":
                SqliteLedgerRepository(connection).update(fresh.reverse(), at=self._clock())
            SqliteAuditLedger(connection).append(
                mandate_id=mandate_id,
                event_type=outcome,
                human_summary={
                    "purchase_reversed": "Valor estornado: a trilha não sustenta esta cobrança.",
                    "reversal_refused": "O processador recusou o estorno; o valor segue retido.",
                    "reversal_in_doubt": "O processador não respondeu ao estorno; o valor segue retido.",
                    "reversal_unsupported": "Nenhum processador para estornar; o valor segue retido.",
                }[outcome],
                actor="auditor:aval",
                detail={
                    "reservation_id": reservation_id,
                    "amount_minor_units": int(row["amount_minor_units"]),
                    "currency": "USD",
                    "scale": 2,
                    "verdict": verdict,
                    "settlement_reference": reference,
                },
                occurred_at=self._clock(),
            )

        run_in_write_transaction(self._engine, commit)

    @staticmethod
    def _proof_payload(signed_proof: str) -> dict:
        """Read the payload AVAL itself recorded. Signature verification belongs to the
        merchant, which holds the token; this row is the ledger's own copy."""
        encoded = signed_proof.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))

    DECISION_EVENTS = {
        AuthorizationDecision.AUTHORIZED: "purchase_authorized",
        AuthorizationDecision.AWAITING_HUMAN: "purchase_escalated",
        AuthorizationDecision.REJECTED: "purchase_rejected",
    }

    @staticmethod
    def _purchase_detail(
        command: AuthorizationCommand,
        result: AuthorizationResult,
        agent_id: str | None = None,
        **extra,
    ) -> dict:
        return {
            "agent_id": agent_id,
            "checkout_id": command.checkout_id,
            "merchant_id": command.merchant_id,
            "category": command.category,
            "amount_minor_units": command.total.minor_units,
            "currency": command.total.currency,
            "scale": command.total.scale,
            "decision": result.decision.value,
            "reason_code": result.reason_code,
            **extra,
        }

    # No card network has published a binding chargeback rule for a dispute an agent
    # started. The vocabulary the industry is converging on is *agent overreach* and
    # *mandate repudiation*, and both are questions this trail can answer — so it
    # answers them, in a fixed order, the way the authorization ladder does.
    REPUDIATION_UNPROVEN_NOTE = (
        "Este mandato não carrega prova de criação assinada, e nenhum outro artefato "
        "assinado pelo titular o nomeia. A trilha prova que o agente ficou dentro do "
        "mandato; não prova que esta pessoa o criou. Todo mandato criado por HTTP nasce "
        "assinado — esta resposta só alcança um mandato registrado em processo."
    )

    #: Ledger event types, mapped to the three outcomes the core can reach. Reading the
    #: panel off the trail means the panel cannot disagree with the trail.
    #:
    #: `purchase_authorized` is the preview at `/authorize`; `purchase_committed` is the
    #: authorized outcome at `/capture`, which never writes the first. A purchase that
    #: previews and then pays therefore counts two decisions, because the core made two —
    #: and the second one re-walked the whole ladder rather than trusting the first.
    DECISION_OUTCOMES = {
        "purchase_authorized": "authorized",
        "purchase_committed": "authorized",
        "purchase_escalated": "awaiting_human",
        "purchase_rejected": "rejected",
    }

    def metrics_snapshot(self) -> dict[str, Any]:
        """Aggregates of the append-only trail, plus the one invariant worth a footer.

        `spend_outside_mandate` is money held or settled with no authorization proof
        bound to it. That is the same condition `liability_for` calls AGENT_OVERREACH,
        deliberately: the number on the screen and the verdict in a dispute are one
        definition, so they cannot drift apart and tell a judge two different stories.
        """
        decisions: dict[str, int] = {"authorized": 0, "awaiting_human": 0, "rejected": 0}
        reasons: dict[str, int] = {}
        payments = {"settled": 0, "declined": 0, "in_doubt": 0}
        with self._engine.connect() as connection:
            for entry in SqliteAuditLedger(connection).all_entries():
                outcome = self.DECISION_OUTCOMES.get(entry.event_type)
                if outcome is not None:
                    decisions[outcome] += 1
                    reason = entry.detail.get("reason_code")
                    if isinstance(reason, str) and outcome != "authorized":
                        reasons[reason] = reasons.get(reason, 0) + 1
                if entry.event_type == "purchase_settled":
                    payments["settled"] += 1
                elif entry.event_type == "purchase_declined":
                    payments["declined"] += 1
                elif entry.event_type == "payment_in_doubt":
                    payments["in_doubt"] += 1
            unproven = connection.execute(
                select(
                    func.coalesce(func.sum(reservations.c.amount_minor_units), 0)
                ).where(
                    reservations.c.status.in_(
                        (
                            ReservationStatus.COMMITTED.value,
                            ReservationStatus.SETTLED.value,
                        )
                    ),
                    ~reservations.c.id.in_(select(authorization_proofs.c.reservation_id)),
                )
            ).scalar_one()
        return {
            "decisions": decisions,
            "reasons": reasons,
            "payments": payments,
            "spend_outside_mandate": {
                "minor_units": int(unproven),
                "currency": "USD",
                "scale": 2,
            },
        }

    def liability_for(self, reservation_id: str) -> dict[str, Any]:
        """Who answers for this purchase, derived from the trail every time it is asked.

        Deliberately not stored. The evidence it reads is append-only, so recomputing
        always lands on the same verdict — and a stored verdict that had drifted from
        the evidence beneath it would be worse than no verdict at all.
        """
        with self._engine.connect() as connection:
            return self._liability_with(connection, reservation_id)

    def _liability_with(self, connection, reservation_id: str) -> dict[str, Any]:
        """The same verdict, on a connection the caller already holds.

        Resolution runs inside a write transaction, and opening a second connection
        under it would read a stale snapshot of the very evidence being judged.
        """
        row = connection.execute(
            select(reservations.c.mandate_id, reservations.c.status).where(
                reservations.c.id == reservation_id
            )
        ).mappings().one_or_none()
        if row is None:
            return self._verdict(
                "NO_CHARGE", "nobody", ["Nenhuma reserva com este identificador."], []
            )
        proof = connection.execute(
            select(authorization_proofs.c.jti, authorization_proofs.c.signed_proof).where(
                authorization_proofs.c.reservation_id == reservation_id
            )
        ).mappings().first()
        signatures = self._holder_signatures(connection, row["mandate_id"])

        charged = row["status"] in (
            ReservationStatus.COMMITTED.value,
            ReservationStatus.SETTLED.value,
        )
        if not charged:
            return self._verdict(
                "NO_CHARGE",
                "nobody",
                [f"A reserva terminou como {row['status']}; nenhum valor foi cobrado."],
                signatures,
            )
        if proof is None:
            # Money is held for a purchase this layer never issued a proof for. The
            # merchant verified nothing and the mandate authorized nothing, so the loss
            # sits with whoever operated the agent — not with the person who delegated.
            return self._verdict(
                "AGENT_OVERREACH",
                "agent_operator",
                [
                    "Valor retido sem prova de autorização emitida por esta camada.",
                    "Nenhuma decisão do núcleo vincula esta reserva.",
                ],
                signatures,
            )
        bound = self._proof_payload(proof["signed_proof"])
        basis = [
            "Prova {jti} vincula merchant {merchant}, valor {amount} e terms_hash {terms}.".format(
                jti=proof["jti"],
                merchant=bound.get("merchant_id"),
                amount=bound.get("amount_minor_units"),
                terms=bound.get("terms_hash"),
            ),
            f"Reserva {reservation_id} comprometida sob a política v{bound.get('policy_version')}.",
        ]
        basis.extend(
            f"Assinatura do titular ({signature['kind']}) pela chave {signature['kid']}."
            for signature in signatures
        )
        return self._verdict("HOLDER_LIABLE", "holder", basis, signatures)

    @staticmethod
    def _holder_signatures(connection, mandate_id: str) -> list[dict[str, str]]:
        """Every artefact on this mandate that the holder's own key signed.

        A person who says "I never created this mandate" is answered first by their
        own signature over the terms it was born with, and after that by anything else
        they signed about it — an approval, a revocation. Nothing here is inferred: a
        mandate registered without a creation proof produces no genesis line, and the
        verdict says `unproven` with the reason written.
        """
        found: list[dict[str, str]] = []
        genesis = connection.execute(
            select(mandate_creation_proofs.c.kid).where(
                mandate_creation_proofs.c.mandate_id == mandate_id
            )
        ).scalar_one_or_none()
        if genesis is not None:
            # Position 0 of the chain, and the reason repudiation is answerable at all:
            # the mandate exists because this key said so.
            found.append({"kind": "mandate_creation", "kid": str(genesis)})
        for row in connection.execute(
            select(escalations.c.approval_jws)
            .where(
                escalations.c.mandate_id == mandate_id,
                escalations.c.approval_jws.is_not(None),
            )
            .order_by(escalations.c.decided_at)
        ).mappings():
            found.append(
                {"kind": "escalation_approval", "kid": _jws_kid(row["approval_jws"])}
            )
        for row in connection.execute(
            select(revocations.c.signed_jws, revocations.c.scope)
            .where(revocations.c.mandate_id == mandate_id)
            .order_by(revocations.c.revoked_at)
        ).mappings():
            found.append(
                {"kind": f"revocation:{row['scope']}", "kid": _jws_kid(row["signed_jws"])}
            )
        return found

    def _verdict(
        self,
        verdict: str,
        liable_party: str,
        basis: list[str],
        signatures: list[dict[str, str]],
    ) -> dict[str, Any]:
        refuted = bool(signatures)
        return {
            "verdict": verdict,
            "liable_party": liable_party,
            "basis": basis,
            "holder_signatures": signatures,
            "mandate_repudiation": "refuted" if refuted else "unproven",
            "repudiation_note": (
                "O titular assinou artefatos que nomeiam este mandato."
                if refuted
                else self.REPUDIATION_UNPROVEN_NOTE
            ),
        }

    def disputes_for_mandate(self, mandate_id: str) -> list[Dispute]:
        with self._engine.connect() as connection:
            rows = connection.execute(
                select(disputes).where(disputes.c.mandate_id == mandate_id).order_by(disputes.c.opened_at)
            ).mappings().all()
        return [
            Dispute(
                id=row["id"], mandate_id=row["mandate_id"], reservation_id=row["reservation_id"],
                reason=row["reason"], opened_at=row["opened_at"], status=DisputeStatus(row["status"]),
                resolution=row["resolution"], resolved_at=row["resolved_at"],
            )
            for row in rows
        ]

    def reconcile(self) -> dict[str, int]:
        """Finish the captures that were left in doubt.

        A capture whose processor never answered stays committed and its budget stays
        held: that is the only safe reading of *unknown*. This asks again, once the
        processor is back, and closes each attempt through the same path a normal
        settlement takes.
        """
        with self._engine.connect() as connection:
            pending = connection.execute(
                select(
                    capture_attempts.c.id,
                    capture_attempts.c.reservation_id,
                    capture_attempts.c.idempotency_key,
                )
                # `PENDING` is an attempt that never reached the processor; `IN_DOUBT`
                # is one that reached it and got no answer. Both are unresolved and
                # both are this sweep's job — scanning only the first would strand
                # every purchase the third state exists to describe.
                .where(capture_attempts.c.status.in_(("PENDING", "IN_DOUBT")))
                .order_by(capture_attempts.c.id)
            ).mappings().all()

        tally = {"settled": 0, "released": 0, "pending": 0}
        for attempt in pending:
            outcome = self._reconcile_one(
                attempt_id=attempt["id"],
                reservation_id=attempt["reservation_id"],
                idempotency_key=attempt["idempotency_key"],
            )
            tally[outcome] += 1
        return tally

    def _reconcile_one(self, *, attempt_id: str, reservation_id: str, idempotency_key: str) -> str:
        with self._engine.connect() as connection:
            row = connection.execute(
                select(
                    reservations.c.mandate_id,
                    reservations.c.checkout_intent_id,
                    reservations.c.amount_minor_units,
                    reservations.c.status,
                    reservations.c.transaction_hash,
                    checkout_intents.c.merchant_id,
                    checkout_intents.c.currency,
                    checkout_intents.c.scale,
                )
                .join(checkout_intents, reservations.c.checkout_intent_id == checkout_intents.c.id)
                .where(reservations.c.id == reservation_id)
            ).mappings().one_or_none()
            proof = connection.execute(
                select(authorization_proofs.c.signed_proof).where(
                    authorization_proofs.c.reservation_id == reservation_id
                )
            ).scalar()
        if row is None or row["status"] != ReservationStatus.COMMITTED.value:
            return "pending"

        reservation = Reservation(
            reservation_id,
            row["mandate_id"],
            row["checkout_intent_id"],
            Money(row["amount_minor_units"], row["currency"], row["scale"]),
            ReservationStatus.COMMITTED,
            row["transaction_hash"],
        )
        if self._settlement_adapter is None:
            return "pending"
        try:
            settlement = self._settlement_adapter.authorize(
                reservation, proof or f"proof_{reservation_id}"
            )
        except Exception:
            # Still unknown. Still held. Trying again later is the whole point.
            return "pending"

        final = reservation.settle() if settlement.approved else reservation.release()
        result = CaptureResult(
            settlement.approved,
            "settled" if settlement.approved else "settlement_declined",
            final,
            settlement.reference,
        )

        def finish(connection) -> None:
            SqliteLedgerRepository(connection).update(final)
            SqliteCaptureRepository(connection).complete(
                attempt_id, approved=result.approved, reference=result.settlement_reference
            )
            SqliteIdempotencyRepository(connection).complete(
                "capture", idempotency_key, self._serialize_result(result)
            )
            SqliteAuditLedger(connection).append(
                mandate_id=row["mandate_id"],
                event_type="purchase_settled" if result.approved else "purchase_declined",
                human_summary=(
                    "Pagamento liquidado na reconciliação."
                    if result.approved
                    else "Pagamento recusado na reconciliação."
                ),
                actor="psp:demo",
                detail={
                    "checkout_id": row["checkout_intent_id"],
                    "merchant_id": row["merchant_id"],
                    "reservation_id": reservation_id,
                    "amount_minor_units": row["amount_minor_units"],
                    "currency": row["currency"],
                    "scale": row["scale"],
                    "reason_code": result.reason_code,
                    "settlement_reference": result.settlement_reference,
                    "reconciled": True,
                    "payment_state": "settled" if result.approved else "declined",
                },
                occurred_at=self._clock(),
            )

        run_in_write_transaction(self._engine, finish)
        return "settled" if result.approved else "released"

    def evaluate(self, command: AuthorizationCommand) -> AuthorizationResult:
        with self._engine.connect() as connection:
            return self._evaluate_with(connection, command)[0]

    def _open_escalation(
        self,
        connection,
        command: AuthorizationCommand,
        result: AuthorizationResult,
        agent_id: str | None,
    ) -> str:
        repository = SqliteEscalationRepository(connection)
        existing = repository.find_open_match(
            mandate_id=command.mandate_id,
            checkout_id=command.checkout_id,
            merchant_id=command.merchant_id,
            amount=command.total,
            reason_code=result.reason_code,
        )
        if existing is not None:
            return existing.id
        now = self._clock()
        escalation = Escalation(
            id=f"dh_{uuid4().hex}",
            mandate_id=command.mandate_id,
            checkout_id=command.checkout_id,
            merchant_id=command.merchant_id,
            category=command.category,
            amount=command.total,
            reason_code=result.reason_code,
            created_at=now,
            expires_at=now + ESCALATION_WINDOW,
            agent_id=agent_id,
        )
        repository.create(escalation)
        return escalation.id

    def escalation(self, escalation_id: str) -> Escalation | None:
        with self._engine.connect() as connection:
            return SqliteEscalationRepository(connection).get(escalation_id)

    def open_escalations(self, mandate_id: str) -> list[Escalation]:
        with self._engine.connect() as connection:
            return SqliteEscalationRepository(connection).open_for_mandate(mandate_id)

    def open_escalations_for_principal(self, principal_id: str) -> list[Escalation]:
        """Everything waiting on one person. There is deliberately no unscoped variant:
        a pending escalation names what somebody is about to buy."""
        with self._engine.connect() as connection:
            return SqliteEscalationRepository(connection).open_for_principal(principal_id)

    def _verified_approval(
        self, token: str, mandate: Mandate, *, kind: str = "approval"
    ) -> dict:
        """Verify a holder-signed decision about this mandate.

        `kind` only names the reason codes, so a caller can tell an unsigned limit
        change from an unsigned escalation approval. It never changes what is checked.
        """
        try:
            encoded_header = token.split(".")[0]
            header = json.loads(
                base64.urlsafe_b64decode(encoded_header + "=" * (-len(encoded_header) % 4))
            )
            kid = header["kid"]
        except (IndexError, KeyError, ValueError, json.JSONDecodeError) as error:
            raise ApprovalError(
                403, f"{kind}_malformed", "Autorização malformada."
            ) from error
        # Only the holder approves spending. A guardian may revoke authority; it may
        # not spend on the holder behalf.
        authority = next(
            (
                candidate
                for candidate in mandate.authorities
                if candidate.kid == kid and candidate.role is RevocationRole.HOLDER
            ),
            None,
        )
        if authority is None:
            raise ApprovalError(
                403, f"{kind}_authority_unknown", "Chave de autorização desconhecida."
            )
        try:
            claims = verify_compact_jws(token, public_key_from_jwk(dict(authority.public_jwk)))
        except ValueError as error:
            raise ApprovalError(
                403, f"{kind}_signature_invalid", "Assinatura de autorização inválida."
            ) from error
        claims["kid"] = kid
        return claims

    def _verified_creation(self, token: str, mandate: Mandate) -> dict[str, str]:
        """The holder's signature over the mandate being created.

        Verified against the authorities the mandate itself declares, so the proof is
        self-rooted: whoever signs is a key this mandate names as its holder, and the
        same key is what may later revoke it. A signature that is merely *valid* is not
        enough — it has to be about these terms, so every field that decides what may be
        spent is compared against the payload, the way a limit change is.

        The instrument is deliberately not bound: the token is minted at the edge after
        this signature exists, and the holder already gets a separate, signed way to
        cancel a card without touching the mandate.
        """
        claims = self._verified_approval(token, mandate, kind="mandate_creation")
        nonce = claims.get("creation_nonce")
        if not isinstance(nonce, str) or not nonce:
            raise ApprovalError(
                422,
                "mandate_creation_nonce_missing",
                "A autorização de criação não carrega nonce.",
            )
        signed = (
            claims.get("principal_id"),
            claims.get("allowed_merchant_ids"),
            claims.get("allowed_categories"),
            claims.get("limit_minor_units"),
            claims.get("currency"),
            claims.get("scale"),
            claims.get("ceiling_minor_units"),
            claims.get("max_uses"),
            claims.get("usage_window_seconds"),
        )
        declared = (
            mandate.principal.id,
            sorted(mandate.allowed_merchant_ids),
            sorted(mandate.allowed_categories),
            mandate.limit.minor_units,
            mandate.limit.currency,
            mandate.limit.scale,
            None if mandate.ceiling is None else mandate.ceiling.minor_units,
            None if mandate.usage_limit is None else mandate.usage_limit.max_uses,
            None if mandate.usage_limit is None else mandate.usage_limit.window_seconds,
        )
        if signed != declared or not self._same_instant(
            claims.get("expires_at"), mandate.expires_at
        ):
            raise ApprovalError(
                403,
                "mandate_creation_terms_mismatch",
                "A autorização não descreve o mandato que está sendo criado.",
            )
        return {"kid": str(claims["kid"]), "nonce": nonce}

    @staticmethod
    def _same_instant(signed: Any, declared: datetime) -> bool:
        """Validity is compared as an instant, never as a string: `...Z` and `...+00:00`
        are the same moment, and a mandate refused over spelling would be a bug that
        reads as a security refusal."""
        if not isinstance(signed, str):
            return False
        try:
            parsed = datetime.fromisoformat(signed.replace("Z", "+00:00"))
        except ValueError:
            return False
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed == declared

    @staticmethod
    def _require_approval_binds(claims: dict, escalation: Escalation, decision: str) -> None:
        """The signature has to be about this purchase, not merely valid.

        A signed approval that did not name the handle, the mandate and the amount could
        be lifted from one decision and dropped onto a larger one.
        """
        if claims.get("decision_handle") != escalation.id:
            raise ApprovalError(
                403, "approval_handle_mismatch", "A aprovação não é desta escalação."
            )
        if claims.get("mandate_id") != escalation.mandate_id:
            raise ApprovalError(403, "approval_mandate_mismatch", "A aprovação não é deste mandato.")
        if claims.get("amount_minor_units") != escalation.amount.minor_units:
            raise ApprovalError(403, "approval_amount_mismatch", "O valor aprovado não confere.")
        if claims.get("decision") != decision:
            raise ApprovalError(403, "approval_decision_mismatch", "A decisão assinada não confere.")

    def decide_escalation(
        self, *, escalation_id: str, decision: str, approval_jws: str
    ) -> tuple[Escalation, CaptureResult | None]:
        """Close an escalation with a signed human decision, then re-run the purchase.

        The approval is evidence, not a bypass. It lifts exactly the one condition that
        was escalated; everything else is checked again, now, so a mandate revoked while
        the person was deciding still refuses the purchase.
        """
        if decision not in ("approve", "deny"):
            raise ApprovalError(422, "approval_decision_unknown", "Decisão desconhecida.")

        def settle(connection) -> Escalation:
            repository = SqliteEscalationRepository(connection)
            escalation = repository.get(escalation_id)
            if escalation is None:
                raise ApprovalError(404, "escalation_not_found", "Escalação não encontrada.")
            if escalation.status is not EscalationStatus.OPEN:
                raise ApprovalError(409, "escalation_already_decided", "Escalação já decidida.")
            if escalation.is_expired_at(self._clock()):
                raise ApprovalError(409, "escalation_expired", "Escalação expirada.")
            mandate = SqliteMandateRepository(connection).get(escalation.mandate_id)
            if mandate is None:
                raise ApprovalError(404, "mandate_not_found", "Mandato não encontrado.")
            claims = self._verified_approval(approval_jws, mandate)
            self._require_approval_binds(claims, escalation, decision)
            now = self._clock()
            status = (
                EscalationStatus.APPROVED if decision == "approve" else EscalationStatus.DENIED
            )
            repository.mark_decided(
                escalation.id, status=status, approval_jws=approval_jws, decided_at=now
            )
            SqliteAuditLedger(connection).append(
                mandate_id=mandate.id,
                event_type=(
                    "escalation_approved" if decision == "approve" else "escalation_denied"
                ),
                human_summary=(
                    "Compra aprovada pelo titular do mandato."
                    if decision == "approve"
                    else "Compra negada pelo titular do mandato."
                ),
                actor=f"principal:{mandate.principal.id}",
                detail={
                    "decision_handle": escalation.id,
                    "decision": decision,
                    "reason_code": escalation.reason_code,
                    "checkout_id": escalation.checkout_id,
                    "merchant_id": escalation.merchant_id,
                    "category": escalation.category,
                    "amount_minor_units": escalation.amount.minor_units,
                    "currency": escalation.amount.currency,
                    "scale": escalation.amount.scale,
                    "authority_kid": str(claims.get("kid", "")),
                    # Kept whole and on purpose: this is what answers a later denial.
                    "approval_jws": approval_jws,
                },
                occurred_at=now,
            )
            return replace(
                escalation, status=status, approval_jws=approval_jws, decided_at=now
            )

        escalation = run_in_write_transaction(self._engine, settle)
        if escalation.status is not EscalationStatus.APPROVED:
            return escalation, None
        # The resumed capture has to present the instrument the mandate names, or the
        # ladder refuses its own approval with `instrument_not_in_mandate` — the person
        # taps Aprovar and the purchase dies anyway.
        #
        # Read live rather than frozen on purpose: if the holder cancelled the card
        # while they were deciding, the `instrument_not_revoked` rung sits *above* this
        # one and still refuses. Reading now cannot resurrect a cancelled card, and it
        # keeps the escalation from carrying a copy of state the mandate already owns.
        resumed = self.mandate(escalation.mandate_id)
        instrument_id = (
            None if resumed is None or resumed.instrument is None else resumed.instrument.token
        )
        capture = self.capture(
            CaptureCommand(
                mandate_id=escalation.mandate_id,
                checkout_id=escalation.checkout_id,
                merchant_id=escalation.merchant_id,
                total=escalation.amount,
                category=escalation.category,
                # Derived from the handle, so approving twice can never charge twice.
                idempotency_key=f"esc_{escalation.id}",
                instrument_id=instrument_id,
            ),
            agent_id=escalation.agent_id,
            # The signature named this handle, this merchant and this amount, so the
            # person approved *this purchase*, not one of the reasons it was stopped.
            # Asking again for a second reason on the same frozen purchase adds friction
            # and no safety. The refusals that are never approvable — the ceiling, a
            # revocation, an expiry, a broken amount — are not in this set and stand.
            approved_reasons=APPROVABLE_REASONS,
        )
        return escalation, capture

    def decide(
        self, command: AuthorizationCommand, *, agent_id: str | None = None
    ) -> AuthorizationResult:
        """Evaluate and write the decision to the trail in the same transaction.

        A refusal nobody can read afterwards is indistinguishable from a purchase that
        never happened, and the case asks for the opposite: nothing passes in silence.
        """

        def operation(connection) -> AuthorizationResult:
            result, mandate = self._evaluate_with(connection, command)
            # An unknown mandate has no trail to write on: there is no row to hang the
            # event from, and the attempt says nothing about anybody real.
            if mandate is None:
                return result
            if result.decision is AuthorizationDecision.AWAITING_HUMAN:
                result = replace(
                    result,
                    escalation_id=self._open_escalation(connection, command, result, agent_id),
                )
            SqliteAuditLedger(connection).append(
                mandate_id=command.mandate_id,
                event_type=self.DECISION_EVENTS[result.decision],
                human_summary=result.human_summary,
                actor="aval-core",
                detail=self._purchase_detail(
                    command, result, agent_id=agent_id, escalation_id=result.escalation_id
                ),
                occurred_at=self._clock(),
            )
            return result

        return run_in_write_transaction(self._engine, operation)

    def reservation_for_proof(self, reservation_id: str) -> Reservation | None:
        """The committed reservation a proof names.

        The merchant does not carry this and must not be asked to: the proof binding is
        checked against what AVAL recorded, not against what the presenter claims.
        """
        with self._engine.connect() as connection:
            row = connection.execute(
                select(
                    reservations.c.id,
                    reservations.c.mandate_id,
                    reservations.c.checkout_intent_id,
                    reservations.c.amount_minor_units,
                    reservations.c.status,
                    reservations.c.transaction_hash,
                    checkout_intents.c.currency,
                    checkout_intents.c.scale,
                )
                .join(checkout_intents, reservations.c.checkout_intent_id == checkout_intents.c.id)
                .where(reservations.c.id == reservation_id)
            ).mappings().one_or_none()
        if row is None:
            return None
        return Reservation(
            row["id"],
            row["mandate_id"],
            row["checkout_intent_id"],
            Money(row["amount_minor_units"], row["currency"], row["scale"]),
            ReservationStatus(row["status"]),
            row["transaction_hash"],
        )

    def reservation_authority_state(self, reservation_id: str) -> dict | None:
        """Answer *is the authority behind this purchase still standing* without saying
        whose it was. The merchant needs the answer; it is not entitled to the mandate."""
        with self._engine.connect() as connection:
            mandate_id = connection.execute(
                select(reservations.c.mandate_id).where(reservations.c.id == reservation_id)
            ).scalar_one_or_none()
            if mandate_id is None:
                return None
            mandate = SqliteMandateRepository(connection).get(mandate_id)
            if mandate is None:
                return None
            revoked = SqliteRevocationRepository(connection).is_revoked(mandate_id)
            return {
                "revoked": revoked or mandate.status is MandateStatus.REVOKED,
                "expired": self._clock() >= mandate.expires_at,
                "epoch": int(mandate.revocation_metadata.get("epoch", 0)),
                "policy_version": mandate.policy_version,
            }

    def spent_for(self, mandate_id: str, unit: Money) -> Money:
        with self._engine.connect() as connection:
            return SqliteLedgerRepository(connection).spent_for(mandate_id, unit)

    def snapshot(self, mandate_id: str) -> MandateSnapshot | None:
        with self._engine.connect() as connection:
            mandate = SqliteMandateRepository(connection).get(mandate_id)
            if mandate is None:
                return None
            limit, _ = SqlitePolicyRepository(connection).active_limit_for(mandate_id, mandate.limit)
            ledger = SqliteLedgerRepository(connection)
            return MandateSnapshot(
                mandate=mandate,
                limit=limit,
                spent=ledger.spent_for(mandate_id, limit),
                uses_in_window=self._uses_in_window(ledger, mandate),
                instrument_revoked=self._instrument_revoked(connection, mandate),
            )

    def snapshots_for_principal(self, principal_id: str) -> list[MandateSnapshot]:
        """Every mandate one buyer holds, each already priced against its live limit.

        Built one connection deep so a listing reads the same active limit and the same
        spend a single read would — a judge who moves the limit sees the list move too.
        """
        with self._engine.connect() as connection:
            policies = SqlitePolicyRepository(connection)
            ledger = SqliteLedgerRepository(connection)
            snapshots = []
            for mandate in SqliteMandateRepository(connection).for_principal(principal_id):
                limit, _ = policies.active_limit_for(mandate.id, mandate.limit)
                snapshots.append(
                    MandateSnapshot(
                        mandate=mandate,
                        limit=limit,
                        spent=ledger.spent_for(mandate.id, limit),
                        uses_in_window=self._uses_in_window(ledger, mandate),
                        instrument_revoked=self._instrument_revoked(connection, mandate),
                    )
                )
            return snapshots

    @staticmethod
    def _instrument_revoked(connection, mandate: Mandate) -> bool:
        if mandate.instrument is None:
            return False
        return SqliteRevocationRepository(connection).has_scope(
            mandate.id, f"instrument:{mandate.instrument.token}"
        )

    def _uses_in_window(self, ledger: SqliteLedgerRepository, mandate: Mandate) -> int:
        if mandate.usage_limit is None:
            return 0
        window = timedelta(seconds=mandate.usage_limit.window_seconds)
        return ledger.uses_since(mandate.id, self._clock() - window)

    def timeline_for(self, mandate_id: str) -> list[LedgerEntry]:
        with self._engine.connect() as connection:
            return SqliteAuditLedger(connection).timeline_for(mandate_id)

    def merchant_timeline(self, merchant_id: str) -> list[LedgerEntry]:
        with self._engine.connect() as connection:
            return SqliteAuditLedger(connection).entries_for_merchant(merchant_id)

    def verify_timeline(self, mandate_id: str) -> tuple[bool, int | None, int]:
        entries = self.timeline_for(mandate_id)
        intact, broken_at = verify_chain(entries)
        return intact, broken_at, len(entries)

    def live_delegation_context(
        self, command: AuthorizationCommand
    ) -> tuple[AuthorizationResult, LiveAuthorizationContext | None]:
        """Return the current, authoritative allowance inputs for one checkout."""
        with self._engine.connect() as connection:
            decision, mandate = self._evaluate_with(connection, command)
            if decision.decision is not AuthorizationDecision.AUTHORIZED or mandate is None:
                return decision, None
            live_limit, _ = SqlitePolicyRepository(connection).active_limit_for(
                mandate.id, mandate.limit
            )
            spent = SqliteLedgerRepository(connection).spent_for(mandate.id, live_limit)
            return decision, LiveAuthorizationContext(
                mandate_ceiling=mandate.limit,
                live_balance=live_limit.subtract(spent),
                expires_at=mandate.expires_at,
            )


    def _evaluate_with(
        self,
        connection,
        command: AuthorizationCommand,
        approved_reasons: frozenset[str] = frozenset(),
    ) -> tuple[AuthorizationResult, Mandate | None]:
        # Every rung the ladder actually walked, in order. `cleared` records a rung that
        # held; `stopped` records the one that did not and freezes the trace there, so
        # the absence of a money check is itself evidence.
        walked: list[EvaluationStep] = []

        def cleared(check: str, detail: str | None = None) -> None:
            walked.append(EvaluationStep(check, True, detail))

        def stopped(check: str, detail: str) -> tuple[EvaluationStep, ...]:
            walked.append(EvaluationStep(check, False, detail))
            return tuple(walked)

        mandate = SqliteMandateRepository(connection).get(command.mandate_id)
        if mandate is None:
            return self._reject(
                "mandate_not_found",
                "Mandato não encontrado.",
                stopped("mandate_exists", f"mandato {command.mandate_id} não existe"),
            ), None
        cleared("mandate_exists", command.mandate_id)
        try:
            revocations = SqliteRevocationRepository(connection)
            revoked = revocations.is_revoked(command.mandate_id)
            budget_zero = revocations.has_scope(command.mandate_id, "budget:zero")
            merchant_revoked = revocations.has_scope(command.mandate_id, f"merchant:{command.merchant_id}")
        except Exception:
            # Unknown is not permitted. If revocation cannot be read, the answer is no.
            return self._reject(
                "revocation_unavailable",
                "Revogação indisponível; captura recusada.",
                stopped("revocation_readable", "store de revogação indisponível"),
            ), mandate
        cleared("revocation_readable")
        limit, _ = SqlitePolicyRepository(connection).active_limit_for(command.mandate_id, mandate.limit)
        if revoked or mandate.status is MandateStatus.REVOKED:
            return self._reject(
                "mandate_revoked",
                "Mandato revogado.",
                stopped("mandate_not_revoked", "mandato revogado pelo titular"),
            ), mandate
        cleared("mandate_not_revoked")
        # Whichever card is in play: the one this command presents, or — when the
        # command is a preview that carries none — the one the mandate itself names.
        # A cancelled card has to refuse the preview too, or the holder is told their
        # purchase needs approval when in truth their card no longer exists.
        instrument_id = getattr(command, "instrument_id", None) or (
            None if mandate.instrument is None else mandate.instrument.token
        )
        instrument_revoked = instrument_id is not None and revocations.has_scope(
            command.mandate_id, f"instrument:{instrument_id}"
        )
        if merchant_revoked:
            return self._reject(
                "merchant_revoked",
                "Merchant revogado para este mandato.",
                stopped("merchant_not_revoked", f"merchant {command.merchant_id} revogado"),
            ), mandate
        cleared("merchant_not_revoked", command.merchant_id)
        if instrument_revoked:
            return self._reject(
                "instrument_revoked",
                "Instrumento revogado para este mandato.",
                stopped("instrument_not_revoked", f"instrumento {instrument_id} revogado"),
            ), mandate
        if instrument_id is not None:
            cleared("instrument_not_revoked", instrument_id)
        if budget_zero and "budget_revoked" not in approved_reasons:
            return AuthorizationResult(
                AuthorizationDecision.AWAITING_HUMAN,
                "budget_revoked",
                "Orçamento do mandato foi zerado; aprovação humana necessária.",
                trace=stopped("budget_not_zeroed", "orçamento zerado por revogação de escopo"),
            ), mandate
        cleared("budget_not_zeroed")
        if mandate.status is MandateStatus.EXPIRED or self._clock() >= mandate.expires_at:
            return self._reject(
                "mandate_expired",
                "Mandato expirado.",
                stopped(
                    "mandate_not_expired",
                    f"validade {mandate.expires_at.isoformat()} já passou",
                ),
            ), mandate
        cleared("mandate_not_expired", mandate.expires_at.isoformat())
        if (
            command.merchant_id not in mandate.allowed_merchant_ids
            and "merchant_out_of_scope" not in approved_reasons
        ):
            return AuthorizationResult(
                AuthorizationDecision.AWAITING_HUMAN,
                "merchant_out_of_scope",
                "Merchant fora do escopo do mandato; aprovação humana necessária.",
                trace=stopped(
                    "merchant_in_scope",
                    f"{command.merchant_id} fora de {sorted(mandate.allowed_merchant_ids)}",
                ),
            ), mandate
        cleared("merchant_in_scope", command.merchant_id)
        if (
            command.category not in mandate.allowed_categories
            and "category_not_allowed" not in approved_reasons
        ):
            return AuthorizationResult(
                AuthorizationDecision.AWAITING_HUMAN,
                "category_not_allowed",
                "Categoria fora do escopo do mandato; aprovação humana necessária.",
                trace=stopped(
                    "category_in_scope",
                    f"{command.category} fora de {sorted(mandate.allowed_categories)}",
                ),
            ), mandate
        cleared("category_in_scope", command.category)
        # Only a capture carries an instrument, and only a capture moves money. The
        # pre-check above it is a preview: it deliberately does not spend the offer's
        # nonce either. Everything here is walked again at capture, so gating the rung
        # on the command that pays is not a hole — it is where the question is real.
        if isinstance(command, CaptureCommand) and mandate.instrument is not None:
            if command.instrument_id != mandate.instrument.token:
                return self._reject(
                    "instrument_not_in_mandate",
                    "Meio de pagamento não é o que o mandato nomeia.",
                    stopped(
                        "instrument_in_mandate",
                        "nenhum instrumento apresentado"
                        if command.instrument_id is None
                        else "instrumento apresentado não é o do mandato",
                    ),
                ), mandate
            cleared("instrument_in_mandate", mandate.instrument.label)
        assert limit is not None
        if (command.total.currency, command.total.scale) != (limit.currency, limit.scale):
            return self._reject(
                "money_unit_mismatch",
                "Moeda ou escala incompatível com o mandato.",
                stopped(
                    "money_unit_matches",
                    f"{command.total.currency}/{command.total.scale} != "
                    f"{limit.currency}/{limit.scale}",
                ),
            ), mandate
        cleared("money_unit_matches", f"{limit.currency}/{limit.scale}")
        if command.total.minor_units <= 0:
            return self._reject(
                "invalid_amount",
                "Valor de captura inválido.",
                stopped("amount_positive", f"valor {command.total.minor_units} não é positivo"),
            ), mandate
        cleared("amount_positive", str(command.total.minor_units))
        # The ceiling is fixed when the mandate is created. A live limit change moves the
        # budget, never this bound, so no approval path exists above it.
        if mandate.ceiling is not None and command.total.minor_units > mandate.ceiling.minor_units:
            return self._reject(
                "mandate_ceiling",
                "Valor acima do teto do mandato.",
                stopped(
                    "below_ceiling",
                    f"valor {command.total.minor_units} acima do teto "
                    f"{mandate.ceiling.minor_units}",
                ),
            ), mandate
        cleared(
            "below_ceiling",
            None if mandate.ceiling is None else f"teto {mandate.ceiling.minor_units}",
        )
        ledger = SqliteLedgerRepository(connection)
        # Griefing, not overspending. Every rung above this one answers "you may not
        # spend that"; this one answers an agent that never spends anything and still
        # leaves the buyer unable to buy — each unanswered capture holds budget, and
        # holding it is correct, so a loop reserves the whole mandate without moving a
        # cent. It refuses rather than escalates: a human pressing approve does not
        # unstick money that is already stuck, so there is no handle to sign and there
        # must be no button to press. Reconciling is what frees a slot.
        #
        # It is not mandate authority either. The holder never asked for a griefing
        # allowance; this protects them from their own agent, so it is a property of
        # the layer and not a field the mandate grants.
        live = ledger.live_reservations(mandate.id)
        slot_detail = f"{live} reserva(s) viva(s) contra o teto de {self._max_live_reservations}"
        if live >= self._max_live_reservations:
            return self._reject(
                "reservation_limit",
                "Reservas em aberto demais neste mandato; reconcilie antes de comprar.",
                stopped("reservation_slot_free", slot_detail),
            ), mandate
        cleared("reservation_slot_free", slot_detail)
        # Frequency sits between the ceiling and the budget on purpose. It is authority
        # over *how often*, the way the budget is authority over *how much*, so it is
        # approvable — a human may still say yes to a fourth purchase. The ceiling
        # remains the only bound with no approval path at all.
        if mandate.usage_limit is not None:
            window = timedelta(seconds=mandate.usage_limit.window_seconds)
            used = ledger.uses_since(mandate.id, self._clock() - window)
            usage_detail = (
                f"{used} uso{'s' if used != 1 else ''} em "
                f"{mandate.usage_limit.window_seconds}s {{}} o máximo de "
                f"{mandate.usage_limit.max_uses}"
            )
            if used >= mandate.usage_limit.max_uses and "usage_limit_exceeded" not in approved_reasons:
                return AuthorizationResult(
                    AuthorizationDecision.AWAITING_HUMAN,
                    "usage_limit_exceeded",
                    "Compra excede a frequência permitida pelo mandato.",
                    trace=stopped("within_usage_window", usage_detail.format("atinge")),
                ), mandate
            cleared("within_usage_window", usage_detail.format("cabe no"))
        spent = ledger.spent_for(mandate.id, limit)
        over_budget = spent.add(command.total).minor_units > limit.minor_units
        budget_detail = (
            f"gasto {spent.minor_units} + {command.total.minor_units} "
            f"{{}} o limite {limit.minor_units}"
        )
        if over_budget and "budget_exceeded" not in approved_reasons:
            return AuthorizationResult(
                AuthorizationDecision.AWAITING_HUMAN,
                "budget_exceeded",
                "Compra excede o orçamento vivo do mandato.",
                trace=stopped("within_budget", budget_detail.format("excede")),
            ), mandate
        cleared("within_budget", budget_detail.format("cabe em"))
        return AuthorizationResult(
            AuthorizationDecision.AUTHORIZED,
            "authorized",
            "Compra autorizada.",
            trace=tuple(walked),
        ), mandate

    def capture(
        self,
        command: CaptureCommand,
        *,
        agent_id: str | None = None,
        approved_reasons: frozenset[str] = frozenset(),
    ) -> CaptureResult:
        # Every field that makes this a different purchase belongs in the hash: change
        # the category, the terms or the instrument and it is not the same charge.
        request_hash = command.idempotency_fingerprint or hashlib.sha256(json.dumps({"mandate": command.mandate_id, "checkout": command.checkout_id, "merchant": command.merchant_id, "amount": command.total.minor_units, "currency": command.total.currency, "scale": command.total.scale, "category": command.category, "terms": command.terms_hash, "instrument": command.instrument_id}, sort_keys=True).encode()).hexdigest()
        def prepare(connection):
            SqliteMandateLockRepository(connection).acquire(
                command.mandate_id, touched_at=self._clock()
            )
            idem = SqliteIdempotencyRepository(connection)
            try:
                claim = idem.get_or_claim("capture", command.idempotency_key, request_hash)
            except Exception:
                return ("result", CaptureResult(False, "idempotency_unavailable"))
            if claim.state == "REPLAY":
                return ("replay", claim.response_body)
            if claim.state == "MISMATCH":
                return ("result", CaptureResult(False, "idempotency_key_reused"))
            if claim.state == "IN_FLIGHT":
                return ("result", CaptureResult(False, "idempotency_in_flight"))
            decision, mandate = self._evaluate_with(connection, command, approved_reasons)
            if decision.decision is not AuthorizationDecision.AUTHORIZED:
                escalation_id = None
                if (
                    mandate is not None
                    and decision.decision is AuthorizationDecision.AWAITING_HUMAN
                ):
                    escalation_id = self._open_escalation(
                        connection, command, decision, agent_id
                    )
                    decision = replace(decision, escalation_id=escalation_id)
                result = CaptureResult(False, decision.reason_code, escalation_id=escalation_id)
                if mandate is not None:
                    SqliteAuditLedger(connection).append(
                        mandate_id=command.mandate_id,
                        event_type=self.DECISION_EVENTS[decision.decision],
                        human_summary=decision.human_summary,
                        actor="aval-core",
                        detail=self._purchase_detail(
                            command, decision, agent_id=agent_id, escalation_id=escalation_id
                        ),
                        occurred_at=self._clock(),
                    )
                idem.complete("capture", command.idempotency_key, self._serialize_result(result))
                return ("result", result)
            assert mandate is not None
            ledger = SqliteLedgerRepository(connection)
            if ledger.find_by_transaction(command.mandate_id, request_hash, command.total) is not None:
                result = CaptureResult(False, "transaction_already_captured")
                idem.complete("capture", command.idempotency_key, self._serialize_result(result))
                return ("result", result)
            pending = Reservation(f"rsv_{uuid4().hex}", command.mandate_id, command.checkout_id, command.total)
            ledger.save(
                pending,
                merchant_id=command.merchant_id,
                canonical_payload=command.canonical_offer,
            )
            reservation = pending.commit(request_hash)
            ledger.update(reservation, at=self._clock())
            attempt_id = f"cap_{uuid4().hex}"
            SqliteCaptureRepository(connection).create(attempt_id=attempt_id, reservation_id=reservation.id, idempotency_key=command.idempotency_key)
            if self._authorization_proof_issuer:
                issued_proof = self._authorization_proof_issuer.issue(
                    reservation, policy_version=mandate.policy_version,
                    revocation_epoch=int(mandate.revocation_metadata.get("epoch", 0)),
                    merchant_id=command.merchant_id, terms_hash=command.terms_hash,
                )
                connection.execute(authorization_proofs.insert().values(
                    id=issued_proof.id, reservation_id=reservation.id, jti=issued_proof.jti,
                    expires_at=issued_proof.expires_at, signed_proof=issued_proof.signed_proof,
                ))
                proof = issued_proof.signed_proof
                proof_jti = issued_proof.jti
            else:
                proof = f"proof_{reservation.id}"
                proof_jti = None
            # The decision and the commit are different facts. Sharing one name made a
            # single purchase read as two attempts in the auditor view.
            SqliteAuditLedger(connection).append(
                mandate_id=command.mandate_id,
                event_type="purchase_committed",
                human_summary=f"Compra autorizada e comprometida ({reservation.id}).",
                actor="aval-core",
                detail=self._purchase_detail(
                    command,
                    decision,
                    agent_id=agent_id,
                    reservation_id=reservation.id,
                    transaction_hash=reservation.transaction_hash,
                    policy_version=mandate.policy_version,
                    revocation_epoch=int(mandate.revocation_metadata.get("epoch", 0)),
                    terms_hash=command.terms_hash,
                    proof_jti=proof_jti,
                ),
                occurred_at=self._clock(),
            )
            return ("prepared", reservation, attempt_id, proof, proof_jti)
        prepared = run_in_write_transaction(self._engine, prepare)
        if prepared[0] == "replay":
            return replace(self._deserialize_result(prepared[1]), replayed=True)
        if prepared[0] == "result":
            return prepared[1]
        _, reservation, attempt_id, proof, proof_jti = prepared
        if self._settlement_adapter is None:
            result = CaptureResult(True, "committed", reservation, authorization_proof=proof)
        else:
            try:
                settlement = self._settlement_adapter.authorize(reservation, proof)
            except Exception:
                # Unknown is a state, not an outcome. The budget stays held either way —
                # that part was always right — but silence in the trail is what made a
                # held purchase indistinguishable from a broken one on the buyer's
                # screen. Name the state, then let the error surface as it did before.
                self._record_payment_in_doubt(
                    attempt_id=attempt_id,
                    mandate_id=command.mandate_id,
                    reservation=reservation,
                    command=command,
                    agent_id=agent_id,
                )
                raise
            final = reservation.settle() if settlement.approved else reservation.release()
            result = CaptureResult(
                settlement.approved,
                "settled" if settlement.approved else "settlement_declined",
                final,
                settlement.reference,
                authorization_proof=proof,
            )
        def finish(connection):
            SqliteLedgerRepository(connection).update(result.reservation)
            SqliteCaptureRepository(connection).complete(attempt_id, approved=result.approved, reference=result.settlement_reference)
            SqliteIdempotencyRepository(connection).complete("capture", command.idempotency_key, self._serialize_result(result))
            SqliteAuditLedger(connection).append(
                mandate_id=command.mandate_id,
                event_type="purchase_settled" if result.approved else "purchase_declined",
                human_summary=(
                    "Pagamento liquidado."
                    if result.approved
                    else "Pagamento recusado pelo processador."
                ),
                actor="psp:demo",
                detail={
                    "agent_id": agent_id,
                    "checkout_id": command.checkout_id,
                    "merchant_id": command.merchant_id,
                    "reservation_id": reservation.id,
                    "amount_minor_units": command.total.minor_units,
                    "currency": command.total.currency,
                    "scale": command.total.scale,
                    "instrument_id": command.instrument_id,
                    "reason_code": result.reason_code,
                    "settlement_reference": result.settlement_reference,
                    # The capture vocabulary the checkout adapters read.
                    "capture_state": "capture.committed" if result.approved else "capture.declined",
                    # The vocabulary a person reads. Three states, never two.
                    "payment_state": "settled" if result.approved else "declined",
                },
                occurred_at=self._clock(),
            )
        run_in_write_transaction(self._engine, finish)
        return result

    def _record_payment_in_doubt(
        self,
        *,
        attempt_id: str,
        mandate_id: str,
        reservation: Reservation,
        command: CaptureCommand,
        agent_id: str | None,
    ) -> None:
        """Write the third state down, without touching the money.

        The reservation stays `COMMITTED` and the idempotency claim stays in flight:
        releasing either would be reading *no answer* as *no charge*, which is the one
        mistake that double-spends a payment that actually settled on the other side.
        """

        def operation(connection) -> None:
            connection.execute(
                update(capture_attempts)
                .where(capture_attempts.c.id == attempt_id)
                .values(status="IN_DOUBT")
            )
            SqliteAuditLedger(connection).append(
                mandate_id=mandate_id,
                event_type="payment_in_doubt",
                human_summary="Pagamento em confirmação: o processador não respondeu.",
                actor="psp:demo",
                detail={
                    "agent_id": agent_id,
                    "checkout_id": command.checkout_id,
                    "merchant_id": command.merchant_id,
                    "reservation_id": reservation.id,
                    "amount_minor_units": command.total.minor_units,
                    "currency": command.total.currency,
                    "scale": command.total.scale,
                    "reason_code": "settlement_unreachable",
                    "payment_state": "in_doubt",
                },
                occurred_at=self._clock(),
            )

        run_in_write_transaction(self._engine, operation)

    @staticmethod
    def _serialize_result(result: CaptureResult) -> str:
        reservation = result.reservation
        return json.dumps({"approved": result.approved, "reason_code": result.reason_code, "reference": result.settlement_reference, "escalation_id": result.escalation_id, "authorization_proof": result.authorization_proof, "reservation": None if reservation is None else {"id": reservation.id, "mandate_id": reservation.mandate_id, "checkout_id": reservation.checkout_intent_id, "amount": reservation.amount.minor_units, "currency": reservation.amount.currency, "scale": reservation.amount.scale, "status": reservation.status.value, "transaction_hash": reservation.transaction_hash}})

    @staticmethod
    def _deserialize_result(body: str | None) -> CaptureResult:
        assert body is not None
        value = json.loads(body)
        item = value["reservation"]
        reservation = None if item is None else Reservation(item["id"], item["mandate_id"], item["checkout_id"], Money(item["amount"], item["currency"], item["scale"]), ReservationStatus(item["status"]), item["transaction_hash"])
        return CaptureResult(
            value["approved"],
            value["reason_code"],
            reservation,
            value["reference"],
            value.get("escalation_id"),
            value.get("authorization_proof"),
        )

    @staticmethod
    def _is_canonical_revocation_scope(scope: str) -> bool:
        if scope in {"mandate", "budget:zero"}:
            return True
        if scope.startswith("merchant:"):
            return bool(scope.removeprefix("merchant:"))
        if scope.startswith("instrument:vt_"):
            return len(scope) > len("instrument:vt_")
        return False

    @staticmethod
    def _reject(
        reason_code: str, human_summary: str, trace: tuple[EvaluationStep, ...] = ()
    ) -> AuthorizationResult:
        return AuthorizationResult(
            AuthorizationDecision.REJECTED, reason_code, human_summary, trace=trace
        )


def _jws_kid(token: str | None) -> str:
    """The key id a compact JWS announces, read without verifying it.

    Verification already happened when the signature was accepted and stored; this is
    the ledger's own copy being labelled, not a credential being trusted.
    """
    if not token:
        return "unknown"
    try:
        header = token.split(".")[0]
        decoded = json.loads(base64.urlsafe_b64decode(header + "=" * (-len(header) % 4)))
    except (ValueError, IndexError):
        return "unknown"
    return str(decoded.get("kid", "unknown"))
