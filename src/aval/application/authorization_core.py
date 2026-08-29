from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
import base64
import hashlib
import json
from uuid import uuid4

from sqlalchemy import Engine, create_engine, select
from sqlalchemy.pool import StaticPool

from aval.application.ports import AuthorizationProofIssuer, SettlementAdapter
from aval.domain.entities import Dispute, Mandate, Reservation, Revocation
from aval.domain.enums import AuthorizationDecision, DisputeStatus, MandateStatus, ReservationStatus
from aval.domain.money import Money
from aval.security.jws import verify_compact_jws
from aval.security.key_custody import public_key_from_jwk
from aval.infrastructure.sqlite.mandate_repository import SqliteMandateRepository
from aval.infrastructure.sqlite.models import authorization_proofs, disputes, metadata, reservations
from aval.infrastructure.sqlite.ledger_repository import SqliteLedgerRepository
from aval.infrastructure.sqlite.idempotency_repository import SqliteIdempotencyRepository
from aval.infrastructure.sqlite.capture_repository import SqliteCaptureRepository
from aval.infrastructure.sqlite.policy_repository import SqlitePolicyRepository
from aval.infrastructure.sqlite.revocation_repository import SqliteRevocationRepository
from aval.infrastructure.sqlite.transaction import run_in_write_transaction


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
    terms_hash: str | None = None


@dataclass(frozen=True)
class AuthorizationResult:
    decision: AuthorizationDecision
    reason_code: str
    human_summary: str


@dataclass(frozen=True)
class SettlementResult:
    approved: bool
    reference: str | None = None


