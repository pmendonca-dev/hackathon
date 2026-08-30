"""O veredito move dinheiro.

O enunciado define chargeback como *"o banco estorna o dinheiro"*, e até aqui a disputa
respondia quem tinha razão sem que um centavo se mexesse. Um veredito que não move nada
é uma opinião bem fundamentada.

A regra é a mesma escada de sempre, aplicada agora ao dinheiro:

- a trilha **não** prova autoridade sobre a cobrança → o valor volta, e a capacidade de
  gasto da titular volta com ele;
- a trilha **prova** → nada é estornado, e o recibo diz por quê.

O caso reversível de verdade é o que o `spend_outside_mandate` do rodapé já contava:
dinheiro retido sem prova emitida por esta camada. Ele existe porque um agente pode
cobrar **por fora** — e é isso que a rota de demonstração `rogue-charge` encena, sob
flag, para que o jurado veja o estorno acontecer em vez de ouvir sobre ele.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from aval.api.app import create_app
from aval.runtime import build_runtime
from aval.security.key_custody import KeyCustodyService
from datetime import UTC, datetime

from tests.integration.api.conftest import Harness, MutableClock, _generated


@pytest.fixture
def rogue_harness(monkeypatch: pytest.MonkeyPatch) -> Harness:
    """A harness whose app was built with the demonstration flag already set: the
    router is mounted at composition time, so flipping the variable afterwards would
    change nothing — which is exactly the property the flag is supposed to have."""
    monkeypatch.setenv("AVAL_DEMO_ROGUE", "1")
    clock = MutableClock(datetime(2026, 8, 29, 12, 0, tzinfo=UTC))
    custody = KeyCustodyService()
    custody.generate_es256(Harness.HOLDER_KID)
    runtime = build_runtime(now_provider=clock, operator_token=Harness.OPERATOR_TOKEN)
    harness = Harness(
        client=TestClient(create_app(runtime)), clock=clock, custody=custody, runtime=runtime
    )
    harness.client.post(
        "/agents",
        headers=harness.operator,
        json={
            "id": "agent_travel",
            "profile_url": "https://agents.aval.local/agent_travel",
            "public_jwk": _generated(custody, Harness.AGENT_KID),
            "trusted": True,
        },
    )
    return harness


def rogue_charge(harness: Harness, mandate_id: str, minor_units: int = 9000) -> str:
    response = harness.client.post(
        "/admin/demo/rogue-charge",
        headers=harness.operator,
        json={"mandate_id": mandate_id, "minor_units": minor_units},
    )
    assert response.status_code == 201, response.text
    return response.json()["reservation_id"]


def resolve(harness: Harness, reservation_id: str) -> dict:
    opened = harness.client.post(
        "/disputes", json={"reservation_id": reservation_id, "reason": "não reconheço"}
    )
    assert opened.status_code == 201, opened.text
    resolved = harness.client.post(f"/disputes/{opened.json()['dispute_id']}/resolution")
    assert resolved.status_code == 200, resolved.text
    return resolved.json()


def spent(harness: Harness, mandate_id: str) -> int:
    return harness.read_mandate(mandate_id).json()["spent"]["minor_units"]


def events(harness: Harness, mandate_id: str) -> list[str]:
    trail = harness.client.get(
        "/ledger", params={"mandate_id": mandate_id, "view": "auditor"}
    ).json()
    return [entry["event_type"] for entry in trail["entries"]]


def test_a_charge_this_layer_never_authorized_holds_the_budget(rogue_harness) -> None:
    """The premise of the reversal: an agent that went around AVAL still eats the
    holder's capacity, because the money is held in her name."""
    mandate_id = rogue_harness.create_mandate()

    rogue_charge(rogue_harness, mandate_id)

    assert spent(rogue_harness, mandate_id) == 9000


def test_the_verdict_gives_back_what_it_could_not_justify(rogue_harness) -> None:
    mandate_id = rogue_harness.create_mandate()
    reservation_id = rogue_charge(rogue_harness, mandate_id)

    verdict = resolve(rogue_harness, reservation_id)["liability"]

    assert verdict["verdict"] == "AGENT_OVERREACH"
    assert spent(rogue_harness, mandate_id) == 0
    assert "purchase_reversed" in events(rogue_harness, mandate_id)


def test_the_holder_who_authorized_is_not_reimbursed(harness) -> None:
    """A reversal that fired on a purchase the trail *can* justify would turn every
    receipt into a refund button."""
    mandate_id = harness.create_mandate()
    reservation_id = harness.capture(
        harness.purchase(mandate_id) | {"idempotency_key": "cap_rev_1"}
    ).json()["reservation_id"]

    verdict = resolve(harness, reservation_id)["liability"]

    assert verdict["verdict"] == "HOLDER_LIABLE"
    assert spent(harness, mandate_id) == 13000
    assert "purchase_reversed" not in events(harness, mandate_id)


def test_a_reversal_happens_once_however_often_it_is_asked(rogue_harness) -> None:
    """Resolution is a read of the trail, and reads may be repeated. Money may not."""
    mandate_id = rogue_harness.create_mandate()
    reservation_id = rogue_charge(rogue_harness, mandate_id)
    opened = rogue_harness.client.post(
        "/disputes", json={"reservation_id": reservation_id, "reason": "não reconheço"}
    ).json()

    for _ in range(3):
        rogue_harness.client.post(f"/disputes/{opened['dispute_id']}/resolution")

    assert spent(rogue_harness, mandate_id) == 0
    assert events(rogue_harness, mandate_id).count("purchase_reversed") == 1


def test_the_footer_number_returns_to_zero_after_the_reversal(rogue_harness) -> None:
    """`spend_outside_mandate` and the reversal read the same fact, so the panel and the
    arbitration cannot tell a judge two different stories."""
    mandate_id = rogue_harness.create_mandate()
    reservation_id = rogue_charge(rogue_harness, mandate_id)
    before = rogue_harness.client.get("/metrics").json()["spend_outside_mandate"]["minor_units"]

    resolve(rogue_harness, reservation_id)

    assert before == 9000
    assert rogue_harness.client.get("/metrics").json()["spend_outside_mandate"]["minor_units"] == 0


def test_the_rogue_charge_route_does_not_exist_without_its_flag(harness) -> None:
    """Same discipline as the tamper route: the router is never mounted, so there is no
    permission check to argue with and nothing in the OpenAPI document."""
    response = harness.client.post(
        "/admin/demo/rogue-charge",
        headers=harness.operator,
        json={"mandate_id": harness.create_mandate(), "minor_units": 100},
    )

    assert response.status_code == 404, response.text


def test_the_rogue_charge_route_still_needs_the_operator(rogue_harness) -> None:
    response = rogue_harness.client.post(
        "/admin/demo/rogue-charge",
        json={"mandate_id": rogue_harness.create_mandate(), "minor_units": 100},
    )

    assert response.status_code == 401, response.text


def test_the_holder_can_name_the_purchase_they_do_not_recognise(harness) -> None:
    """A dispute is opened against a reservation, so the person's own record has to
    carry that id. Without it the button exists only where a developer can read the
    database, which is not where the holder is."""
    mandate_id = harness.create_mandate()
    reservation_id = harness.capture(
        harness.purchase(mandate_id) | {"idempotency_key": "cap_rev_2"}
    ).json()["reservation_id"]

    record = harness.human_ledger(mandate_id).json()

    assert any(
        entry["detail"].get("reservation_id") == reservation_id for entry in record["entries"]
    )
