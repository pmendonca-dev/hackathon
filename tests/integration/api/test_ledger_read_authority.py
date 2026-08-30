"""Ver também é autoridade.

A listagem já era escopada pela chave: `GET /mandates` responde pelos mandatos que
aquela assinatura já poderia encerrar, e por mais nenhum. O registro do titular não era.
`mandate_id` é um identificador, não um segredo — ele viaja no recibo do agente, na
barra de endereço e em qualquer print de tela — e com ele qualquer um lia orçamento,
gasto, merchants e histórico de compras da pessoa.

A visão do auditor continua aberta de propósito, e isso está declarado: ela é a peça de
transparência da demonstração, e o que ela mostra é a *cadeia*, que é o que um auditor
existe para conferir. O que ela não pode fazer é virar a porta dos fundos da visão
humana — por isso as duas são testadas lado a lado aqui.
"""

from __future__ import annotations

from tests.integration.api.conftest import Harness


def human_view(harness: Harness, mandate_id: str, **params):
    return harness.client.get(
        "/ledger", params={"mandate_id": mandate_id, "view": "human", **params}
    )


def test_the_holders_record_is_refused_without_a_read_authorization(harness: Harness) -> None:
    mandate_id = harness.create_mandate()

    response = human_view(harness, mandate_id)

    assert response.status_code == 403, response.text
    assert response.json()["reason_code"] == "read_authorization_required"


def test_a_key_that_is_no_authority_on_the_mandate_cannot_read_it(harness: Harness) -> None:
    """The attack the id made possible: someone who saw a mandate_id and holds a key of
    their own. Naming is not holding, for sight exactly as for revocation."""
    mandate_id = harness.create_mandate()
    harness.custody.generate_es256("usr_bruno_k1")

    response = human_view(
        harness, mandate_id, authorization_jws=harness.read_token(kid="usr_bruno_k1")
    )

    assert response.status_code == 403, response.text
    assert response.json()["reason_code"] == "read_forbidden"


def test_the_holder_reads_their_own_record(harness: Harness) -> None:
    mandate_id = harness.create_mandate()

    response = human_view(harness, mandate_id, authorization_jws=harness.read_token())

    assert response.status_code == 200, response.text
    assert response.json()["mandate"]["mandate_id"] == mandate_id


def test_a_single_mandate_is_read_by_the_key_that_holds_it(harness: Harness) -> None:
    mandate_id = harness.create_mandate()

    assert harness.client.get(f"/mandates/{mandate_id}").status_code == 403
    assert harness.read_mandate(mandate_id).status_code == 200


def test_the_auditor_view_stays_open_and_still_carries_the_chain(harness: Harness) -> None:
    """A declared boundary, not an oversight: the auditor is the transparency surface a
    judge opens without credentials, and it is what the tamper demo is checked against.
    It is listed in the README's assumed boundaries for exactly that reason."""
    mandate_id = harness.create_mandate()

    response = harness.client.get(
        "/ledger", params={"mandate_id": mandate_id, "view": "auditor"}
    )

    assert response.status_code == 200, response.text
    assert response.json()["chain"]["intact"] is True


def test_the_merchant_view_is_still_answered_by_its_own_name(harness: Harness) -> None:
    """The seller never had the mandate id and must not need one now: requiring a
    holder's signature here would hand every merchant the buyer it is built to hide."""
    response = harness.client.get(
        "/ledger", params={"merchant_id": "vuelaya", "view": "merchant"}
    )

    assert response.status_code == 200, response.text
