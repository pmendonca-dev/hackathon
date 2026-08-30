"""The panic button: end everything this key is allowed to end, in one signature.

A person who believes their agent has been taken over should not have to revoke six
mandates one at a time while it keeps spending. One holder-signed token, scoped to a
principal, revokes every mandate that key is actually an authority on.

The last two words are the security boundary. The token is not a claim about a person,
it is a signature checked against each mandate's own registered authority — so it
reaches exactly the mandates that key could already have revoked one by one, and not
one more. Holding a key for one of somebody's mandates never becomes authority over
the rest of them.
"""

from __future__ import annotations

from tests.integration.api.conftest import Harness
from aval.security.jws import sign_compact_jws


def kill_token(harness: Harness, principal_id: str, *, kid: str | None = None) -> str:
    return sign_compact_jws(
        {
            "principal_id": principal_id,
            "scope": "mandate",
            "reason": "agente comprometido",
            "epoch": 1,
        },
        harness.custody,
        kid or harness.HOLDER_KID,
    )


def test_one_signature_revokes_every_mandate_that_key_holds(harness: Harness) -> None:
    first = harness.create_mandate()
    second = harness.create_mandate()

    response = harness.client.post(
        "/principals/usr_marta/revocations",
        json={"token": kill_token(harness, "usr_marta")},
    )

    assert response.status_code == 200, response.text
    assert set(response.json()["revoked_mandate_ids"]) == {first, second}
    for mandate_id in (first, second):
        decision = harness.authorize(harness.purchase(mandate_id)).json()
        assert decision["reason_code"] == "mandate_revoked"


def test_it_never_reaches_a_mandate_that_key_is_not_an_authority_on(
    harness: Harness,
) -> None:
    """Same person, a mandate registered under a different key. The kill switch is a
    signature, not an identity claim, so that mandate is untouched."""
    mine = harness.create_mandate()
    harness.custody.generate_es256("usr_marta_k2")
    other_key = harness.create_mandate(
        authorities=[
            {
                "kid": "usr_marta_k2",
                "role": "holder",
                "public_jwk": harness.custody.public_jwk("usr_marta_k2"),
                "allowed_scopes": ["mandate"],
            }
        ]
    )

    harness.client.post(
        "/principals/usr_marta/revocations",
        json={"token": kill_token(harness, "usr_marta")},
    )

    assert harness.authorize(harness.purchase(mine)).json()["reason_code"] == "mandate_revoked"
    assert harness.authorize(harness.purchase(other_key)).json()["decision"] == "authorized"


def test_claiming_another_principal_does_not_reach_their_mandates(
    harness: Harness,
) -> None:
    """The attack that matters: a token that *names* someone else's principal, signed
    with a key that is no authority on their mandates. Naming is not holding."""
    harness.custody.generate_es256("usr_bruno_k1")
    theirs = harness.create_mandate(
        principal={"id": "usr_bruno", "display_name": "Bruno Alves"},
        authorities=[
            {
                "kid": "usr_bruno_k1",
                "role": "holder",
                "public_jwk": harness.custody.public_jwk("usr_bruno_k1"),
                "allowed_scopes": ["mandate"],
            }
        ],
    )

    response = harness.client.post(
        "/principals/usr_bruno/revocations",
        json={"token": kill_token(harness, "usr_bruno")},
    )

    assert response.status_code == 403, response.text
    assert harness.authorize(harness.purchase(theirs)).json()["decision"] == "authorized"


def test_a_forged_signature_revokes_nothing(harness: Harness) -> None:
    mandate_id = harness.create_mandate()
    harness.custody.generate_es256("attacker_k1")

    response = harness.client.post(
        "/principals/usr_marta/revocations",
        json={"token": kill_token(harness, "usr_marta", kid="attacker_k1")},
    )

    assert response.status_code == 403, response.text
    assert harness.authorize(harness.purchase(mandate_id)).json()["decision"] == "authorized"


def test_the_url_principal_must_match_the_signed_one(harness: Harness) -> None:
    """Without this, a token could be walked from the principal it names onto another."""
    harness.create_mandate()

    response = harness.client.post(
        "/principals/usr_someone_else/revocations",
        json={"token": kill_token(harness, "usr_marta")},
    )

    assert response.status_code == 400, response.text
    assert response.json()["reason_code"] == "revocation_principal_mismatch"


def test_each_revocation_lands_on_its_own_mandate_trail(harness: Harness) -> None:
    first = harness.create_mandate()
    second = harness.create_mandate()

    harness.client.post(
        "/principals/usr_marta/revocations",
        json={"token": kill_token(harness, "usr_marta")},
    )

    for mandate_id in (first, second):
        entries = harness.client.get(
            "/ledger", params={"mandate_id": mandate_id, "view": "auditor"}
        ).json()
        assert any("revocation" in entry["event_type"] for entry in entries["entries"])
        assert entries["chain"]["intact"] is True
