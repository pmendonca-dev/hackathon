"""Contestar é autoridade do titular, e resolver mexe em dinheiro.

A trilha já escrevia *"compra contestada pelo titular"* e gravava o ator como
`principal:disputant` — sobre uma rota que qualquer um alcançava sabendo o `mandate_id`.
Uma trilha que afirma quem agiu sem verificar quem agiu é pior do que uma que se cala:
ela é a evidência que a arbitragem lê depois.

E resolver deixou de ser uma leitura inofensiva quando o veredito passou a estornar. Uma
resolução disparada por terceiro decide o momento em que o dinheiro volta e fecha a
disputa da pessoa sem ela. Então as três superfícies pedem a mesma prova que todo o resto
do sistema pede para falar em nome do titular: a chave dele.

O token de operador continua não servindo aqui — de propósito. Quem opera a instância não
arbitra o dinheiro dos outros.
"""

from __future__ import annotations

from tests.integration.api.conftest import Harness


def settled_reservation(harness: Harness, mandate_id: str, key: str = "cap_disp") -> str:
    return harness.capture(
        harness.purchase(mandate_id) | {"idempotency_key": key}
    ).json()["reservation_id"]


def open_signed(harness: Harness, reservation_id: str, **overrides):
    body = {
        "reservation_id": reservation_id,
        "reason": "não reconheço esta compra",
        "authorization_jws": harness.read_token(),
    }
    body.update(overrides)
    return harness.client.post("/disputes", json=body)


def test_listing_the_disputes_of_a_mandate_needs_the_holders_key(harness: Harness) -> None:
    mandate_id = harness.create_mandate()

    response = harness.client.get("/disputes", params={"mandate_id": mandate_id})

    assert response.status_code == 403, response.text
    assert response.json()["reason_code"] == "read_authorization_required"


def test_a_stranger_holding_the_id_reads_no_disputes(harness: Harness) -> None:
    """The listing carries reservation ids, the reasons a person wrote and the kid of the
    key that holds the mandate. The id was never a password."""
    mandate_id = harness.create_mandate()
    harness.custody.generate_es256("usr_bruno_k1")

    response = harness.client.get(
        "/disputes",
        params={"mandate_id": mandate_id, "authorization_jws": harness.read_token(kid="usr_bruno_k1")},
    )

    assert response.status_code == 403, response.text
    assert response.json()["reason_code"] == "read_forbidden"


def test_the_holder_lists_their_own_disputes(harness: Harness) -> None:
    mandate_id = harness.create_mandate()
    open_signed(harness, settled_reservation(harness, mandate_id))

    response = harness.client.get(
        "/disputes", params={"mandate_id": mandate_id, "authorization_jws": harness.read_token()}
    )

    assert response.status_code == 200, response.text
    assert len(response.json()["disputes"]) == 1


def test_an_unsigned_dispute_is_refused(harness: Harness) -> None:
    """Otherwise the trail records "contestada pelo titular" about somebody who merely
    knew an id, and the arbitration reads that line as evidence months later."""
    mandate_id = harness.create_mandate()
    reservation_id = settled_reservation(harness, mandate_id)

    response = harness.client.post(
        "/disputes", json={"reservation_id": reservation_id, "reason": "não fui eu"}
    )

    assert response.status_code == 403, response.text
    assert response.json()["reason_code"] == "dispute_unsigned"


def test_a_dispute_signed_by_a_key_that_holds_nothing_is_refused(harness: Harness) -> None:
    mandate_id = harness.create_mandate()
    reservation_id = settled_reservation(harness, mandate_id)
    harness.custody.generate_es256("usr_bruno_k1")

    response = open_signed(
        harness, reservation_id, authorization_jws=harness.read_token(kid="usr_bruno_k1")
    )

    assert response.status_code == 403, response.text
    assert response.json()["reason_code"] == "dispute_forbidden"


def test_the_holder_opens_the_dispute_on_their_own_purchase(harness: Harness) -> None:
    mandate_id = harness.create_mandate()

    response = open_signed(harness, settled_reservation(harness, mandate_id))

    assert response.status_code == 201, response.text
    assert response.json()["dispute_id"].startswith("dsp_")


def test_resolving_without_the_holders_key_is_refused(harness: Harness) -> None:
    """Resolution stopped being a harmless read the moment the verdict began moving
    money: it decides when the value goes back and closes the person's dispute."""
    mandate_id = harness.create_mandate()
    dispute_id = open_signed(harness, settled_reservation(harness, mandate_id)).json()["dispute_id"]

    response = harness.client.post(f"/disputes/{dispute_id}/resolution")

    assert response.status_code == 403, response.text
    assert response.json()["reason_code"] == "dispute_unsigned"


def test_the_operator_credential_does_not_arbitrate(harness: Harness) -> None:
    """The asymmetry, again and on purpose: running the instance is never a way to
    decide what happens to somebody else's money."""
    mandate_id = harness.create_mandate()
    dispute_id = open_signed(harness, settled_reservation(harness, mandate_id)).json()["dispute_id"]

    response = harness.client.post(
        f"/disputes/{dispute_id}/resolution", headers=harness.operator
    )

    assert response.status_code == 403, response.text
    assert response.json()["reason_code"] == "dispute_unsigned"


def test_the_holder_resolves_and_the_trail_answers(harness: Harness) -> None:
    mandate_id = harness.create_mandate()
    dispute_id = open_signed(harness, settled_reservation(harness, mandate_id)).json()["dispute_id"]

    response = harness.client.post(
        f"/disputes/{dispute_id}/resolution", json={"authorization_jws": harness.read_token()}
    )

    assert response.status_code == 200, response.text
    assert response.json()["liability"]["verdict"] == "HOLDER_LIABLE"


def test_the_trail_names_the_key_that_actually_disputed(harness: Harness) -> None:
    """The actor stops being a claim: it is the kid whose signature was verified."""
    mandate_id = harness.create_mandate()
    open_signed(harness, settled_reservation(harness, mandate_id))

    trail = harness.client.get(
        "/ledger", params={"mandate_id": mandate_id, "view": "auditor"}
    ).json()

    opened = [entry for entry in trail["entries"] if entry["event_type"] == "dispute_opened"]
    assert opened and opened[-1]["actor"] == f"principal:{harness.HOLDER_KID}"
