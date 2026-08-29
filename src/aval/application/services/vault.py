from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from aval.domain.money import Money


@dataclass(frozen=True)
class Allowance:
    reason: str
    max_amount: int
    currency: str
    checkout_session_id: str
    merchant_id: str
    expires_at: datetime


@dataclass(frozen=True)
class ApprovedPaymentContext:
    live_balance: Money
    mandate_ceiling: Money
    checkout_total: Money
    merchant_id: str
    checkout_id: str
    expires_at: datetime


@dataclass(frozen=True)
class DelegatedPayment:
    token: str
    allowance: Allowance


class DelegationRejected(Exception):
    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


class DelegationAuthorizer(Protocol):
    def authorize_delegation(
        self, *, mandate_id: str, checkout_id: str, merchant_id: str
    ) -> ApprovedPaymentContext: ...


class CredentialTokenizer(Protocol):
    def tokenize(self, card_number: str) -> str: ...


class VaultService:
    """Projects a fresh core-approved payment context as an ACP token."""

    def __init__(
        self,
        *,
        authorizer: DelegationAuthorizer,
        tokenizer: CredentialTokenizer,
    ) -> None:
        self._authorizer = authorizer
        self._tokenizer = tokenizer

    def delegate(
        self,
        *,
        mandate_id: str,
        checkout_id: str,
        merchant_id: str,
        card_number: str,
    ) -> DelegatedPayment:
        approved = self._authorizer.authorize_delegation(
            mandate_id=mandate_id,
            checkout_id=checkout_id,
            merchant_id=merchant_id,
        )
        if (approved.checkout_id, approved.merchant_id) != (checkout_id, merchant_id):
            raise ValueError("authorized payment context does not match the request")

        allowance = derive_allowance(
            live_balance=approved.live_balance,
            mandate_ceiling=approved.mandate_ceiling,
            checkout_total=approved.checkout_total,
            merchant_id=approved.merchant_id,
            checkout_id=approved.checkout_id,
            expires_at=approved.expires_at,
        )
        return DelegatedPayment(
            token=self._tokenizer.tokenize(card_number),
            allowance=allowance,
        )


def derive_allowance(
    *,
    live_balance: Money,
    mandate_ceiling: Money,
    checkout_total: Money,
    merchant_id: str,
    checkout_id: str,
    expires_at: datetime,
) -> Allowance:
    units = {
        (live_balance.currency, live_balance.scale),
        (mandate_ceiling.currency, mandate_ceiling.scale),
        (checkout_total.currency, checkout_total.scale),
    }
    if len(units) != 1:
        raise ValueError("allowance inputs require matching currency and scale")

    return Allowance(
        reason="one_time",
        max_amount=min(
            live_balance.minor_units,
            mandate_ceiling.minor_units,
            checkout_total.minor_units,
        ),
        currency=live_balance.currency.lower(),
        checkout_session_id=checkout_id,
        merchant_id=merchant_id,
        expires_at=expires_at,
    )
