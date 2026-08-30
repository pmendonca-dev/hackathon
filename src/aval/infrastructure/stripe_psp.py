"""The real payment processor, when the demo is asked to move real money.

It stands exactly where `DemoPspAdapter` stands and answers the same three ways —
approved, declined, unreachable — because the core is not allowed to learn which
processor it is talking to. What changes is that a decline here is a card issuer
saying no, and a reference here is a charge that exists at Stripe.

Two properties this file exists to protect:

**A decline and a silence are not the same answer.** An issuer that refuses is a
decision; a network that never replied is *unknown*, and reading it as a refusal
would release a reservation whose money may already have moved. Anything that is
not a definite answer from Stripe raises `PspUnreachable`, which the core holds.

**A retry must not charge twice.** The reservation's transaction hash is the
idempotency key, so the same committed purchase resolves to the same PaymentIntent
however many times the call is repeated.

The credential never appears here, in a log or in an exception: what a mandate holds
is a `pm_...` the person vaulted at Stripe's own page, and what this file sends is
that token's id.
"""

from __future__ import annotations

from collections.abc import Callable
import json
import logging
import urllib.error
import urllib.parse
import urllib.request

from aval.application.authorization_core import SettlementResult
from aval.domain.entities import Mandate, Reservation
from aval.domain.enums import ReservationStatus
from aval.infrastructure.psp import PspUnreachable

logger = logging.getLogger("aval.psp.stripe")

_API_ROOT = "https://api.stripe.com/v1"

# How many minor units Stripe expects per major unit, where it disagrees with the two
# decimals almost everything uses. Charging 1000 JPY as if it were ¥10.00 is the kind
# of mistake that is only ever found by a customer, so a currency that is not listed
# and not two-decimal is refused rather than guessed at.
_ZERO_DECIMAL = frozenset(
    {"BIF", "CLP", "DJF", "GNF", "JPY", "KMF", "KRW", "MGA", "PYG", "RWF",
     "UGX", "VND", "VUV", "XAF", "XOF", "XPF"}
)


class StripeConfigError(RuntimeError):
    """The processor was selected and cannot be built. Never degraded into the mock."""


