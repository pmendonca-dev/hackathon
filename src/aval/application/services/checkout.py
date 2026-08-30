from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from typing import Protocol

from sqlalchemy import Engine

from aval.adapters.ap2.merchant_authorization import MerchantAuthorizationSigner
from aval.adapters.ap2.mandates import ClosedCheckoutMandateVerifier
from aval.adapters.ap2.merchant_authorization import MerchantAuthorizationVerifier
from aval.adapters.ucp.ap2_extension import Ap2CheckoutLock, UcpCheckoutError
from aval.application.authorization_core import AuthorizationCommand
from aval.domain.checkout_status import to_ucp_status
from aval.domain.enums import AuthorizationDecision, AvalCheckoutStatus
from aval.domain.money import Money
from aval.infrastructure.sqlite.idempotency_repository import SqliteIdempotencyRepository
from aval.infrastructure.sqlite.transaction import run_in_write_transaction


DEFAULT_CHECKOUT_CATEGORY = "travel"


@dataclass(frozen=True)
class CheckoutCommand:
    id: str
    mandate_id: str
    merchant_id: str
    total: Money
    line_items: Sequence[Mapping[str, object]]
    negotiated_capabilities: frozenset[str]
    # What is being bought. The mandate declares which categories it allows, so this
    # travels to the core rather than being assumed there.
    category: str = DEFAULT_CHECKOUT_CATEGORY


@dataclass(frozen=True)
class CheckoutSession:
    payload: Mapping[str, object]
    ap2_lock: Ap2CheckoutLock
    command: CheckoutCommand


@dataclass(frozen=True)
class CheckoutCompletion:
    checkout_id: str
    status: str
    replayed: bool = False


class CheckoutStore(Protocol):
    def save(self, checkout_id: str, session: CheckoutSession) -> None: ...
    def get(self, checkout_id: str) -> CheckoutSession | None: ...


class InMemoryCheckoutStore:
    """Small test double; HTTP composition injects a durable repository."""

    def __init__(self) -> None:
        self._sessions: dict[str, CheckoutSession] = {}

    def save(self, checkout_id: str, session: CheckoutSession) -> None:
        self._sessions[checkout_id] = session

    def get(self, checkout_id: str) -> CheckoutSession | None:
        return self._sessions.get(checkout_id)


class CheckoutService:
    def __init__(
        self,
        *,
        core,
        store: CheckoutStore,
        merchant_authorization: MerchantAuthorizationSigner,
        clock: Callable[[], datetime],
        merchant_authorization_verifier: MerchantAuthorizationVerifier | None = None,
        mandate_verifier: ClosedCheckoutMandateVerifier | None = None,
        engine: Engine | None = None,
    ) -> None:
        self._core = core
        self._store = store
        self._merchant_authorization = merchant_authorization
        self._merchant_authorization_verifier = merchant_authorization_verifier
        self._mandate_verifier = mandate_verifier
        self._clock = clock
        self._engine = engine

    def create(self, command: CheckoutCommand) -> CheckoutSession:
        decision = self._core.evaluate(
            AuthorizationCommand(
                command.mandate_id, command.id, command.merchant_id, command.total, command.category
            )
        )
        status = (
            AvalCheckoutStatus.READY
            if decision.decision is AuthorizationDecision.AUTHORIZED
            else AvalCheckoutStatus.AWAITING_HUMAN
            if decision.decision is AuthorizationDecision.AWAITING_HUMAN
            else AvalCheckoutStatus.REJECTED
        )
        payload: dict[str, object] = {
            "id": command.id,
            "merchant_id": command.merchant_id,
            "line_items": [dict(item) for item in command.line_items],
            "totals": [{"type": "total", "amount": command.total.minor_units, "currency": command.total.currency}],
            "status": to_ucp_status(status),
        }
        if status is AvalCheckoutStatus.AWAITING_HUMAN:
            payload["continue_url"] = f"/human/checkouts/{command.id}"
        lock = Ap2CheckoutLock(command.negotiated_capabilities)
        if lock.locked:
            payload["ap2"] = {"merchant_authorization": self._merchant_authorization.sign(payload)}
        session = CheckoutSession(payload, lock, command)
        self._store.save(command.id, session)
        return session

    def complete(
        self,
        checkout_id: str,
        *,
        checkout_mandate: str | None,
        audience: str,
        nonce: str,
        idempotency_key: str,
    ) -> CheckoutCompletion:
        if self._engine is None:
            return self._verify_completion(
                checkout_id, checkout_mandate=checkout_mandate, audience=audience, nonce=nonce,
            )
        request_hash = hashlib.sha256(json.dumps({
            "checkout_id": checkout_id, "checkout_mandate": checkout_mandate,
            "audience": audience, "nonce": nonce,
        }, sort_keys=True).encode()).hexdigest()

        def operation(connection) -> CheckoutCompletion:
            idem = SqliteIdempotencyRepository(connection)
            try:
                claim = idem.get_or_claim("checkout_complete", idempotency_key, request_hash)
            except Exception as error:
                raise UcpCheckoutError("idempotency_unavailable") from error
            if claim.state == "REPLAY":
                value = json.loads(claim.response_body or "{}")
                return CheckoutCompletion(value["checkout_id"], value["status"], replayed=True)
            if claim.state == "MISMATCH":
                raise UcpCheckoutError("idempotency_key_reused")
            if claim.state == "IN_FLIGHT":
                raise UcpCheckoutError("idempotency_in_flight")
            result = self._verify_completion(
                checkout_id, checkout_mandate=checkout_mandate, audience=audience, nonce=nonce,
            )
            idem.complete("checkout_complete", idempotency_key, json.dumps({
                "checkout_id": result.checkout_id, "status": result.status,
            }))
            return result

        try:
            return run_in_write_transaction(self._engine, operation)
        except UcpCheckoutError:
            raise
        except ValueError as error:
            raise UcpCheckoutError(str(error)) from error
        except Exception as error:
            raise UcpCheckoutError("idempotency_unavailable") from error

    def _verify_completion(
        self, checkout_id: str, *, checkout_mandate: str | None, audience: str, nonce: str,
    ) -> CheckoutCompletion:
        session = self._store.get(checkout_id)
        if session is None:
            raise UcpCheckoutError("checkout_not_found")
        session.ap2_lock.require_completion(checkout_mandate)
        if session.ap2_lock.locked:
            if self._merchant_authorization_verifier is None or self._mandate_verifier is None:
                raise UcpCheckoutError("ap2_verification_unavailable")
            ap2 = session.payload.get("ap2")
            if not isinstance(ap2, Mapping) or not isinstance(ap2.get("merchant_authorization"), str):
                raise UcpCheckoutError("merchant_authorization_missing")
            merchant_authorization = ap2["merchant_authorization"]
            self._merchant_authorization_verifier.verify(session.payload, merchant_authorization)
            self._mandate_verifier.verify(
                checkout_mandate,
                expected_audience=audience,
                expected_nonce=nonce,
                merchant_authorization=merchant_authorization,
            )
        return CheckoutCompletion(checkout_id, "ready_for_capture")
