"""Registering a payment method after the mandate already exists.

A mandate is created before the person has a card: they are sent to the processor's
own page and come back with a token, never with a number. These tests are about who
is allowed to close that gap, because attaching a card decides whose money an agent
will spend.
"""

from __future__ import annotations

from typing import Any

from aval.security.jws import sign_compact_jws

from conftest import Harness


def binding(
    harness: Harness,
    mandate_id: str,
    *,
    token: str = "pm_live_1",
    label: str = "•••• 4242",
    supersedes: str | None = None,
    kid: str | None = None,
    signed: bool = True,
    claims: dict[str, Any] | None = None,
):
    payload = {
        "mandate_id": mandate_id,
        "scope": "instrument",
        "instrument_token": token,
        "instrument_label": label,
        "supersedes": supersedes,
    }
    payload.update(claims or {})
    body: dict[str, Any] = {"token": token, "label": label}
    if signed:
        body["authorization_jws"] = sign_compact_jws(
            payload, harness.custody, kid or harness.HOLDER_KID
        )
    return harness.client.post(f"/mandates/{mandate_id}/instrument", json=body)


def test_the_holder_registers_a_card_and_the_mandate_can_pay(harness: Harness) -> None:
    mandate_id = harness.create_mandate(payment_method=None)
    assert harness.runtime.core.mandate(mandate_id).instrument is None

    response = binding(harness, mandate_id)

    assert response.status_code == 200, response.text
    assert response.json()["instrument_revocation_scope"] == "instrument:pm_live_1"
    instrument = harness.runtime.core.mandate(mandate_id).instrument
    assert (instrument.token, instrument.label) == ("pm_live_1", "•••• 4242")


def test_an_unsigned_binding_is_refused(harness: Harness) -> None:
    """A mandate id is a guessable name, not an entitlement."""
    mandate_id = harness.create_mandate(payment_method=None)

    response = binding(harness, mandate_id, signed=False)

    assert response.status_code == 403
    assert response.json()["reason_code"] == "instrument_binding_unsigned"
    assert harness.runtime.core.mandate(mandate_id).instrument is None


def test_a_stranger_key_cannot_point_an_agent_at_its_card(harness: Harness) -> None:
    harness.custody.generate_es256("stranger-key")
    mandate_id = harness.create_mandate(payment_method=None)

    response = binding(harness, mandate_id, kid="stranger-key")

    assert response.status_code == 403
    assert response.json()["reason_code"] == "instrument_binding_authority_unknown"
    assert harness.runtime.core.mandate(mandate_id).instrument is None


def test_a_signature_over_another_card_does_not_bind_this_one(harness: Harness) -> None:
    """The body is what the caller sends; the signature is what the holder agreed to."""
    mandate_id = harness.create_mandate(payment_method=None)

    response = binding(harness, mandate_id, claims={"instrument_token": "pm_outro"})

    assert response.json()["reason_code"] == "instrument_binding_token_mismatch"
    assert harness.runtime.core.mandate(mandate_id).instrument is None


def test_a_binding_signed_for_one_mandate_does_not_walk_onto_another(harness: Harness) -> None:
    first = harness.create_mandate(payment_method=None)
    second = harness.create_mandate(payment_method=None, principal={
        "id": "usr_marta", "display_name": "Marta Silva"
    })

    response = binding(harness, second, claims={"mandate_id": first})

    assert response.json()["reason_code"] == "instrument_binding_mandate_mismatch"


def test_replaying_a_binding_after_the_card_changed_is_refused(harness: Harness) -> None:
    """Compare-and-swap: a captured binding dies the moment any other one lands."""
    mandate_id = harness.create_mandate(payment_method=None)
    assert binding(harness, mandate_id, token="pm_first").status_code == 200
    assert binding(
        harness, mandate_id, token="pm_second", supersedes="pm_first"
    ).status_code == 200

    replayed = binding(harness, mandate_id, token="pm_first")

    assert replayed.json()["reason_code"] == "instrument_binding_stale"
    assert harness.runtime.core.mandate(mandate_id).instrument.token == "pm_second"


def test_the_holder_can_cancel_the_card_they_registered(harness: Harness) -> None:
    """Binding grants the scope that cancels it — otherwise the card is unrevocable."""
    mandate_id = harness.create_mandate(payment_method=None)
    binding(harness, mandate_id, token="pm_live_1")

    token = sign_compact_jws(
        {
            "mandate_id": mandate_id,
            "scope": "instrument:pm_live_1",
            "reason": "cartão perdido",
            "epoch": 1,
        },
        harness.custody,
        harness.HOLDER_KID,
    )
    revoked = harness.client.post(
        f"/mandates/{mandate_id}/revocation", json={"token": token}
    )

    assert revoked.status_code == 200, revoked.text
    assert harness.runtime.core.snapshot(mandate_id).instrument_revoked is True


def test_a_revoked_mandate_does_not_accept_a_card(harness: Harness) -> None:
    """A card on a dead mandate is a screen that lies about being funded."""
    mandate_id = harness.create_mandate(payment_method=None)
    token = sign_compact_jws(
        {"mandate_id": mandate_id, "scope": "mandate", "reason": "fim", "epoch": 1},
        harness.custody,
        harness.HOLDER_KID,
    )
    harness.client.post(f"/mandates/{mandate_id}/revocation", json={"token": token})

    response = binding(harness, mandate_id)

    assert response.status_code == 409
    assert response.json()["reason_code"] == "mandate_revoked"


def test_the_trail_records_the_label_and_never_the_credential(harness: Harness) -> None:
    """The ledger is read by people who may not present what it names."""
    mandate_id = harness.create_mandate(payment_method=None)
    binding(harness, mandate_id, token="pm_secret_credential")

    ledger = harness.client.get("/ledger", params={"mandate_id": mandate_id, "view": "auditor"})

    assert "mandate_instrument_bound" in ledger.text
    assert "pm_secret_credential" not in ledger.text
