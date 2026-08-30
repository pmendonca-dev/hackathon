"""The real processor, answered without touching the network.

What is guarded here is the difference between the three answers a processor can
give. A decline releases the hold; a silence must not, because money may already
have moved. Getting that wrong is how a purchase is charged and forgotten.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from aval.domain.entities import Mandate, PaymentInstrument, Principal, RevocationAuthority
from aval.domain.enums import RevocationRole, ReservationStatus
from aval.domain.entities import Reservation
from aval.domain.money import Money
from aval.infrastructure.psp import PspUnreachable
from aval.infrastructure.stripe_psp import StripeConfigError, StripePspAdapter


class FakeStripe:
    """Stripe's wire, as far as the adapter can tell."""

    def __init__(self) -> None:
        self.intent_status = "succeeded"
        self.http_status = 200
        self.error: dict | None = None
        self.offline = False
        self.customer: str | None = "cus_1"
        self.calls: list[tuple[str, dict, str | None]] = []

    def opener(self, request, timeout=None):  # noqa: ANN001 - urlopen shape
        import urllib.error
        import urllib.parse

        if self.offline:
            raise OSError("connection reset")
        path = request.full_url.split("/v1", 1)[1]
        form = dict(urllib.parse.parse_qsl(request.data.decode())) if request.data else {}
        self.calls.append((path, form, request.get_header("Idempotency-key")))
        if path.startswith("/payment_methods/"):
            return _Response(200, {"id": "pm_1", "customer": self.customer})
        if self.http_status != 200:
            raise urllib.error.HTTPError(
                request.full_url, self.http_status, "error", {},
                _Response(self.http_status, {"error": self.error or {}}),
            )
        return _Response(200, {"id": "pi_1", "status": self.intent_status})


class _Response:
    def __init__(self, status: int, payload: dict) -> None:
        self.status = status
        self._body = json.dumps(payload).encode()

    def read(self) -> bytes:
        return self._body

    def close(self) -> None:
        # HTTPError treats the body as a file and closes it on collection.
        return None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


def mandate(token: str = "pm_card_1") -> Mandate:
    return Mandate(
        id="m1",
        principal=Principal("p1", "Marta"),
        allowed_merchant_ids=frozenset({"vuelaya"}),
        allowed_categories=frozenset({"travel"}),
        limit=Money(20_000, "USD", 2),
        expires_at=datetime.now(UTC) + timedelta(days=1),
        policy_version=1,
        revocation_metadata={"revocation_id": "r1", "epoch": 0},
        authorities=(
            RevocationAuthority("a1", "holder", RevocationRole.HOLDER, {"kty": "EC"}, frozenset({"mandate"})),
        ),
        instrument=PaymentInstrument(token, "•••• 4242"),
    )


def reservation(*, currency: str = "USD", scale: int = 2, committed: bool = True) -> Reservation:
    return Reservation(
        "rsv_1", "m1", "chk_1", Money(13_000, currency, scale),
        ReservationStatus.COMMITTED if committed else ReservationStatus.PENDING,
        "tx_hash_1" if committed else None,
    )


def adapter(stripe: FakeStripe, *, found: Mandate | None = None) -> StripePspAdapter:
    return StripePspAdapter(
        secret_key="sk_test_x",
        mandate_for=lambda _: mandate() if found is None else found,
        opener=stripe.opener,
    )


def test_a_succeeded_intent_settles_and_carries_its_reference() -> None:
    stripe = FakeStripe()

    result = adapter(stripe).authorize(reservation(), "proof")

    assert (result.approved, result.reference) == (True, "pi_1")
    path, form, _ = stripe.calls[-1]
    assert path == "/payment_intents"
    assert (form["amount"], form["currency"]) == ("13000", "usd")
    assert form["payment_method"] == "pm_card_1"
    # Nobody is at the keyboard. Saying so is what lets the issuer weigh it as such.
    assert form["off_session"] == "true"


def test_the_same_committed_purchase_carries_the_same_idempotency_key() -> None:
    """A retried settlement must resolve to one PaymentIntent, not two charges."""
    stripe = FakeStripe()
    psp = adapter(stripe)

    psp.authorize(reservation(), "proof")
    psp.authorize(reservation(), "proof")

    keys = [key for path, _, key in stripe.calls if path == "/payment_intents"]
    assert keys[0] == keys[1] == "aval_tx_hash_1"


def test_a_declined_card_is_a_decision_and_releases_the_hold() -> None:
    stripe = FakeStripe()
    stripe.http_status = 402
    stripe.error = {"type": "card_error", "code": "card_declined"}

    result = adapter(stripe).authorize(reservation(), "proof")

    assert result.approved is False


def test_a_silent_processor_is_unknown_and_never_a_decline() -> None:
    """The hold stays. Reading silence as a refusal releases money that may have moved."""
    stripe = FakeStripe()
    stripe.offline = True

    with pytest.raises(PspUnreachable):
        adapter(stripe).authorize(reservation(), "proof")


def test_a_server_error_is_unknown_too() -> None:
    stripe = FakeStripe()
    stripe.http_status = 500
    stripe.error = {"type": "api_error"}

    with pytest.raises(PspUnreachable):
        adapter(stripe).authorize(reservation(), "proof")


def test_an_intent_that_needs_the_person_is_not_a_settlement() -> None:
    """3-D Secure cannot be answered by an agent, so it is not money that moved."""
    stripe = FakeStripe()
    stripe.intent_status = "requires_action"

    result = adapter(stripe).authorize(reservation(), "proof")

    assert (result.approved, result.reference) == (False, None)


def test_a_mandate_naming_no_card_is_never_charged() -> None:
    """The core refuses this earlier; refusing again means no caller can get past it."""
    stripe = FakeStripe()
    naked = mandate()
    psp = StripePspAdapter(
        secret_key="sk_test_x", mandate_for=lambda _: None, opener=stripe.opener
    )

    assert psp.authorize(reservation(), "proof").approved is False
    assert stripe.calls == []
    assert naked is not None


def test_an_uncommitted_reservation_never_reaches_the_processor() -> None:
    stripe = FakeStripe()

    result = adapter(stripe).authorize(reservation(committed=False), "proof")

    assert result.approved is False
    assert stripe.calls == []


def test_a_currency_this_adapter_cannot_convert_is_refused_not_guessed() -> None:
    """1000 JPY charged as if it were ¥10.00 is only ever found by a customer."""
    stripe = FakeStripe()

    with pytest.raises(PspUnreachable):
        adapter(stripe).authorize(reservation(currency="JPY", scale=2), "proof")
    assert stripe.calls == []


def test_a_proof_that_does_not_bind_the_reservation_stops_the_charge() -> None:
    stripe = FakeStripe()

    def refuse(proof, reservation):
        raise ValueError("proof does not bind this reservation")

    psp = StripePspAdapter(
        secret_key="sk_test_x", mandate_for=lambda _: mandate(),
        proof_verifier=refuse, opener=stripe.opener,
    )

    assert psp.authorize(reservation(), "proof").approved is False
    assert stripe.calls == []


def test_a_card_attached_to_nobody_cannot_be_charged_off_session() -> None:
    stripe = FakeStripe()
    stripe.customer = None

    with pytest.raises(PspUnreachable):
        adapter(stripe).authorize(reservation(), "proof")


def test_the_adapter_refuses_to_exist_without_a_key() -> None:
    with pytest.raises(StripeConfigError):
        StripePspAdapter(secret_key="", mandate_for=lambda _: None)
