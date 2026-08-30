from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
import base64
import hashlib
import json
from uuid import uuid4

from sqlalchemy import Engine, create_engine, select
from sqlalchemy.pool import StaticPool

from aval.application.ports import AuthorizationProofIssuer, SettlementAdapter
from aval.domain.entities import (
    AgentIdentity,
    AuditEvent,
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
    metadata,
    reservations,
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
APPROVABLE_REASONS = frozenset({"merchant_out_of_scope", "category_not_allowed", "budget_exceeded"})

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


@dataclass(frozen=True)
class AuthorizationResult:
    decision: AuthorizationDecision
    reason_code: str
    human_summary: str
    escalation_id: str | None = None


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


@dataclass(frozen=True)
class LiveAuthorizationContext:
    """Current Core facts safe to project into a short-lived edge allowance."""

    mandate_ceiling: Money
    live_balance: Money
    expires_at: datetime


class AuthorizationCore:
    """The sole writer for the in-process authorization state used by the MVP."""

    def __init__(
        self,
        *,
        clock: Callable[[], datetime],
        engine: Engine | None = None,
        settlement_adapter: SettlementAdapter | None = None,
        authorization_proof_issuer: AuthorizationProofIssuer | None = None,
    ) -> None:
        self._clock = clock
        if engine is None:
            self._engine = create_engine(
                "sqlite+pysqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
            )
            metadata.create_all(self._engine)
        else:
            self._engine = engine
        self._settlement_adapter = settlement_adapter
        self._authorization_proof_issuer = authorization_proof_issuer

    def register_mandate(self, mandate: Mandate) -> None:
        def operation(connection) -> None:
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
                },
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

    def replace_live_limit(
        self, mandate_id: str, limit: Money, *, authorization_jws: str | None = None
    ) -> None:
        """Move the live budget.

        Raising a limit is raising how much of someone else's money an agent may spend,
        so it is proved the same way a revocation is: with the holder's own key over a
        payload that names this mandate and this exact amount. An operator credential is
        deliberately not accepted here — running the service is not the same as owning
        the mandate.

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
        try:
            encoded_header = token.split(".")[0]
            header = json.loads(base64.urlsafe_b64decode(encoded_header + "=" * (-len(encoded_header) % 4)))
            kid = header["kid"]
        except (IndexError, KeyError, ValueError, json.JSONDecodeError) as error:
            raise ValueError("malformed revocation JWS") from error
        def operation(connection) -> None:
            mandates = SqliteMandateRepository(connection).for_authority_kid(kid)
            # One person may hold several mandates under the same key: renewing a mandate
            # does not give someone a new phone. So a key id selects *candidates*, and the
            # token itself says which one it is about. A candidate that is not the named
            # mandate is simply not this token's business — skipping it is what keeps a
            # revocation working when a sibling mandate happens to be scanned first.
            signature_failure: ValueError | None = None
            for mandate in mandates:
                for authority in mandate.authorities:
                    if authority.kid != kid:
                        continue
                    try:
                        payload = verify_compact_jws(
                            token, public_key_from_jwk(dict(authority.public_jwk))
                        )
                    except ValueError as error:
                        # Two mandates may register different key material under the same
                        # kid. Remember why this one failed and keep looking; if nothing
                        # verifies, this is the answer the caller gets.
                        signature_failure = error
                        continue
                    if payload.get("mandate_id") != mandate.id:
                        continue
                    scope = payload.get("scope")
                    if not isinstance(scope, str) or not self._is_canonical_revocation_scope(scope):
                        raise ValueError("invalid revocation scope")
                    if scope not in authority.allowed_scopes:
                        raise ValueError("revocation scope is not allowed")
                    if authority.role in (RevocationRole.GUARDIAN, RevocationRole.ISSUER) and scope != "mandate":
                        raise ValueError("guardian and issuer may only revoke the mandate")
                    if not payload.get("reason") or not isinstance(payload.get("epoch"), int):
                        raise ValueError("revocation payload is incomplete")
                    SqliteMandateLockRepository(connection).acquire(
                        mandate.id, touched_at=self._clock()
                    )
                    revocation = Revocation(
                        id=f"rev_{uuid4().hex}", mandate_id=mandate.id, authority_id=authority.id,
                        scope=scope, reason=str(payload["reason"]), epoch=int(payload["epoch"]),
                        signed_jws=token, revoked_at=self._clock(),
                    )
                    SqliteRevocationRepository(connection).append(revocation)
                    metadata = dict(mandate.revocation_metadata)
                    metadata["epoch"] = revocation.epoch
                    # Only a mandate-scoped revocation ends the mandate. An instrument
                    # or merchant scope withdraws part of the authority and leaves the
                    # rest standing, which is why the status is not touched here.
                    if scope == "mandate":
                        mandate = replace(mandate, status=MandateStatus.REVOKED, revocation_metadata=metadata)
                    else:
                        mandate = replace(mandate, revocation_metadata=metadata)
                    SqliteMandateRepository(connection).put(mandate)
                    # `revocation.{role}` names *who* withdrew the authority, which is
                    # what makes an emergency operator revocation answerable later.
                    SqliteAuditLedger(connection).append(
                        mandate_id=mandate.id,
                        event_type=f"revocation.{authority.role.value}",
                        human_summary=f"Revogação de escopo {scope} por {authority.role.value} aceita.",
                        actor=f"authority:{authority.kid}",
                        detail={
                            "scope": revocation.scope,
                            "reason": revocation.reason,
                            "epoch": revocation.epoch,
                            "authority_role": authority.role.value,
                        },
                        occurred_at=self._clock(),
                    )
                    return
            # Nothing verified. A forged signature is a more precise answer than an
            # unknown authority, so report it when that is what actually happened.
            if signature_failure is not None:
                raise signature_failure
            raise ValueError("unknown revocation authority")
        run_in_write_transaction(self._engine, operation)

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
                },
                occurred_at=resolved.resolved_at,
            )
            return resolved

        return run_in_write_transaction(self._engine, operation)

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
                .where(capture_attempts.c.status == "PENDING")
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
        capture = self.capture(
            CaptureCommand(
                mandate_id=escalation.mandate_id,
                checkout_id=escalation.checkout_id,
                merchant_id=escalation.merchant_id,
                total=escalation.amount,
                category=escalation.category,
                # Derived from the handle, so approving twice can never charge twice.
                idempotency_key=f"esc_{escalation.id}",
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
            spent = SqliteLedgerRepository(connection).spent_for(mandate_id, limit)
            return MandateSnapshot(mandate=mandate, limit=limit, spent=spent)

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
        mandate = SqliteMandateRepository(connection).get(command.mandate_id)
        if mandate is None:
            return self._reject("mandate_not_found", "Mandato não encontrado."), None
        try:
            revocations = SqliteRevocationRepository(connection)
            revoked = revocations.is_revoked(command.mandate_id)
            budget_zero = revocations.has_scope(command.mandate_id, "budget:zero")
            merchant_revoked = revocations.has_scope(command.mandate_id, f"merchant:{command.merchant_id}")
        except Exception:
            return self._reject("revocation_unavailable", "Revogação indisponível; captura recusada."), mandate
        limit, _ = SqlitePolicyRepository(connection).active_limit_for(command.mandate_id, mandate.limit)
        if revoked or mandate.status is MandateStatus.REVOKED:
            return self._reject("mandate_revoked", "Mandato revogado."), mandate
        instrument_id = getattr(command, "instrument_id", None)
        instrument_revoked = instrument_id is not None and revocations.has_scope(
            command.mandate_id, f"instrument:{instrument_id}"
        )
        if merchant_revoked:
            return self._reject("merchant_revoked", "Merchant revogado para este mandato."), mandate
        if instrument_revoked:
            return self._reject("instrument_revoked", "Instrumento revogado para este mandato."), mandate
        if budget_zero:
            return AuthorizationResult(
                AuthorizationDecision.AWAITING_HUMAN,
                "budget_revoked",
                "Orçamento do mandato foi zerado; aprovação humana necessária.",
            ), mandate
        if mandate.status is MandateStatus.EXPIRED or self._clock() >= mandate.expires_at:
            return self._reject("mandate_expired", "Mandato expirado."), mandate
        if (
            command.merchant_id not in mandate.allowed_merchant_ids
            and "merchant_out_of_scope" not in approved_reasons
        ):
            return AuthorizationResult(
                AuthorizationDecision.AWAITING_HUMAN,
                "merchant_out_of_scope",
                "Merchant fora do escopo do mandato; aprovação humana necessária.",
            ), mandate
        if (
            command.category not in mandate.allowed_categories
            and "category_not_allowed" not in approved_reasons
        ):
            return AuthorizationResult(
                AuthorizationDecision.AWAITING_HUMAN,
                "category_not_allowed",
                "Categoria fora do escopo do mandato; aprovação humana necessária.",
            ), mandate
        assert limit is not None
        if (command.total.currency, command.total.scale) != (limit.currency, limit.scale):
            return self._reject("money_unit_mismatch", "Moeda ou escala incompatível com o mandato."), mandate
        if command.total.minor_units <= 0:
            return self._reject("invalid_amount", "Valor de captura inválido."), mandate
        # The ceiling is fixed when the mandate is created. A live limit change moves the
        # budget, never this bound, so no approval path exists above it.
        if mandate.ceiling is not None and command.total.minor_units > mandate.ceiling.minor_units:
            return self._reject("mandate_ceiling", "Valor acima do teto do mandato."), mandate
        over_budget = (
            SqliteLedgerRepository(connection)
            .spent_for(mandate.id, limit)
            .add(command.total)
            .minor_units
            > limit.minor_units
        )
        if over_budget and "budget_exceeded" not in approved_reasons:
            return AuthorizationResult(
                AuthorizationDecision.AWAITING_HUMAN,
                "budget_exceeded",
                "Compra excede o orçamento vivo do mandato.",
            ), mandate
        return AuthorizationResult(AuthorizationDecision.AUTHORIZED, "authorized", "Compra autorizada."), mandate

    def capture(
        self,
        command: CaptureCommand,
        *,
        agent_id: str | None = None,
        approved_reasons: frozenset[str] = frozenset(),
    ) -> CaptureResult:
        # Every field that makes this a different purchase belongs in the hash: change
        # the category, the terms or the instrument and it is not the same charge.
        request_hash = hashlib.sha256(json.dumps({"mandate": command.mandate_id, "checkout": command.checkout_id, "merchant": command.merchant_id, "amount": command.total.minor_units, "currency": command.total.currency, "scale": command.total.scale, "category": command.category, "terms": command.terms_hash, "instrument": command.instrument_id}, sort_keys=True).encode()).hexdigest()
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
            ledger.update(reservation)
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
            return self._deserialize_result(prepared[1])
        if prepared[0] == "result":
            return prepared[1]
        _, reservation, attempt_id, proof, proof_jti = prepared
        if self._settlement_adapter is None:
            result = CaptureResult(True, "committed", reservation, authorization_proof=proof)
        else:
            settlement = self._settlement_adapter.authorize(reservation, proof)
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
                },
                occurred_at=self._clock(),
            )
        run_in_write_transaction(self._engine, finish)
        return result

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
    def _reject(reason_code: str, human_summary: str) -> AuthorizationResult:
        return AuthorizationResult(AuthorizationDecision.REJECTED, reason_code, human_summary)
