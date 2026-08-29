from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
import base64
import hashlib
import json
from uuid import uuid4

from sqlalchemy import Engine, create_engine
from sqlalchemy.pool import StaticPool

from aval.application.ports import AuthorizationProofIssuer, SettlementAdapter
from aval.domain.entities import AuditEvent, Mandate, Reservation, Revocation
from aval.domain.enums import AuthorizationDecision, MandateStatus, ReservationStatus
from aval.domain.money import Money
from aval.security.jws import verify_compact_jws
from aval.security.key_custody import public_key_from_jwk
from aval.infrastructure.sqlite.mandate_repository import SqliteMandateRepository
from aval.infrastructure.sqlite.models import authorization_proofs, metadata
from aval.infrastructure.sqlite.ledger_repository import SqliteLedgerRepository
from aval.infrastructure.sqlite.idempotency_repository import SqliteIdempotencyRepository
from aval.infrastructure.sqlite.capture_repository import SqliteCaptureRepository
from aval.infrastructure.sqlite.policy_repository import SqlitePolicyRepository
from aval.infrastructure.sqlite.revocation_repository import SqliteRevocationRepository
from aval.infrastructure.sqlite.audit_repository import SqliteAuditRepository
from aval.infrastructure.sqlite.transaction import run_in_write_transaction


@dataclass(frozen=True)
class AuthorizationCommand:
    mandate_id: str
    checkout_id: str
    merchant_id: str
    total: Money


@dataclass(frozen=True)
class CaptureCommand(AuthorizationCommand):
    idempotency_key: str


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
                    if revocation.scope == "mandate":
                        mandate = replace(mandate, status=MandateStatus.REVOKED, revocation_metadata=metadata)
                    else:
                        mandate = replace(mandate, revocation_metadata=metadata)
                    SqliteMandateRepository(connection).put(mandate)
                    return
            raise ValueError("unknown revocation authority")
        run_in_write_transaction(self._engine, operation)

    def evaluate(self, command: AuthorizationCommand) -> AuthorizationResult:
        with self._engine.connect() as connection:
            return self._evaluate_with(connection, command)[0]

    def _evaluate_with(self, connection, command: AuthorizationCommand) -> tuple[AuthorizationResult, Mandate | None]:
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
        if merchant_revoked:
            return self._reject("merchant_revoked", "Merchant revogado para este mandato."), mandate
        if budget_zero:
            return AuthorizationResult(
                AuthorizationDecision.AWAITING_HUMAN,
                "budget_revoked",
                "Orçamento do mandato foi zerado; aprovação humana necessária.",
            ), mandate
        if mandate.status is MandateStatus.EXPIRED or self._clock() >= mandate.expires_at:
            return self._reject("mandate_expired", "Mandato expirado."), mandate
        if command.merchant_id not in mandate.allowed_merchant_ids:
            return AuthorizationResult(
                AuthorizationDecision.AWAITING_HUMAN,
                "merchant_out_of_scope",
                "Merchant fora do escopo do mandato; aprovação humana necessária.",
            ), mandate
        assert limit is not None
        if (command.total.currency, command.total.scale) != (limit.currency, limit.scale):
            return self._reject("money_unit_mismatch", "Moeda ou escala incompatível com o mandato."), mandate
        if command.total.minor_units <= 0:
            return self._reject("invalid_amount", "Valor de captura inválido."), mandate
        if SqliteLedgerRepository(connection).spent_for(mandate.id, limit).add(command.total).minor_units > limit.minor_units:
            return AuthorizationResult(
                AuthorizationDecision.AWAITING_HUMAN,
                "budget_exceeded",
                "Compra excede o orçamento vivo do mandato.",
            ), mandate
        return AuthorizationResult(AuthorizationDecision.AUTHORIZED, "authorized", "Compra autorizada."), mandate

    def capture(self, command: CaptureCommand) -> CaptureResult:
        request_hash = hashlib.sha256(json.dumps({"mandate": command.mandate_id, "checkout": command.checkout_id, "merchant": command.merchant_id, "amount": command.total.minor_units, "currency": command.total.currency, "scale": command.total.scale}, sort_keys=True).encode()).hexdigest()
        def prepare(connection):
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
            SqliteAuditRepository(connection).append(AuditEvent(
                id=f"aud_{uuid4().hex}", mandate_id=command.mandate_id,
                event_type="capture.committed" if result.approved else "capture.declined",
                human_summary="Captura liquidada." if result.approved else "Captura recusada.",
                occurred_at=self._clock(),
            ))
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
