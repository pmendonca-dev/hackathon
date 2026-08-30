from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json

from sqlalchemy import Engine

from aval.application.authorization_core import AuthorizationCommand, AuthorizationCore
from aval.application.services.checkout import CheckoutStore
from aval.application.services.vault import (
    ApprovedPaymentContext,
    DelegatedPayment,
    DelegationRejected,
    VaultService,
)
from aval.domain.enums import AuthorizationDecision
from aval.domain.money import Money
from aval.infrastructure.sqlite.idempotency_repository import SqliteIdempotencyRepository
from aval.infrastructure.sqlite.transaction import run_in_write_transaction
from aval.infrastructure.sqlite.vault_repository import SqliteVaultTokenRepository, VaultTokenRecord


class CoreDelegationAuthorizer:
    """Derives an ACP allowance from current Core facts and canonical checkout only."""

    def __init__(self, *, core: AuthorizationCore, checkouts: CheckoutStore) -> None:
        self._core = core
        self._checkouts = checkouts

    def authorize_delegation(
        self, *, mandate_id: str, checkout_id: str, merchant_id: str
    ) -> ApprovedPaymentContext:
        checkout = self._checkouts.get(checkout_id)
        if checkout is None:
            raise DelegationRejected("checkout_not_found")
        command = checkout.command
        if command.mandate_id != mandate_id:
            raise DelegationRejected("checkout_mandate_mismatch")
        if command.merchant_id != merchant_id:
            raise DelegationRejected("checkout_merchant_mismatch")
        decision, facts = self._core.live_delegation_context(
            AuthorizationCommand(
                mandate_id, checkout_id, merchant_id, command.total, command.category
            )
        )
        if decision.decision is not AuthorizationDecision.AUTHORIZED or facts is None:
            raise DelegationRejected(decision.reason_code)
        return ApprovedPaymentContext(
            live_balance=facts.live_balance,
            mandate_ceiling=facts.mandate_ceiling,
            checkout_total=command.total,
            merchant_id=merchant_id,
            checkout_id=checkout_id,
            expires_at=facts.expires_at,
        )


@dataclass(frozen=True)
class DelegationOutcome:
    payment: DelegatedPayment | None
    reason_code: str | None
    replayed: bool


class DurableDelegationService:
    """Makes delegation retry-safe without retaining any card credentials."""

    def __init__(self, *, vault: VaultService, engine: Engine) -> None:
        self._vault = vault
        self._engine = engine

    def delegate(
        self, *, mandate_id: str, checkout_id: str, merchant_id: str, card_number: str, idempotency_key: str
    ) -> DelegationOutcome:
        request_hash = hashlib.sha256(json.dumps({
            "mandate_id": mandate_id, "checkout_id": checkout_id, "merchant_id": merchant_id,
        }, sort_keys=True).encode()).hexdigest()

        def operation(connection) -> DelegationOutcome:
            idem = SqliteIdempotencyRepository(connection)
            claim = idem.get_or_claim("delegate_payment", idempotency_key, request_hash)
            if claim.state == "REPLAY":
                return self._outcome_from_json(claim.response_body, replayed=True)
            if claim.state == "MISMATCH":
                return DelegationOutcome(None, "idempotency_key_reused", False)
            if claim.state == "IN_FLIGHT":
                return DelegationOutcome(None, "idempotency_in_flight", False)
            try:
                payment = self._vault.delegate(
                    mandate_id=mandate_id, checkout_id=checkout_id, merchant_id=merchant_id,
                    card_number=card_number,
                )
            except DelegationRejected as error:
                outcome = DelegationOutcome(None, error.reason_code, False)
                idem.complete("delegate_payment", idempotency_key, self._outcome_json(outcome))
                return outcome
            allowance = payment.allowance
            SqliteVaultTokenRepository(connection).put(VaultTokenRecord(
                id=payment.token, mandate_id=mandate_id, checkout_id=checkout_id,
                merchant_id=merchant_id,
                max_amount=Money(allowance.max_amount, allowance.currency.upper(), 2),
                expires_at=allowance.expires_at,
            ))
            outcome = DelegationOutcome(payment, None, False)
            idem.complete("delegate_payment", idempotency_key, self._outcome_json(outcome))
            return outcome

        return run_in_write_transaction(self._engine, operation)

    @staticmethod
    def _outcome_json(outcome: DelegationOutcome) -> str:
        if outcome.payment is None:
            return json.dumps({"reason_code": outcome.reason_code})
        allowance = outcome.payment.allowance
        return json.dumps({"token": outcome.payment.token, "allowance": {
            "reason": allowance.reason, "max_amount": allowance.max_amount,
            "currency": allowance.currency, "checkout_session_id": allowance.checkout_session_id,
            "merchant_id": allowance.merchant_id, "expires_at": allowance.expires_at.isoformat(),
        }})

    @staticmethod
    def _outcome_from_json(body: str | None, *, replayed: bool) -> DelegationOutcome:
        value = json.loads(body or "{}")
        if "reason_code" in value:
            return DelegationOutcome(None, value["reason_code"], replayed)
        from aval.application.services.vault import Allowance
        allowance = value["allowance"]
        return DelegationOutcome(DelegatedPayment(value["token"], Allowance(
            allowance["reason"], allowance["max_amount"], allowance["currency"],
            allowance["checkout_session_id"], allowance["merchant_id"],
            datetime.fromisoformat(allowance["expires_at"]),
        )), None, replayed)