@dataclass(frozen=True)
class CaptureResult:
    approved: bool
    reason_code: str
    reservation: Reservation | None = None
    settlement_reference: str | None = None


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
        self._engine = engine or create_engine(
            "sqlite+pysqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        metadata.create_all(self._engine)
        self._settlement_adapter = settlement_adapter
        self._authorization_proof_issuer = authorization_proof_issuer

    def register_mandate(self, mandate: Mandate) -> None:
        run_in_write_transaction(self._engine, lambda connection: SqliteMandateRepository(connection).put(mandate))

    def replace_live_limit(self, mandate_id: str, limit: Money) -> None:
        def operation(connection) -> None:
            mandate = SqliteMandateRepository(connection).get(mandate_id)
            if mandate is None:
                raise ValueError("mandate not found")
            version = SqlitePolicyRepository(connection).replace_limit(mandate_id, limit)
            metadata = dict(mandate.revocation_metadata)
            metadata["epoch"] = int(metadata.get("epoch", 0)) + 1
            SqliteMandateRepository(connection).put(
                replace(mandate, policy_version=version, revocation_metadata=metadata)
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
            for mandate in mandates:
                for authority in mandate.authorities:
                    if authority.kid != kid:
                        continue
                    payload = verify_compact_jws(token, public_key_from_jwk(dict(authority.public_jwk)))
                    if payload.get("mandate_id") != mandate.id:
                        raise ValueError("revocation mandate does not match authority")
                    if payload.get("scope") not in authority.allowed_scopes:
                        raise ValueError("revocation scope is not allowed")
                    if not payload.get("reason") or not isinstance(payload.get("epoch"), int):
                        raise ValueError("revocation payload is incomplete")
                    revocation = Revocation(
                        id=f"rev_{uuid4().hex}", mandate_id=mandate.id, authority_id=authority.id,
                        scope=str(payload["scope"]), reason=str(payload["reason"]), epoch=int(payload["epoch"]),
                        signed_jws=token, revoked_at=self._clock(),
                    )
                    SqliteRevocationRepository(connection).append(revocation)
                    metadata = dict(mandate.revocation_metadata)
                    metadata["epoch"] = revocation.epoch
                    SqliteMandateRepository(connection).put(replace(mandate, status=MandateStatus.REVOKED, revocation_metadata=metadata))
                    return
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
            return resolved

        return run_in_write_transaction(self._engine, operation)

    @staticmethod
    def _proof_payload(signed_proof: str) -> dict:
        """Read the payload AVAL itself recorded. Signature verification belongs to the
        merchant, which holds the token; this row is the ledger's own copy."""
        encoded = signed_proof.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))

    def evaluate(self, command: AuthorizationCommand) -> AuthorizationResult:
        with self._engine.connect() as connection:
            return self._evaluate_with(connection, command)[0]

    def _evaluate_with(self, connection, command: AuthorizationCommand) -> tuple[AuthorizationResult, Mandate | None]:
        mandate = SqliteMandateRepository(connection).get(command.mandate_id)
        revoked = mandate is not None and SqliteRevocationRepository(connection).is_revoked(command.mandate_id)
        limit, _ = SqlitePolicyRepository(connection).active_limit_for(command.mandate_id, mandate.limit) if mandate else (None, 0)
        if mandate is None:
            return self._reject("mandate_not_found", "Mandato não encontrado."), None
        if revoked or mandate.status is MandateStatus.REVOKED:
            return self._reject("mandate_revoked", "Mandato revogado."), mandate
        if mandate.status is MandateStatus.EXPIRED or self._clock() >= mandate.expires_at:
            return self._reject("mandate_expired", "Mandato expirado."), mandate
        if command.merchant_id not in mandate.allowed_merchant_ids:
            return AuthorizationResult(
                AuthorizationDecision.AWAITING_HUMAN,
                "merchant_out_of_scope",
                "Merchant fora do escopo do mandato; aprovação humana necessária.",
            ), mandate
        if command.category not in mandate.allowed_categories:
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
        if SqliteLedgerRepository(connection).spent_for(mandate.id, limit).add(command.total).minor_units > limit.minor_units:
            return AuthorizationResult(
                AuthorizationDecision.AWAITING_HUMAN,
                "budget_exceeded",
                "Compra excede o orçamento vivo do mandato.",
            ), mandate
        return AuthorizationResult(AuthorizationDecision.AUTHORIZED, "authorized", "Compra autorizada."), mandate

    def capture(self, command: CaptureCommand) -> CaptureResult:
        request_hash = hashlib.sha256(json.dumps({"mandate": command.mandate_id, "checkout": command.checkout_id, "merchant": command.merchant_id, "amount": command.total.minor_units, "currency": command.total.currency, "scale": command.total.scale, "category": command.category, "terms": command.terms_hash}, sort_keys=True).encode()).hexdigest()
        def prepare(connection):
            idem = SqliteIdempotencyRepository(connection)
            claim = idem.get_or_claim("capture", command.idempotency_key, request_hash)
            if claim.state == "REPLAY":
                return ("replay", claim.response_body)
            if claim.state == "MISMATCH":
                return ("result", CaptureResult(False, "idempotency_key_reused"))
            if claim.state == "IN_FLIGHT":
                return ("result", CaptureResult(False, "idempotency_in_flight"))
            decision, mandate = self._evaluate_with(connection, command)
            if decision.decision is not AuthorizationDecision.AUTHORIZED:
                result = CaptureResult(False, decision.reason_code)
                idem.complete("capture", command.idempotency_key, self._serialize_result(result))
                return ("result", result)
            assert mandate is not None
            ledger = SqliteLedgerRepository(connection)
            if ledger.find_by_transaction(command.mandate_id, request_hash, command.total) is not None:
                result = CaptureResult(False, "transaction_already_captured")
                idem.complete("capture", command.idempotency_key, self._serialize_result(result))
                return ("result", result)
            pending = Reservation(f"rsv_{uuid4().hex}", command.mandate_id, command.checkout_id, command.total)
            ledger.save(pending, merchant_id=command.merchant_id)
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
            else:
                proof = f"proof_{reservation.id}"
            return ("prepared", reservation, attempt_id, proof)
        prepared = run_in_write_transaction(self._engine, prepare)
        if prepared[0] == "replay":
            return self._deserialize_result(prepared[1])
        if prepared[0] == "result":
            return prepared[1]
        _, reservation, attempt_id, proof = prepared
        if self._settlement_adapter is None:
            result = CaptureResult(True, "committed", reservation)
        else:
            settlement = self._settlement_adapter.authorize(reservation, proof)
            final = reservation.settle() if settlement.approved else reservation.release()
            result = CaptureResult(settlement.approved, "settled" if settlement.approved else "settlement_declined", final, settlement.reference)
        def finish(connection):
            SqliteLedgerRepository(connection).update(result.reservation)
            SqliteCaptureRepository(connection).complete(attempt_id, approved=result.approved, reference=result.settlement_reference)
            SqliteIdempotencyRepository(connection).complete("capture", command.idempotency_key, self._serialize_result(result))
        run_in_write_transaction(self._engine, finish)
        return result

    @staticmethod
    def _serialize_result(result: CaptureResult) -> str:
        reservation = result.reservation
        return json.dumps({"approved": result.approved, "reason_code": result.reason_code, "reference": result.settlement_reference, "reservation": None if reservation is None else {"id": reservation.id, "mandate_id": reservation.mandate_id, "checkout_id": reservation.checkout_intent_id, "amount": reservation.amount.minor_units, "currency": reservation.amount.currency, "scale": reservation.amount.scale, "status": reservation.status.value, "transaction_hash": reservation.transaction_hash}})

    @staticmethod
    def _deserialize_result(body: str | None) -> CaptureResult:
        assert body is not None
        value = json.loads(body)
        item = value["reservation"]
        reservation = None if item is None else Reservation(item["id"], item["mandate_id"], item["checkout_id"], Money(item["amount"], item["currency"], item["scale"]), ReservationStatus(item["status"]), item["transaction_hash"])
        return CaptureResult(value["approved"], value["reason_code"], reservation, value["reference"])

    @staticmethod
    def _reject(reason_code: str, human_summary: str) -> AuthorizationResult:
        return AuthorizationResult(AuthorizationDecision.REJECTED, reason_code, human_summary)