class StripePspAdapter:
    """Settles a committed reservation against the card its mandate names."""

    def __init__(
        self,
        *,
        secret_key: str,
        mandate_for: Callable[[str], Mandate | None],
        proof_verifier: Callable[[str, Reservation], object] | None = None,
        opener: Callable | None = None,
        timeout: int = 20,
    ) -> None:
        if not secret_key:
            raise StripeConfigError("uma chave secreta da Stripe é obrigatória")
        self._secret_key = secret_key
        self._mandate_for = mandate_for
        self._proof_verifier = proof_verifier
        self._opener = opener or urllib.request.urlopen
        self._timeout = timeout

    # ── settlement ─────────────────────────────────────────────────────────
    def authorize(self, reservation: Reservation, proof: str) -> SettlementResult:
        if (
            reservation.status is not ReservationStatus.COMMITTED
            or not reservation.transaction_hash
        ):
            # Money only moves for a reservation the core already committed.
            return SettlementResult(approved=False)
        if self._proof_verifier is not None:
            try:
                self._proof_verifier(proof, reservation)
            except ValueError:
                return SettlementResult(approved=False)

        mandate = self._mandate_for(reservation.mandate_id)
        if mandate is None or mandate.instrument is None:
            # The core refuses this earlier. Refusing again here means the processor
            # never charges a card no mandate named, whoever calls it.
            return SettlementResult(approved=False)
        amount = self._stripe_amount(reservation)
        if amount is None:
            # A currency this file cannot convert is a configuration mistake, and a
            # mistake about how much to charge must never resolve into a charge.
            logger.error(
                "moeda %s com escala %s não é conversível para a Stripe",
                reservation.amount.currency,
                reservation.amount.scale,
            )
            raise PspUnreachable("a moeda da reserva não é conversível")

        payment_method = mandate.instrument.token
        customer = self._customer_of(payment_method)
        return self._confirm(
            reservation,
            amount=amount,
            payment_method=payment_method,
            customer=customer,
        )

    def _confirm(
        self, reservation: Reservation, *, amount: int, payment_method: str, customer: str
    ) -> SettlementResult:
        status, payload = self._call(
            "/payment_intents",
            {
                "amount": amount,
                "currency": reservation.amount.currency.lower(),
                "customer": customer,
                "payment_method": payment_method,
                # Nobody is at the keyboard: this is an agent settling a purchase a
                # person authorized in advance, which is what the mandate *is*. Saying
                # so is what lets the issuer weigh it as one.
                "off_session": "true",
                "confirm": "true",
                "metadata[reservation_id]": reservation.id,
                "metadata[mandate_id]": reservation.mandate_id,
            },
            # Same committed purchase, same PaymentIntent, however often this is retried.
            idempotency_key=f"aval_{reservation.transaction_hash}",
        )
        if status == 200 and payload.get("status") == "succeeded":
            return SettlementResult(approved=True, reference=str(payload["id"]))
        if status == 200:
            # Anything that is not `succeeded` needs someone at the keyboard —
            # `requires_action` is 3-D Secure, which an off-session purchase cannot do.
            # Not a decline to retry silently, and not money that moved.
            logger.info("PaymentIntent em %s, não liquidado", payload.get("status"))
            return SettlementResult(approved=False)
        error = payload.get("error", {}) if isinstance(payload, dict) else {}
        if status == 402 or error.get("type") == "card_error":
            # The issuer answered, and the answer is no.
            logger.info("cartão recusado: %s", error.get("code", "sem código"))
            return SettlementResult(approved=False)
        # 4xx that is not a card error is our own request being wrong, and 5xx is Stripe
        # having a bad day. Neither is a decline, and neither may release the hold.
        raise PspUnreachable(f"a Stripe respondeu {status}: {error.get('code', 'sem código')}")

    def _customer_of(self, payment_method: str) -> str:
        """Which customer this card is attached to.

        Stripe requires it for an off-session charge, and the mandate deliberately does
        not store it: what the holder authorized is a card, and the customer is Stripe's
        own bookkeeping around it.

        ponytail: one extra round trip per settlement. Caching it on the instrument is
        the upgrade, and it only pays off above demo volume.
        """
        status, payload = self._call(f"/payment_methods/{payment_method}", None)
        customer = payload.get("customer") if status == 200 else None
        if not customer:
            raise PspUnreachable("o cartão do mandato não está vinculado a um cliente")
        return str(customer)

    # ── revocation ─────────────────────────────────────────────────────────
    def detach(self, payment_method: str) -> bool:
        """Let go of the card at Stripe when the holder cancels it here.

        Best effort by design: the local revocation already stops every future
        purchase, so a Stripe that does not answer must not turn cancelling a card
        into an error the person sees.
        """
        try:
            status, _ = self._call(f"/payment_methods/{payment_method}/detach", {})
        except PspUnreachable:
            return False
        return status == 200

    # ── transport ──────────────────────────────────────────────────────────
    def _call(
        self, path: str, form: dict[str, object] | None, *, idempotency_key: str | None = None
    ) -> tuple[int, dict]:
        data = None if form is None else urllib.parse.urlencode(form).encode()
        request = urllib.request.Request(
            f"{_API_ROOT}{path}", data=data, method="GET" if form is None else "POST"
        )
        request.add_header("Authorization", f"Bearer {self._secret_key}")
        request.add_header("Content-Type", "application/x-www-form-urlencoded")
        if idempotency_key is not None:
            request.add_header("Idempotency-Key", idempotency_key)
        try:
            with self._opener(request, timeout=self._timeout) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as error:
            try:
                return error.code, json.loads(error.read())
            except (ValueError, OSError):
                return error.code, {}
        except OSError as error:
            # Never a decline. The reservation stays held and `reconcile` asks again.
            raise PspUnreachable(f"a Stripe não respondeu: {error}") from error

    @staticmethod
    def _stripe_amount(reservation: Reservation) -> int | None:
        """The reservation's money in the unit Stripe charges in, or None if unsure."""
        currency = reservation.amount.currency.upper()
        expected = 0 if currency in _ZERO_DECIMAL else 2
        if reservation.amount.scale != expected:
            return None
        return reservation.amount.minor_units
