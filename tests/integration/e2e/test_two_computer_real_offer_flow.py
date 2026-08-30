"""Both computers, in one process, talking only the way they would over a network.

Everything the split promises is either true here or it is not true at all: A searches
the web and never touches the database, B spends and never learns the OpenAI key, the
only thing crossing between them is a signed request, and what comes back to the chat
carries a link a person can check and no credential of any kind.

The two external services are faked — no OpenAI call, no Stripe call — but the boundary
between A and B is not. Real HMAC headers, real signature verification, real refusals.
Faking that would be faking the only thing this test exists to prove.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import replace
from datetime import UTC, datetime
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient

from aval.agent.scheduler import tick_once
from aval.api.app import create_app
from aval.discovery.core_client import CoreDiscoveryClient
from aval.discovery.models import ShoppingRequest, encode_shopping_request
from aval.discovery.openai_web import OpenAIWebDiscovery
from aval.interfaces.discovery.app import create_discovery_app
from aval.merchant.catalog import TEST_MARKETPLACE_ID
from aval.runtime import build_runtime
from aval.security.edge_auth import EdgeSigner
from aval.security.jws import sign_compact_jws
from aval.security.key_custody import KeyCustodyService
from tests.integration.api.conftest import Harness, MutableClock

# Two credentials, one per direction, exactly as a real deployment would carry them.
EDGE_TO_CORE = "a-signs-b-verifies"
CORE_TO_EDGE = "b-signs-a-verifies"

WEB_PAGE = {
    "title": "Notebook Acer Aspire 5",
    "merchant": "Loja Confiável",  # deliberately contradicts the URL, as real answers do
    "url": "https://shop.example/aspire-5?utm_source=openai",
    "price": 120.00,
    "currency": "USD",
    "evidence": "Preço anunciado na página do produto.",
}


class _Response:
    """The shape `urlopen` returns, as far as the code under test can tell."""

    def __init__(self, body: bytes, status: int = 200) -> None:
        self._body = body
        self.status = status

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_: object) -> None:
        return None


def _opener_for(client: TestClient):
    """Turn a urllib request into a call on the other computer's app.

    This is the network hop, and it is the only thing that is not real: the request is
    built, signed and verified exactly as it would be over a socket.
    """

    def opener(request, timeout=None):  # noqa: ANN001 - urlopen shape
        parts = urlsplit(request.full_url)
        path = parts.path + (f"?{parts.query}" if parts.query else "")
        response = client.request(
            request.get_method(),
            path,
            content=request.data,
            headers=dict(request.header_items()),
        )
        if response.status_code >= 400:
            raise urllib.error.HTTPError(
                request.full_url,
                response.status_code,
                "error",
                {},
                _Response(response.content, response.status_code),
            )
        return _Response(response.content)

    return opener


class FakeStripe:
    """Stripe's wire. Counts what was actually charged."""

    def __init__(self) -> None:
        self.payment_intents: list[dict] = []

    def opener(self, request, timeout=None):  # noqa: ANN001 - urlopen shape
        import urllib.parse

        path = request.full_url.split("/v1", 1)[1]
        form = dict(urllib.parse.parse_qsl(request.data.decode())) if request.data else {}
        if path.startswith("/payment_methods/"):
            return _Response(json.dumps({"id": "pm_1", "customer": "cus_1"}).encode())
        if path == "/payment_intents":
            self.payment_intents.append(form)
            return _Response(json.dumps({"id": "pi_1", "status": "succeeded"}).encode())
        return _Response(b"{}")


class TwoMachines:
    """Computer A and Computer B, and nothing shared between them but signed HTTP."""

    def __init__(self, *, edge: TestClient, core: TestClient, runtime, harness: Harness, stripe: FakeStripe) -> None:
        self.edge = edge
        self.core = core
        self.runtime = runtime
        self.harness = harness
        self.stripe = stripe

    # ── what a person does in the chat ─────────────────────────────────────
    def create_confirmed_watch(self, query: str, *, max_minor_units: int) -> str:
        payload = self.harness.mandate_payload(
            allowed_merchant_ids=[TEST_MARKETPLACE_ID],
            allowed_categories=["shopping"],
            limit={"minor_units": max_minor_units, "currency": "USD", "scale": 2},
            ceiling={"minor_units": max_minor_units, "currency": "USD", "scale": 2},
        )
        created = self.core.post("/mandates", json=payload)
        assert created.status_code == 201, created.text
        mandate_id = created.json()["mandate_id"]
        instruction = encode_shopping_request(
            ShoppingRequest(
                query=query,
                category="shopping",
                max_minor_units=max_minor_units,
                currency="USD",
            )
        )
        armed = self.core.post(
            "/agent/watches", json={"mandate_id": mandate_id, "instruction": instruction}
        )
        assert armed.status_code == 201, armed.text
        return mandate_id

    # ── what B's scheduler does with nobody at the keyboard ────────────────
    def tick_core(self) -> int:
        return tick_once(self.runtime)

    # ── what A's bot does to find out ──────────────────────────────────────
    def poll_telegram_edge(self) -> dict:
        path = "/edge/v1/events"
        headers = EdgeSigner(EDGE_TO_CORE, clock=lambda: datetime.now(UTC)).sign(
            "GET", path, b""
        )
        response = self.core.get(path, headers=headers)
        assert response.status_code == 200, response.text
        events = response.json()["events"]
        assert events, "o núcleo fechou uma vigília e não contou a ninguém"
        return events[0]

    def revoke(self, mandate_id: str) -> None:
        token = sign_compact_jws(
            {"mandate_id": mandate_id, "scope": "mandate", "reason": "holder_request", "epoch": 1},
            self.harness.custody,
            Harness.HOLDER_KID,
        )
        assert self.core.post(
            f"/mandates/{mandate_id}/revocation", json={"token": token}
        ).status_code == 200


