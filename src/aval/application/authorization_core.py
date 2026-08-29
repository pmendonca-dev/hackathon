from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
import base64
import json
from uuid import uuid4

from sqlalchemy import Engine, create_engine
from sqlalchemy.pool import StaticPool

from aval.application.ports import AuthorizationProofIssuer, SettlementAdapter
from aval.domain.entities import Mandate, Reservation, Revocation
from aval.domain.enums import AuthorizationDecision, MandateStatus, ReservationStatus
from aval.domain.money import Money
from aval.security.jws import verify_compact_jws
from aval.security.key_custody import public_key_from_jwk
from aval.infrastructure.sqlite.mandate_repository import SqliteMandateRepository
from aval.infrastructure.sqlite.models import metadata
from aval.infrastructure.sqlite.policy_repository import SqlitePolicyRepository
from aval.infrastructure.sqlite.revocation_repository import SqliteRevocationRepository
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
        self._reservations: dict[str, Reservation] = {}
        self._idempotency: dict[str, CaptureResult] = {}

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

    def evaluate(self, command: AuthorizationCommand) -> AuthorizationResult:
        with self._engine.connect() as connection:
            mandate = SqliteMandateRepository(connection).get(command.mandate_id)
            revoked = mandate is not None and SqliteRevocationRepository(connection).is_revoked(command.mandate_id)
            limit, _ = SqlitePolicyRepository(connection).active_limit_for(command.mandate_id, mandate.limit) if mandate else (None, 0)
        if mandate is None:
            return self._reject("mandate_not_found", "Mandato não encontrado.")
        if revoked or mandate.status is MandateStatus.REVOKED:
            return self._reject("mandate_revoked", "Mandato revogado.")
        if mandate.status is MandateStatus.EXPIRED or self._clock() >= mandate.expires_at:
            return self._reject("mandate_expired", "Mandato expirado.")
        if command.merchant_id not in mandate.allowed_merchant_ids:
            return AuthorizationResult(
                AuthorizationDecision.AWAITING_HUMAN,
                "merchant_out_of_scope",
                "Merchant fora do escopo do mandato; aprovação humana necessária.",
            )
        assert limit is not None
        if (command.total.currency, command.total.scale) != (limit.currency, limit.scale):
            return self._reject("money_unit_mismatch", "Moeda ou escala incompatível com o mandato.")
        if command.total.minor_units <= 0:
            return self._reject("invalid_amount", "Valor de captura inválido.")
        if self._spent(mandate.id).add(command.total).minor_units > limit.minor_units:
            return AuthorizationResult(
                AuthorizationDecision.AWAITING_HUMAN,
                "budget_exceeded",
                "Compra excede o orçamento vivo do mandato.",
            )
        return AuthorizationResult(AuthorizationDecision.AUTHORIZED, "authorized", "Compra autorizada.")

    def capture(self, command: CaptureCommand) -> CaptureResult:
        if cached := self._idempotency.get(command.idempotency_key):
            return cached
        decision = self.evaluate(command)
        if decision.decision is not AuthorizationDecision.AUTHORIZED:
            result = CaptureResult(False, decision.reason_code)
            self._idempotency[command.idempotency_key] = result
            return result
        with self._engine.connect() as connection:
            mandate = SqliteMandateRepository(connection).get(command.mandate_id)
        assert mandate is not None
        reservation = Reservation(
            id=f"rsv_{uuid4().hex}",
            mandate_id=command.mandate_id,
            checkout_intent_id=command.checkout_id,
            amount=command.total,
        ).commit(transaction_hash=uuid4().hex)
        self._reservations[reservation.id] = reservation
        if self._settlement_adapter is None:
            result = CaptureResult(True, "committed", reservation)
        else:
            proof = (
                self._authorization_proof_issuer.issue(
                    reservation,
                    policy_version=mandate.policy_version,
                    revocation_epoch=int(mandate.revocation_metadata.get("epoch", 0)),
                ).signed_proof
                if self._authorization_proof_issuer is not None
                else f"proof_{reservation.id}"
            )
            settlement = self._settlement_adapter.authorize(reservation, proof)
            final_reservation = reservation.settle() if settlement.approved else reservation.release()
            self._reservations[reservation.id] = final_reservation
            result = CaptureResult(
                settlement.approved,
                "settled" if settlement.approved else "settlement_declined",
                final_reservation,
                settlement.reference,
            )
        self._idempotency[command.idempotency_key] = result
        return result

    def _spent(self, mandate_id: str) -> Money:
        with self._engine.connect() as connection:
            mandate = SqliteMandateRepository(connection).get(mandate_id)
        assert mandate is not None
        spent = Money(0, mandate.limit.currency, mandate.limit.scale)
        for reservation in self._reservations.values():
            if reservation.mandate_id == mandate_id and reservation.status in {
                ReservationStatus.COMMITTED,
                ReservationStatus.SETTLED,
            }:
                spent = spent.add(reservation.amount)
        return spent

    @staticmethod
    def _reject(reason_code: str, human_summary: str) -> AuthorizationResult:
        return AuthorizationResult(AuthorizationDecision.REJECTED, reason_code, human_summary)
