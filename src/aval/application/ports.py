"""Stable application boundaries; infrastructure implements persistence, never adapters."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Protocol

from aval.domain.entities import (
    AuthorizationProof,
    CaptureAttempt,
    Mandate,
    Reservation,
    Revocation,
)
from aval.domain.money import Money


class Clock(Protocol):
    def now(self) -> datetime: ...


class AuthorizationProofIssuer(Protocol):
    def issue(
        self,
        reservation: Reservation,
        *,
        policy_version: int,
        revocation_epoch: int,
        merchant_id: str,
        terms_hash: str | None = None,
    ) -> AuthorizationProof: ...


class SettlementAdapter(Protocol):
    def authorize(self, reservation: Reservation, proof: str): ...


class MandateRepository(Protocol):
    def put(self, mandate: Mandate) -> None: ...
    def get(self, mandate_id: str) -> Mandate | None: ...


class PolicyRepository(Protocol):
    def active_limit_for(self, mandate_id: str, fallback: Money) -> tuple[Money, int]: ...


class RevocationRepository(Protocol):
    def is_revoked(self, mandate_id: str) -> bool: ...
    def append(self, revocation: Revocation) -> None: ...


class LedgerRepository(Protocol):
    def spent_for(self, mandate_id: str, unit: Money) -> Money: ...
    def save_reservation(self, reservation: Reservation) -> None: ...
    def get_reservation(self, reservation_id: str) -> Reservation | None: ...


class IdempotencyStore(Protocol):
    def get_or_claim(self, surface: str, key: str, request_hash: str): ...
    def complete(self, surface: str, key: str, response_body: str) -> None: ...


class CaptureRepository(Protocol):
    def save_attempt(self, attempt: CaptureAttempt) -> None: ...


class AuditLedger(Protocol):
    """Append-only, hash-chained. `append` returns the entry it wrote so the caller can
    quote its digest without reading the trail back."""

    def append(
        self,
        *,
        mandate_id: str,
        event_type: str,
        human_summary: str,
        actor: str,
        detail: Mapping[str, object],
        occurred_at: datetime,
    ) -> object: ...
    def timeline_for(self, mandate_id: str) -> Sequence[object]: ...
    def entries_for_merchant(self, merchant_id: str) -> Sequence[object]: ...
