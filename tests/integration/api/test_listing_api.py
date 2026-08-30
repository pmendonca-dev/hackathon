"""Listing surfaces for the human interfaces.

The bot and the browser need to answer "what mandates do I hold?" and "what is waiting
for me?" without knowing an id in advance. There is no global listing, and the tests below
are what keeps it that way.

But scoping by principal was never enough on its own. `usr_tg_{chat_id}` and
`usr_marta` are names anyone can guess, so the scope has to be the *key*: both listings
carry a holder signature and answer only for the mandates that key actually holds. The
system always isolated authority — one judge cannot revoke another's mandate — and this
is what makes it isolate sight as well, which is the same room of judges sharing one bot.
"""

from __future__ import annotations

from tests.integration.api.conftest import Harness


def other_principal(harness: Harness) -> str:
    return harness.create_mandate(
        principal={"id": "usr_bruno", "display_name": "Bruno Alves"}
    )


def test_the_mandates_of_a_principal_are_listed_with_their_live_budget(harness: Harness) -> None:
    first = harness.create_mandate()
    second = harness.create_mandate()

    response = harness.list_mandates()

    assert response.status_code == 200, response.text
    listed = response.json()["mandates"]
    assert {item["mandate_id"] for item in listed} == {first, second}
    assert listed[0]["limit"] == {"minor_units": 20000, "currency": "USD", "scale": 2}
    assert listed[0]["remaining"] == {"minor_units": 20000, "currency": "USD", "scale": 2}
    assert listed[0]["status"] == "ACTIVE"


def test_listing_mandates_without_a_principal_is_refused(harness: Harness) -> None:
    """No global dump. Every buyer in the system is not a public listing."""
    harness.create_mandate()

    response = harness.client.get("/mandates")

    assert response.status_code == 422, response.text


def test_a_mandate_listing_never_carries_another_principal(harness: Harness) -> None:
    mine = harness.create_mandate()
    theirs = other_principal(harness)

    response = harness.list_mandates()

    listed = {item["mandate_id"] for item in response.json()["mandates"]}
    assert mine in listed
    assert theirs not in listed
    assert "usr_bruno" not in response.text


def test_an_unknown_principal_lists_nothing_rather_than_failing(harness: Harness) -> None:
    """A holder with no mandates yet is an empty inbox, not an error."""
    response = harness.list_mandates("usr_nobody")

    assert response.status_code == 200, response.text
    assert response.json()["mandates"] == []


def test_pending_escalations_are_listed_for_a_principal_across_mandates(
    harness: Harness,
) -> None:
    first = harness.create_mandate()
    second = harness.create_mandate()
    for mandate_id in (first, second):
        harness.authorize(harness.purchase(mandate_id, merchant_id="despegar"))

    response = harness.list_escalations()

    assert response.status_code == 200, response.text
    escalations = response.json()["escalations"]
    assert {item["mandate_id"] for item in escalations} == {first, second}
    assert all(item["reason_code"] == "merchant_out_of_scope" for item in escalations)


def test_listing_escalations_without_any_scope_is_refused(harness: Harness) -> None:
    """Pending approvals name what somebody is about to buy. They are not a feed."""
    mandate_id = harness.create_mandate()
    harness.authorize(harness.purchase(mandate_id, merchant_id="despegar"))

    response = harness.client.get("/escalations")

    assert response.status_code == 422, response.text


def test_escalations_of_another_principal_are_not_listed(harness: Harness) -> None:
    mine = harness.create_mandate()
    theirs = other_principal(harness)
    harness.authorize(harness.purchase(mine, merchant_id="despegar"))
    harness.authorize(harness.purchase(theirs, merchant_id="despegar"))

    response = harness.list_escalations()

    listed = {item["mandate_id"] for item in response.json()["escalations"]}
    assert listed == {mine}


def test_listing_escalations_by_mandate_still_answers_the_single_mandate(
    harness: Harness,
) -> None:
    """The existing per-mandate query keeps working; the principal filter is additive."""
    mandate_id = harness.create_mandate()
    harness.authorize(harness.purchase(mandate_id, merchant_id="despegar"))

    response = harness.client.get("/escalations", params={"mandate_id": mandate_id})

    assert response.status_code == 200, response.text
    assert [item["mandate_id"] for item in response.json()["escalations"]] == [mandate_id]