@pytest.fixture
def two_machines(monkeypatch: pytest.MonkeyPatch) -> TwoMachines:
    # Both halves are told the deployment is split, and each gets only its own secrets.
    monkeypatch.setenv("AVAL_EDGE_TO_CORE_SECRET", EDGE_TO_CORE)
    monkeypatch.setenv("AVAL_CORE_TO_EDGE_SECRET", CORE_TO_EDGE)
    monkeypatch.setenv("AVAL_PSP", "stripe")
    monkeypatch.setenv("AVAL_STRIPE_SECRET_KEY", "sk_test_two_machines")

    # ── Computer A: the web, and nothing else ──────────────────────────────
    edge_app = create_discovery_app(
        secret=CORE_TO_EDGE,
        discovery=OpenAIWebDiscovery(responder=lambda _: {"offers": [WEB_PAGE]}),
    )
    edge = TestClient(edge_app)

    # Only Stripe reaches the real `urlopen`; A and B are handed explicit openers.
    stripe = FakeStripe()
    monkeypatch.setattr(urllib.request, "urlopen", stripe.opener)

    # ── Computer B: the money, and no way to search ────────────────────────
    clock = MutableClock(datetime(2026, 8, 30, 12, 0, tzinfo=UTC))
    custody = KeyCustodyService()
    custody.generate_es256(Harness.HOLDER_KID)
    runtime = build_runtime(
        now_provider=clock,
        operator_token=Harness.OPERATOR_TOKEN,
        discovery=CoreDiscoveryClient(
            base_url="http://computer-a:9100",
            secret=CORE_TO_EDGE,
            # Wall clock: the edge signature is transport freshness between machines,
            # and A has no demo offset to match.
            clock=lambda: datetime.now(UTC),
            opener=_opener_for(edge),
        ),
    )
    core = TestClient(create_app(runtime))
    harness = Harness(client=core, clock=clock, custody=custody, runtime=runtime)
    return TwoMachines(edge=edge, core=core, runtime=runtime, harness=harness, stripe=stripe)


# ── the whole journey ───────────────────────────────────────────────────────
def test_real_offer_watch_crosses_boundary_without_secret_leak(two_machines: TwoMachines) -> None:
    two_machines.create_confirmed_watch("notebook", max_minor_units=200_00)

    assert two_machines.tick_core() == 1

    event = two_machines.poll_telegram_edge()
    payload = event["payload"]
    assert payload["source_url"].startswith("https://")
    assert payload["outcome"] == "settled"
    # The page was charged for real, in test mode, exactly once.
    assert len(two_machines.stripe.payment_intents) == 1

    raw = json.dumps(event)
    assert "pm_" not in raw, "um token de pagamento não atravessa para a borda"
    assert "sk_test" not in raw
    assert "eyJ" not in raw, "nenhum JWS compacto atravessa"


def test_the_link_survives_the_crossing_and_the_tracking_does_not(
    two_machines: TwoMachines,
) -> None:
    """The link is what lets a person check the claim instead of believing it."""
    two_machines.create_confirmed_watch("notebook", max_minor_units=200_00)
    two_machines.tick_core()

    payload = two_machines.poll_telegram_edge()["payload"]

    assert payload["source_url"] == "https://shop.example/aspire-5"
    assert "utm_source" not in payload["source_url"]
    # The model claimed "Loja Confiável"; the URL says otherwise, and the URL wins.
    assert payload["source_merchant"] == "shop.example"


def test_a_revoked_mandate_stops_the_charge_on_the_far_side_of_the_boundary(
    two_machines: TwoMachines,
) -> None:
    """A still finds the page. B still refuses to pay for it."""
    mandate_id = two_machines.create_confirmed_watch("notebook", max_minor_units=200_00)
    two_machines.revoke(mandate_id)

    two_machines.tick_core()

    assert two_machines.stripe.payment_intents == []
    assert two_machines.poll_telegram_edge()["payload"]["outcome"] == "mandate_revoked"


def test_a_page_over_the_ceiling_is_refused_even_though_the_search_found_it(
    two_machines: TwoMachines,
) -> None:
    two_machines.create_confirmed_watch("notebook", max_minor_units=100_00)

    two_machines.tick_core()

    assert two_machines.stripe.payment_intents == []


# ── the boundary itself ─────────────────────────────────────────────────────
def test_computer_a_refuses_the_credential_of_the_other_direction(
    two_machines: TwoMachines,
) -> None:
    """Two secrets exist precisely so that one leak is not both doors."""
    body = json.dumps({"query": "x", "category": "shopping", "max_minor_units": 1, "currency": "USD"}).encode()
    headers = EdgeSigner(EDGE_TO_CORE, clock=lambda: datetime.now(UTC)).sign(
        "POST", "/edge/v1/discover", body
    )
    assert two_machines.edge.post(
        "/edge/v1/discover", content=body, headers=headers
    ).status_code == 401


def test_computer_b_refuses_an_unsigned_reader_of_its_outbox(
    two_machines: TwoMachines,
) -> None:
    two_machines.create_confirmed_watch("notebook", max_minor_units=200_00)
    two_machines.tick_core()

    assert two_machines.core.get("/edge/v1/events").status_code == 401


def test_neither_computer_serves_the_other_half_of_the_system(
    two_machines: TwoMachines,
) -> None:
    """A is not a second copy of the API, and B does not search."""
    assert two_machines.edge.post("/authorize", json={}).status_code == 404
    assert two_machines.edge.get("/mandates").status_code == 404
    assert two_machines.core.post("/edge/v1/discover", json={}).status_code == 404
