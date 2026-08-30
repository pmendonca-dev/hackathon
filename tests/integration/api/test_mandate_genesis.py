"""O mandato nasce assinado pela mesma chave que pode encerrá-lo.

Até aqui a trilha provava que o agente ficou dentro do mandato e não provava que a
pessoa o criou: qualquer chamador escrevia um mandato em nome de qualquer principal, e
uma disputa por *mandate repudiation* terminava em `unproven` com a razão escrita.

A prova de criação fecha isso na posição 0 da cadeia. Ela é verificada contra as
autoridades do próprio mandato antes de qualquer linha ser persistida — a mesma chave
que amanhã revoga é a que hoje autoriza a existência — e carrega um nonce de uso único,
porque uma criação replayável duplicaria a capacidade de gasto da titular sem que
ninguém assinasse duas vezes.
"""

from __future__ import annotations

from tests.integration.api.conftest import Harness


def buy(harness: Harness, mandate_id: str, key: str = "cap_genesis"):
    return harness.capture(harness.purchase(mandate_id) | {"idempotency_key": key})


def test_a_mandate_without_the_holders_signature_is_refused(harness: Harness) -> None:
    payload = harness.mandate_payload()
    payload.pop("creation_jws")

    response = harness.client.post("/mandates", json=payload)

    assert response.status_code == 422, response.text
    assert response.json()["reason_code"] == "mandate_creation_unsigned"


def test_a_creation_signed_by_a_key_the_mandate_does_not_name_is_refused(
    harness: Harness,
) -> None:
    """Naming a principal is not holding their key. Without this, an operator mints
    mandates in someone else's name and the trail records them as that person's."""
    harness.custody.generate_es256("usr_impostor_k1")
    payload = harness.mandate_payload()
    payload["creation_jws"] = harness.creation_token(payload, kid="usr_impostor_k1")

    response = harness.client.post("/mandates", json=payload)

    assert response.status_code == 403, response.text
    assert response.json()["reason_code"] == "mandate_creation_authority_unknown"


def test_a_proof_that_names_a_larger_limit_than_the_mandate_is_refused(
    harness: Harness,
) -> None:
    payload = harness.mandate_payload()
    payload["creation_jws"] = harness.creation_token(payload, limit_minor_units=900000)

    response = harness.client.post("/mandates", json=payload)

    assert response.status_code == 403, response.text
    assert response.json()["reason_code"] == "mandate_creation_terms_mismatch"


def test_a_proof_that_names_other_categories_is_refused(harness: Harness) -> None:
    """The signature has to cover *what* may be bought, not only how much."""
    payload = harness.mandate_payload()
    payload["creation_jws"] = harness.creation_token(payload, allowed_categories=["lodging"])

    response = harness.client.post("/mandates", json=payload)

    assert response.status_code == 403, response.text
    assert response.json()["reason_code"] == "mandate_creation_terms_mismatch"


def test_the_same_proof_cannot_create_a_second_mandate(harness: Harness) -> None:
    """Replay is the attack that costs nothing: the same signature, twice, doubles how
    much of the holder's money is authorized without them signing twice."""
    payload = harness.mandate_payload()
    assert harness.client.post("/mandates", json=payload).status_code == 201

    replayed = harness.client.post("/mandates", json=payload)

    assert replayed.status_code == 409, replayed.text
    assert replayed.json()["reason_code"] == "mandate_creation_replayed"


def test_the_genesis_proof_is_the_first_link_of_the_trail(harness: Harness) -> None:
    payload = harness.mandate_payload()
    mandate_id = harness.client.post("/mandates", json=payload).json()["mandate_id"]

    trail = harness.client.get(
        "/ledger", params={"mandate_id": mandate_id, "view": "auditor"}
    ).json()

    genesis = trail["entries"][0]
    assert genesis["event_type"] == "mandate_registered"
    assert genesis["detail"]["creation_proof"] == payload["creation_jws"]
    assert genesis["detail"]["creation_kid"] == harness.HOLDER_KID
    assert trail["chain"]["intact"] is True


def test_the_genesis_signature_answers_a_repudiation(harness: Harness) -> None:
    """"Eu nunca criei esse mandato" agora é respondido pela posição 0, sem depender de
    a pessoa ter aprovado ou revogado alguma coisa depois."""
    mandate_id = harness.create_mandate()
    reservation_id = buy(harness, mandate_id).json()["reservation_id"]
    opened = harness.client.post(
        "/disputes",
        json={
            "reservation_id": reservation_id,
            "reason": "não reconheço",
            "authorization_jws": harness.read_token(),
        }
    ).json()

    verdict = harness.client.post(
        f"/disputes/{opened['dispute_id']}/resolution", json={"authorization_jws": harness.read_token()}
    ).json()["liability"]

    assert verdict["mandate_repudiation"] == "refuted"
    assert verdict["holder_signatures"][0]["kind"] == "mandate_creation"


def test_the_merchant_never_sees_the_creation_proof(harness: Harness) -> None:
    """The proof names the buyer's key. A seller that could read it would learn which
    mandates belong to the same person across its own sales."""
    mandate_id = harness.create_mandate()
    buy(harness, mandate_id)

    body = harness.client.get(
        "/ledger", params={"merchant_id": "vuelaya", "view": "merchant"}
    ).text

    assert "creation_proof" not in body
    assert harness.HOLDER_KID not in body