def test_guessing_the_name_does_not_read_another_buyers_mandates(harness: Harness) -> None:
    """The gap this closes: `principal_id` is a name, not a secret.

    The bot derives it as `usr_tg_{chat_id}` and the browser defaults it to `usr_marta`.
    A judge who guesses the chat id next to theirs used to get that person's mandate,
    their limit and everything they had spent.
    """
    theirs = other_principal(harness)

    # A stranger with their own perfectly valid key, aiming it at somebody else's name.
    harness.custody.generate_es256("usr_stranger_k1")
    response = harness.client.get(
        "/mandates",
        params={"principal_id": "usr_bruno"},
        headers={"X-Aval-Authorization": harness.read_token("usr_bruno", kid="usr_stranger_k1")},
    )

    assert response.status_code == 200, response.text
    assert response.json()["mandates"] == []
    assert theirs not in response.text


def test_a_listing_signed_for_one_buyer_does_not_answer_for_another(harness: Harness) -> None:
    """The token names who it is for, so it cannot be lifted onto a second listing."""
    harness.create_mandate()

    lifted = harness.client.get(
        "/mandates",
        params={"principal_id": "usr_marta"},
        headers={"X-Aval-Authorization": harness.read_token("usr_bruno")},
    )

    assert lifted.json()["mandates"] == []


def test_the_mandate_listing_requires_a_signature_at_all(harness: Harness) -> None:
    """Sem assinatura, a mesma recusa que qualquer outra leitura dá.

    Era 422 porque a assinatura vinha como parâmetro obrigatório de query e quem recusava
    era o framework. Agora ela viaja em cabeçalho — fora do log de acesso e do histórico —
    e a recusa é da rota, com o código que as outras leituras já usavam. Ausente e
    malformada continuam sendo respostas diferentes.
    """
    harness.create_mandate()

    response = harness.client.get("/mandates", params={"principal_id": "usr_marta"})

    assert response.status_code == 403, response.text
    assert response.json()["reason_code"] == "read_authorization_required"


def test_pending_approvals_of_another_buyer_cannot_be_polled(harness: Harness) -> None:
    """Escalations name what somebody is about to buy, down to the amount."""
    theirs = other_principal(harness)
    harness.authorize(harness.purchase(theirs, merchant_id="despegar"))
    harness.custody.generate_es256("usr_stranger_k2")

    response = harness.client.get(
        "/escalations",
        params={"principal_id": "usr_bruno"},
        headers={"X-Aval-Authorization": harness.read_token("usr_bruno", kid="usr_stranger_k2")},
    )

    assert response.status_code == 200, response.text
    assert response.json()["escalations"] == []


def test_polling_approvals_by_principal_requires_a_signature(harness: Harness) -> None:
    mandate_id = harness.create_mandate()
    harness.authorize(harness.purchase(mandate_id, merchant_id="despegar"))

    response = harness.client.get("/escalations", params={"principal_id": "usr_marta"})

    assert response.status_code == 422
    assert response.json()["reason_code"] == "read_authorization_required"


def test_a_malformed_read_authorization_is_refused_not_ignored(harness: Harness) -> None:
    """Fail closed: unreadable authorization is never the same as none required."""
    harness.create_mandate()

    response = harness.client.get(
        "/mandates",
        params={"principal_id": "usr_marta"},
        headers={"X-Aval-Authorization": "not-a-jws"},
    )

    assert response.status_code == 422
    assert response.json()["reason_code"] == "read_authorization_malformed"


def test_reading_a_single_mandate_by_its_random_id_still_works(harness: Harness) -> None:
    """The capability that *is* one stays one.

    A `mandate_id` is 32 random hex — knowing it is the entitlement, and the browser and
    the bot both read this way constantly. Only the guessable scope was closed.
    """
    mandate_id = harness.create_mandate()

    assert harness.read_mandate(mandate_id).status_code == 200
    assert harness.client.get("/escalations", params={"mandate_id": mandate_id}).status_code == 200
