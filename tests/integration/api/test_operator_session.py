"""O operador também deixa rastro.

O titular assina para gastar, e isso já era provado. Do outro lado do console, quem
opera a instância apresentava um token estático que viajava dentro do bundle do
navegador — quem abrisse o devtools na página da demonstração levava embora o
interruptor do processador, o relógio, o preço e o registro de agente, para sempre.

Duas coisas mudam aqui, e nenhuma delas move dinheiro:

1. O token vira **sessão**: ele é apresentado uma vez, no console, e o que fica na
   página é uma credencial curta que expira sozinha. Nenhum segredo permanente nasce
   dentro de um bundle.
2. Todo ato de operador entra num **diário encadeado**, com a sessão que o praticou.
   Derrubar o processador na frente de um jurado deixa de ser um gesto que só o time
   sabe que aconteceu.

A assimetria continua sendo a tese: uma sessão de operador não aprova escalação nem
levanta limite, porque isso é autoridade do titular e se prova com a chave dele.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from aval.infrastructure.sqlite.models import operator_sessions
from tests.integration.api.conftest import Harness


def open_session(harness: Harness) -> dict:
    response = harness.client.post("/admin/operator/sessions", headers=harness.operator)
    assert response.status_code == 201, response.text
    return response.json()


def session_headers(harness: Harness) -> dict[str, str]:
    return {"X-Aval-Operator-Session": open_session(harness)["session_token"]}


def test_the_operator_token_is_exchanged_for_a_session_that_expires(harness: Harness) -> None:
    issued = open_session(harness)

    assert issued["session_token"]
    assert issued["session_id"].startswith("ops_")
    # The whole point: what the page holds stops working on its own.
    assert issued["expires_at"] > harness.clock.instant.isoformat()


def test_a_session_cannot_be_minted_without_the_raw_token(harness: Harness) -> None:
    response = harness.client.post("/admin/operator/sessions")

    assert response.status_code == 401, response.text
    assert response.json()["reason_code"] == "operator_token_missing"


def test_a_session_opens_the_operator_surfaces(harness: Harness) -> None:
    response = harness.client.post(
        "/admin/psp", headers=session_headers(harness), json={"mode": "offline"}
    )

    assert response.status_code == 200, response.text


def test_an_unknown_session_is_refused(harness: Harness) -> None:
    response = harness.client.post(
        "/admin/psp",
        headers={"X-Aval-Operator-Session": "ops_nothing_like_this"},
        json={"mode": "offline"},
    )

    assert response.status_code == 403, response.text
    assert response.json()["reason_code"] == "operator_session_invalid"


def test_an_expired_session_stops_working(harness: Harness) -> None:
    """A credential that outlived its window is a credential nobody is watching.

    The window is real time, not the demo clock — the row is aged here directly for the
    same reason: sessions must not be reachable by the knob that ages mandates."""
    issued = open_session(harness)
    with harness.runtime.engine.begin() as connection:
        connection.execute(
            operator_sessions.update()
            .where(operator_sessions.c.id == issued["session_id"])
            .values(expires_at=datetime.now(UTC) - timedelta(minutes=1))
        )

    response = harness.client.post(
        "/admin/psp",
        headers={"X-Aval-Operator-Session": issued["session_token"]},
        json={"mode": "offline"},
    )

    assert response.status_code == 403, response.text
    assert response.json()["reason_code"] == "operator_session_expired"


def test_moving_the_demo_clock_does_not_end_the_session(harness: Harness) -> None:
    """Found by running the browser journey, not by the unit tests: the trial by fire
    asks a judge to advance the clock and watch a mandate expire, and that was logging
    them out of the console in the same gesture. The clock ages mandates; it is not a
    way to end somebody's session — least of all somebody else's."""
    headers = session_headers(harness)

    harness.client.post("/admin/clock", headers=harness.operator, json={"advance_seconds": 864000})

    assert harness.client.post("/admin/psp", headers=headers, json={"mode": "offline"}).status_code == 200


def test_a_session_can_be_closed_before_it_expires(harness: Harness) -> None:
    issued = open_session(harness)
    headers = {"X-Aval-Operator-Session": issued["session_token"]}

    assert harness.client.delete("/admin/operator/sessions/current", headers=headers).status_code == 200
    assert (
        harness.client.post("/admin/psp", headers=headers, json={"mode": "offline"}).status_code
        == 403
    )


def test_a_session_carries_no_spending_authority(harness: Harness) -> None:
    """The asymmetry the whole system is built on. Operating the instance is not owning
    the mandate: moving the budget still needs the holder's key, and a session — like
    the raw token before it — buys nothing here."""
    mandate_id = harness.create_mandate()

    response = harness.client.patch(
        f"/mandates/{mandate_id}/limit",
        headers=session_headers(harness),
        json={"limit": {"minor_units": 900000, "currency": "USD", "scale": 2}},
    )

    assert response.status_code == 403, response.text
    assert response.json()["reason_code"] == "limit_change_unsigned"


def test_every_operator_action_lands_in_the_journal(harness: Harness) -> None:
    harness.client.post("/admin/psp", headers=harness.operator, json={"mode": "offline"})

    journal = harness.client.get("/admin/operator/journal", headers=harness.operator).json()

    assert journal["entries"], "the processor switch left no trace"
    last = journal["entries"][-1]
    assert last["action"] == "POST /admin/psp"
    assert last["actor"] == "operator:token"


def test_the_journal_names_the_session_that_acted(harness: Harness) -> None:
    issued = open_session(harness)
    harness.client.post(
        "/admin/psp",
        headers={"X-Aval-Operator-Session": issued["session_token"]},
        json={"mode": "offline"},
    )

    journal = harness.client.get("/admin/operator/journal", headers=harness.operator).json()

    assert journal["entries"][-1]["actor"] == f"operator:session:{issued['session_id']}"


def test_the_journal_is_a_chain_that_verifies_itself(harness: Harness) -> None:
    """Same machinery as the mandate trail, for the same reason: a log the operator
    promises not to edit is worth less than one an auditor can check."""
    for mode in ("offline", "online", "decline"):
        harness.client.post("/admin/psp", headers=harness.operator, json={"mode": mode})

    journal = harness.client.get("/admin/operator/journal", headers=harness.operator).json()

    assert journal["chain"]["intact"] is True
    assert journal["chain"]["checked"] >= 3
    assert journal["chain"]["broken_at"] is None


def test_reading_the_journal_is_not_itself_an_action(harness: Harness) -> None:
    """A journal that logged its own reads would grow forever and bury the three lines
    that matter. Reads are not authority; writes are."""
    harness.client.post("/admin/psp", headers=harness.operator, json={"mode": "offline"})
    before = harness.client.get("/admin/operator/journal", headers=harness.operator).json()

    after = harness.client.get("/admin/operator/journal", headers=harness.operator).json()

    assert len(after["entries"]) == len(before["entries"])


def test_the_journal_is_not_public(harness: Harness) -> None:
    assert harness.client.get("/admin/operator/journal").status_code == 401
