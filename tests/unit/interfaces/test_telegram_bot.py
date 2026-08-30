from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
import base64
import json
import threading
import time
import urllib.error

import pytest

from aval.agent.intent import fold, parse_intent
from aval.interfaces.telegram import conversation, views
from aval.discovery.models import decode_shopping_request
from aval.interfaces.telegram.bot import Bot, TelegramApi, TelegramError, _display_name
from aval.merchant.catalog import TEST_MARKETPLACE_ID
from aval.interfaces.telegram.config import BotConfig, ConfigError
from aval.interfaces.telegram.gateway import AvalGateway, GatewayError, MoneyView
from aval.interfaces.telegram.identity import IdentityStore
from aval.security.jws import verify_compact_jws
from aval.security.key_custody import public_key_from_jwk

MARTA = 6348622306
JUDGE = 999888777


# ── a stand-in for the AVAL API that checks signatures for real ─────────────
class FakeAval:
    """Answers the shapes the live API answers, and verifies what it is sent.

    It exists so the bot's signing is tested rather than assumed: an approval
    that does not verify against the chat's own published key fails here.
    """

    def __init__(self) -> None:
        self.mandates: dict[str, dict[str, Any]] = {}
        self.escalations: dict[str, dict[str, Any]] = {}
        self.received: list[tuple[str, dict[str, Any]]] = []
        self.verified_claims: list[dict[str, Any]] = []
        self.disputes: list[dict[str, Any]] = []
        # What the trail answers when a purchase is denied, and whether the chain
        # still hashes. Both are knobs because both are what a judge comes to break.
        self.card_sessions: list[str] = []
        self.bindings: list[dict[str, Any]] = []
        self.card_ready = False
        self.card_token = "pm_test_1"
        self.dispute_status = "MANDATE_HELD"
        self.chain_intact = True
        self.watches: dict[str, dict[str, Any]] = {}
        # The core's durable outbox, and what the edge has confirmed arrived. The bot
        # no longer drives watches; it reads this and acknowledges only after Telegram
        # has taken the message.
        self.events: list[dict[str, Any]] = []
        self.acknowledged_event_ids: list[int] = []
        self.edge_open = True
        # What Córdoba costs right now. The judge's price knob moves this.
        self.cordoba_price = 13000
        self.offline = False
        self.hold: "threading.Event | None" = None
        self._sequence = 0

    # transport ------------------------------------------------------------
    def opener(self, request, timeout=None):  # noqa: ANN001 - urlopen shape
        if self.offline:
            raise OSError("connection refused")
        if self.hold is not None and "/agent/purchase" in request.full_url:
            # A slow merchant call, held open on purpose: what a judge's tap runs into
            # while somebody else's purchase is still in flight.
            self.hold.wait(timeout=10)
        path = request.full_url.split("127.0.0.1:9000", 1)[1]
        body = json.loads(request.data) if request.data else {}
        # A assinatura de leitura chega em cabeçalho, como no servidor de verdade. Um
        # duplo que ainda a lesse da query deixaria o bot cego contra a API real com
        # todos os testes daqui verdes.
        read_token = request.get_header("X-aval-authorization")
        status, payload = self._route(request.get_method(), path, body, read_token)
        if status >= 400:
            raise urllib.error.HTTPError(
                request.full_url, status, "error", {}, _Payload(json.dumps(payload).encode())
            )
        return _Payload(json.dumps(payload).encode())

    def _route(self, method: str, path: str, body: dict[str, Any], read_token: str | None = None):
        route, _, query = path.partition("?")
        params = dict(pair.split("=", 1) for pair in query.split("&") if "=" in pair)
        self.received.append((f"{method} {route}", body))
        if route == "/health":
            return 200, {"status": "ok"}
        if route == "/agent/profile":
            return 200, {
                "agent_id": "agt_marta",
                "kid": "agent-demo",
                "trusted": True,
                "profile_url": "https://aval.demo/agents/agt_marta",
            }
        if route == "/merchant/offers":
            return 200, {
                "offers": [
                    _offer("São Paulo → Córdoba, direto", 13000, "travel", sku="FL-COR"),
                    _offer("São Paulo → Córdoba, executiva", 90000, "travel", sku="FL-EXEC"),
                    _offer("Hotel Córdoba Centro", 22000, "lodging", sku="HT-COR"),
                ]
            }
        if route == "/mandates" and method == "POST":
            return 201, self._create_mandate(body)
        if route.endswith("/instrument/session") and method == "POST":
            mandate_id = route.split("/")[2]
            self.card_sessions.append(mandate_id)
            return 200, {"session_id": "cs_test_1", "url": "https://checkout.stripe.test/cs_test_1"}
        if "/instrument/session/" in route and method == "GET":
            if not self.card_ready:
                return 200, {"ready": False}
            return 200, {"ready": True, "token": self.card_token, "label": "•••• 4242"}
        if route.endswith("/instrument") and method == "POST":
            mandate_id = route.split("/")[2]
            mandate = self.mandates[mandate_id]
            # The real endpoint refuses an unsigned binding, so the fake verifies too:
            # a bot that stopped signing would otherwise pass every test here.
            claims = self._verify(mandate_id, body["authorization_jws"])
            if claims.get("supersedes") != (
                (mandate.get("_instrument_scope") or "").removeprefix("instrument:") or None
            ):
                return 403, {"reason_code": "instrument_binding_stale"}
            self.bindings.append(body)
            mandate["instrument_label"] = body["label"]
            mandate["_instrument_scope"] = f"instrument:{body['token']}"
            return 200, {
                "instrument_label": body["label"],
                "instrument_revocation_scope": f"instrument:{body['token']}",
            }
        if route.startswith("/mandates/") and route.endswith("/revocation"):
            return self._revoke(route.split("/")[2], body)
        if route.startswith("/mandates/") and route.endswith("/limit"):
            return self._replace_limit(route.split("/")[2], body)
        if route.startswith("/mandates/"):
            mandate_id = route.split("/")[2]
            mandate = self.mandates.get(mandate_id)
            if mandate is None:
                return 404, {"reason_code": "mandate_not_found"}
            return self._read(mandate_id, read_token, mandate)
        if route == "/escalations":
            if params.get("mandate_id") not in self.mandates:
                return 404, {"reason_code": "mandate_not_found"}
            return 200, {
                "escalations": [
                    item
                    for item in self.escalations.values()
                    if item["mandate_id"] == params.get("mandate_id") and item["status"] == "OPEN"
                ]
            }
        if route.startswith("/escalations/") and route.endswith("/decision"):
            return self._decide(route.split("/")[2], body)
        if route.startswith("/escalations/"):
            item = self.escalations.get(route.split("/")[2])
            return (200, item) if item else (404, {"reason_code": "escalation_not_found"})
        if route == "/ledger":
            mandate_id = params["mandate_id"]
            mandate = self.mandates[mandate_id]
            refusal = self._read(mandate_id, read_token, mandate)
            if refusal[0] != 200:
                return refusal
            return 200, {
                "view": "human",
                "mandate": mandate,
                "entries": [
                    {
                        "sequence": 1,
                        "event_type": "mandate_registered",
                        "human_summary": "Mandato criado.",
                        "occurred_at": datetime.now(UTC).isoformat(),
                    }
                ],
            }
        if route == "/disputes" and method == "POST":
            # The live API refuses an unsigned dispute, because the trail records it as
            # the holder contesting a purchase and names the key that did it. A bot that
            # stopped signing would keep passing here and start failing there.
            token = body.get("authorization_jws")
            if not token:
                return 403, {"reason_code": "dispute_unsigned"}
            owner = next(
                (
                    mandate_id
                    for mandate_id, mandate in self.mandates.items()
                    if mandate["principal"]["id"] == self._claimed_principal(token)
                ),
                None,
            )
            if owner is None:
                return 403, {"reason_code": "dispute_forbidden"}
            self._verify(owner, token)
            self.disputes.append(body)
            return 201, {"dispute_id": "dsp_1", "status": "OPEN", "reason": body["reason"]}
        if route.startswith("/disputes/") and route.endswith("/resolution"):
            held = self.dispute_status == "MANDATE_HELD"
            return 200, {
                "dispute_id": route.split("/")[2],
                "status": self.dispute_status,
                "resolution": (
                    "Prova jti_1 vincula merchant vuelaya, valor 13000 e terms_hash th_1."
                    if held
                    else "Nenhuma prova de autorização vincula esta compra."
                ),
            }
        if route == "/ledger/verify":
            if params.get("mandate_id") not in self.mandates:
                return 404, {"reason_code": "mandate_not_found"}
            return 200, {
                "intact": self.chain_intact,
                "checked": 3,
                "broken_at": None if self.chain_intact else 2,
            }
        if route == "/agent/purchase":
            return self._purchase(body)
        if route == "/agent/watches" and method == "POST":
            return 201, self._register_watch(body)
        if route == "/agent/watches" and method == "GET":
            return 200, {
                "watches": [
                    watch
                    for watch in self.watches.values()
                    if watch["mandate_id"] == params.get("mandate_id")
                ]
            }
        if route == "/agent/watches/tick":
            return 200, {"fired": self._tick_watches(body["mandate_id"])}
        if route == "/edge/v1/events" and method == "GET":
            if not self.edge_open:
                return 401, {"reason_code": "edge_unauthenticated"}
            after = int(params.get("after", 0) or 0)
            return 200, {
                "events": [
                    event
                    for event in self.events
                    if event["id"] > after and event["id"] not in self.acknowledged_event_ids
                ]
            }
        if route.startswith("/edge/v1/events/") and route.endswith("/ack"):
            if not self.edge_open:
                return 401, {"reason_code": "edge_unauthenticated"}
            self.acknowledged_event_ids.append(int(route.split("/")[4]))
            return 204, {}
        return 404, {"reason_code": "not_found"}

    def enqueue_watch_closed(self, *, principal_id: str, **payload: Any) -> int:
        """What Computer B writes when a watch stops waiting."""
        self._sequence += 1
        event_id = self._sequence
        self.events.append(
            {
                "id": event_id,
                "principal_id": principal_id,
                "event_type": "watch_closed",
                "payload": {"principal_id": principal_id, **payload},
            }
        )
        return event_id

    # behaviour ------------------------------------------------------------
    def _create_mandate(self, body: dict[str, Any]) -> dict[str, Any]:
        self._sequence += 1
        mandate_id = f"mandate_{self._sequence:04d}"
        limit = body["limit"]
        self.mandates[mandate_id] = {
            "mandate_id": mandate_id,
            "status": "ACTIVE",
            "principal": body["principal"],
            "allowed_merchant_ids": body["allowed_merchant_ids"],
            "allowed_categories": body["allowed_categories"],
            "limit": limit,
            "ceiling": body.get("ceiling"),
            "spent": {**limit, "minor_units": 0},
            "remaining": limit,
            "expires_at": body["expires_at"],
            "policy_version": 1,
            "revocation_epoch": 0,
            "usage_limit": body.get("usage_limit"),
            "uses_in_window": 0,
            "_jwk": body["authorities"][0]["public_jwk"],
        }
        # A mandate is born unfunded. The fake used to tokenize a number sent at
        # creation; there is no such request any more — the card arrives through the
        # processor's own session, which `/cartao` drives, so nothing here has a
        # number to tokenize.
        scope = None
        self.mandates[mandate_id]["_instrument_scope"] = scope
        return {
            "mandate_id": mandate_id,
            "policy_version": 1,
            "revocation_id": "rev_1",
            "instrument_revocation_scope": scope,
        }

    def _read(self, mandate_id: str, token: str | None, mandate: dict[str, Any]):
        """Sight is authority here too: the live API refuses a read that no key signed,
        so a bot that stopped signing its reads would go blind against the real server
        while every fixture kept passing."""
        if not token:
            return 403, {"reason_code": "read_authorization_required"}
        claims = self._verify(mandate_id, token)
        if claims.get("principal_id") != mandate["principal"]["id"]:
            return 403, {"reason_code": "read_forbidden"}
        return 200, mandate

    @staticmethod
    def _claimed_principal(token: str) -> str | None:
        """Read the claim without trusting it — only to find the mandate whose published
        key the signature is then checked against."""
        encoded = token.split(".")[1]
        payload = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
        return payload.get("principal_id")

    def _verify(self, mandate_id: str, token: str) -> dict[str, Any]:
        """Exactly what the core does: the holder's published key, or nothing."""
        claims = verify_compact_jws(token, public_key_from_jwk(self.mandates[mandate_id]["_jwk"]))
        self.verified_claims.append(claims)
        return claims

    def _revoke(self, mandate_id: str, body: dict[str, Any]):
        claims = self._verify(mandate_id, body["token"])
        if claims.get("mandate_id") != mandate_id:
            return 400, {"reason_code": "revocation_mandate_mismatch"}
        mandate = self.mandates[mandate_id]
        # Only a mandate-scoped revocation ends the mandate. An instrument scope
        # withdraws the money and leaves the authority standing.
        if claims.get("scope") == "mandate":
            mandate["status"] = "REVOKED"
        elif claims.get("scope") == mandate.get("_instrument_scope"):
            mandate["instrument_label"] = None
            mandate["_card_cancelled"] = True
        else:
            return 400, {"reason_code": "revocation_scope_not_allowed"}
        mandate["revocation_epoch"] = claims["epoch"]
        return 200, {"revoked": True, "epoch": claims["epoch"]}

    def _replace_limit(self, mandate_id: str, body: dict[str, Any]):
        if not body.get("authorization_jws"):
            return 403, {"reason_code": "limit_change_unsigned"}
        claims = self._verify(mandate_id, body["authorization_jws"])
        if claims["limit_minor_units"] != body["limit"]["minor_units"]:
            return 403, {"reason_code": "limit_change_amount_mismatch"}
        mandate = self.mandates[mandate_id]
        mandate["limit"] = body["limit"]
        mandate["remaining"] = body["limit"]
        mandate["policy_version"] += 1
        return 200, {"policy_version": mandate["policy_version"], "epoch": 1}

    def _decide(self, escalation_id: str, body: dict[str, Any]):
        escalation = self.escalations[escalation_id]
        claims = self._verify(escalation["mandate_id"], body["approval_jws"])
        if claims.get("decision_handle") != escalation_id:
            return 403, {"reason_code": "approval_handle_mismatch"}
        if claims.get("amount_minor_units") != escalation["amount"]["minor_units"]:
            return 403, {"reason_code": "approval_amount_mismatch"}
        if claims.get("decision") != body["decision"]:
            return 403, {"reason_code": "approval_decision_mismatch"}
        escalation["status"] = "APPROVED" if body["decision"] == "approve" else "DENIED"
        approved = body["decision"] == "approve"
        return 200, {
            "resumed": approved,
            "escalation": escalation,
            "capture": {"approved": approved, "reason_code": "settled" if approved else "denied"},
        }

    def _register_watch(self, body: dict[str, Any]) -> dict[str, Any]:
        self._sequence += 1
        watch_id = f"wch_{self._sequence:04d}"
        self.watches[watch_id] = {
            "watch_id": watch_id,
            "mandate_id": body["mandate_id"],
            "instruction": body["instruction"],
            "status": "OPEN",
            "outcome": None,
            "settlement_reference": None,
            "created_at": datetime.now(UTC).isoformat(),
            "expires_at": (datetime.now(UTC) + timedelta(days=30)).isoformat(),
            "closed_at": None,
        }
        return self.watches[watch_id]

    def _tick_watches(self, mandate_id: str) -> list[dict[str, Any]]:
        """The real service runs each open watch through the ordinary purchase path,
        and so does this: a watch has no privilege a typed request would not have."""
        fired = []
        for watch in self.watches.values():
            if watch["mandate_id"] != mandate_id or watch["status"] != "OPEN":
                continue
            _, purchase = self._purchase(
                {"mandate_id": mandate_id, "instruction": watch["instruction"]}
            )
            if purchase["outcome"] == "no_offer":
                continue
            watch["status"] = "FIRED"
            watch["outcome"] = purchase["reason_code"]
            watch["settlement_reference"] = purchase.get("settlement_reference")
            fired.append({**watch, "purchase": purchase})
        return fired

    def _purchase(self, body: dict[str, Any]):
        mandate_id = body["mandate_id"]
        if self.mandates[mandate_id].get("_card_cancelled"):
            return 200, {
                "outcome": "rejected",
                "reason_code": "instrument_revoked",
                "human_summary": "Instrumento revogado para este mandato.",
            }
        if self.mandates[mandate_id]["status"] == "REVOKED":
            return 200, {
                "outcome": "rejected",
                "reason_code": "mandate_revoked",
                "human_summary": "Mandato revogado.",
                "offer": _offer("Voo Córdoba", 13000, "travel"),
                "escalation_id": None,
            }
        if not any(
            word in fold(body["instruction"])
            for word in ("cordoba", "santiago", "executiva", "hotel", "buenos")
        ):
            # The real agent asks when nothing in the sentence names an offer. The
            # fake keeps that shape so the screen under test is the real one.
            return 200, {
                "outcome": "needs_clarification",
                "reason_code": "instruction_ambiguous",
                "human_summary": "Para onde? Sem um destino eu estaria escolhendo por voce.",
            }
        if "executiva" in body["instruction"]:
            return 200, {
                "outcome": "rejected",
                "reason_code": "mandate_ceiling",
                "human_summary": "Valor acima do teto do mandato.",
                "offer": _offer("Executiva", 90000, "travel"),
                "escalation_id": None,
            }
        if "santiago" in body["instruction"].lower():
            self._sequence += 1
            escalation_id = f"dh_{self._sequence:04d}"
            self.escalations[escalation_id] = {
                "id": escalation_id,
                "mandate_id": mandate_id,
                "checkout_id": "chk_1",
                "merchant_id": "vuelaya",
                "category": "travel",
                "amount": {"minor_units": 30000, "currency": "USD", "scale": 2},
                "reason_code": "budget_exceeded",
                "status": "OPEN",
                "created_at": datetime.now(UTC).isoformat(),
                "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
            }
            return 200, {
                "outcome": "awaiting_human",
                "reason_code": "budget_exceeded",
                "human_summary": "Compra excede o orçamento vivo do mandato.",
                "offer": _offer("Voo Santiago", 30000, "travel"),
                "escalation_id": escalation_id,
            }
        # The price the world is currently asking. A judge drops it; the standing
        # order is what notices.
        intent = parse_intent(body["instruction"])
        if intent.max_minor_units is not None and intent.max_minor_units < self.cordoba_price:
            return 200, {
                "outcome": "no_offer",
                "reason_code": "no_offer_matched",
                "human_summary": "Nenhuma oferta do catálogo atende ao pedido.",
            }
        return 200, {
            "outcome": "settled",
            "reason_code": "settled",
            "human_summary": "Compra concluída.",
            "offer": _offer("Voo Córdoba", self.cordoba_price, "travel"),
            "escalation_id": None,
            "reservation_id": "rsv_1",
            "settlement_reference": "psp_abc123",
        }


class _Payload:
    def __init__(self, raw: bytes) -> None:
        self._raw = raw

    def read(self) -> bytes:
        return self._raw

    def close(self) -> None:
        """HTTPError closes whatever it is handed; without this it complains."""

    def __enter__(self) -> "_Payload":
        return self

    def __exit__(self, *_: object) -> None:
        return None


def _offer(title: str, minor: int, category: str, sku: str = "SKU") -> dict[str, Any]:
    return {
        "offer_id": "off_1",
        "merchant_id": "vuelaya",
        "item": {"sku": sku, "title": title, "category": category},
        "total": {"minor_units": minor, "currency": "USD", "scale": 2},
    }


class FakeApi:
    def __init__(self) -> None:
        self.sent: list[tuple[int, views.View]] = []
        self.edited: list[tuple[int, int, views.View]] = []
        self.answers: list[tuple[str, str]] = []
        # Telegram refusing a message is the ordinary case the outbox exists for: a
        # rate limit, a network blip, a chat that blocked the bot.
        self.fail_next = False

    def send_message(self, chat_id: int, view: views.View) -> dict:
        if self.fail_next:
            raise TelegramError("telegram recusou")
        self.sent.append((chat_id, view))
        return {"message_id": len(self.sent)}

    def edit_message(self, chat_id: int, message_id: int, view: views.View) -> None:
        self.edited.append((chat_id, message_id, view))

    def answer_callback(self, callback_id: str, text: str = "") -> None:
        self.answers.append((callback_id, text))

    @property
    def last_text(self) -> str:
        latest = self.edited[-1][2] if self.edited else self.sent[-1][1]
        return latest.text


def _build(tmp_path: Path, aval: "FakeAval"):
    """One bot process. Called twice by the restart test, which is the whole point:
    everything a restart may not forget has to live in the identity file."""
    config = BotConfig.from_env(
        {
            "TELEGRAM_BOT_TOKEN": "t",
            "TELEGRAM_OPEN_MODE": "1",
            "AVAL_API_BASE_URL": "http://127.0.0.1:9000",
            "TELEGRAM_IDENTITY_PATH": str(tmp_path / "identities.json"),
        }
    )
    identities = IdentityStore(config.identity_path)
    gateway = AvalGateway(
        "http://127.0.0.1:9000",
        identities=identities,
        opener=aval.opener,
        edge_secret="edge-to-core",
    )
    api = FakeApi()
    return Bot(config, gateway, identities, api), api, aval, identities


@pytest.fixture
def world(tmp_path: Path):
    return _build(tmp_path, FakeAval())


@pytest.fixture
def restart(tmp_path: Path):
    """Boot a second bot over the same identity file and the same server."""
    return lambda aval: _build(tmp_path, aval)


def message(text: str, chat_id: int = MARTA, first_name: str = "Marta") -> dict:
    return {
        "update_id": 1,
        "message": {"chat": {"id": chat_id}, "text": text, "from": {"first_name": first_name}},
    }


def tap(data: str, chat_id: int = MARTA) -> dict:
    return {
        "update_id": 2,
        "callback_query": {
            "id": "cb1",
            "data": data,
            "from": {"first_name": "Marta"},
            "message": {"message_id": 9, "chat": {"id": chat_id}},
        },
    }


# ── configuration ───────────────────────────────────────────────────────────
def test_a_bot_without_a_token_refuses_to_start() -> None:
    with pytest.raises(ConfigError):
        BotConfig.from_env({})


def test_a_non_numeric_chat_id_is_a_configuration_error() -> None:
    with pytest.raises(ConfigError):
        BotConfig.from_env({"TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_ALLOWED_CHAT_IDS": "1,marta"})


def test_without_open_mode_an_unlisted_chat_may_not_act() -> None:
    config = BotConfig.from_env({"TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_ALLOWED_CHAT_IDS": "42"})
    assert config.may_act(42) is True
    assert config.may_act(JUDGE) is False


# ── money and untrusted input ───────────────────────────────────────────────
@pytest.mark.parametrize(
    ("money", "expected"),
    [
        (MoneyView(20000, "USD", 2), "US$ 200,00"),
        (MoneyView(5, "BRL", 2), "R$ 0,05"),
        (MoneyView(-1234567, "USD", 2), "-US$ 12.345,67"),
        (MoneyView(1500, "JPY", 0), "JPY 1.500"),
    ],
)
def test_money_prints_from_minor_units_without_a_float(money: MoneyView, expected: str) -> None:
    assert views.format_money(money) == expected


@pytest.mark.parametrize(
    ("typed", "minor"),
    [("100", 10000), ("100,50", 10050), ("1.200,25", 120025), ("US$ 80", 8000)],
)
def test_a_typed_amount_becomes_exact_minor_units(typed: str, minor: int) -> None:
    parsed = views.parse_money(typed, currency="USD", scale=2)
    assert parsed is not None and parsed.minor_units == minor


@pytest.mark.parametrize("typed", ["", "abc", "-5", "0", "1e3"])
def test_a_bad_amount_is_refused_rather_than_guessed(typed: str) -> None:
    assert views.parse_money(typed, currency="USD", scale=2) is None


@pytest.mark.parametrize("data", ["", "boom", "apr:", "apr:../etc", "apr:" + "x" * 70, "drop:1"])
def test_callback_data_is_treated_as_untrusted(data: str) -> None:
    assert views.parse_callback(data) is None


# ── identity and custody ────────────────────────────────────────────────────
def test_a_chat_keeps_its_key_across_a_restart(tmp_path: Path) -> None:
    path = tmp_path / "identities.json"
    first = IdentityStore(path)
    identity = first.enrol(MARTA, "Marta")
    first.bind_mandate(MARTA, "mandate_1")
    published = first.public_jwk(identity)

    reopened = IdentityStore(path)
    restored = reopened.get(MARTA)
    assert restored is not None and restored.mandate_id == "mandate_1"
    token = reopened.sign(restored, {"hello": "world"})
    # The signature still verifies against the key the mandate was created with,
    # so a restarted bot can still revoke what it issued.
    assert verify_compact_jws(token, public_key_from_jwk(published)) == {"hello": "world"}


def test_a_corrupt_identity_file_does_not_stop_the_bot(tmp_path: Path) -> None:
    path = tmp_path / "identities.json"
    path.write_text("{not json", encoding="utf-8")
    assert IdentityStore(path).known_chats() == ()


# ── the mandate is the person's own ─────────────────────────────────────────
def test_start_issues_a_mandate_bound_to_the_chat_key(world) -> None:
    bot, api, aval, identities = world
    bot.handle_update(message("/start"))

    identity = identities.get(MARTA)
    assert identity is not None and identity.mandate_id is not None
    mandate = aval.mandates[identity.mandate_id]
    assert mandate["_jwk"] == identities.public_jwk(identity)
    assert mandate["principal"]["display_name"] == "Marta"
    assert "US$ 200,00" in api.sent[0][1].text


def test_start_twice_does_not_issue_a_second_mandate(world) -> None:
    bot, _, aval, _ = world
    bot.handle_update(message("/start"))
    bot.handle_update(message("/start"))
    assert len(aval.mandates) == 1


def test_two_people_get_two_mandates_and_two_keys(world) -> None:
    bot, _, aval, identities = world
    bot.handle_update(message("/start", chat_id=MARTA, first_name="Marta"))
    bot.handle_update(message("/start", chat_id=JUDGE, first_name="Jurado"))

    marta, judge = identities.get(MARTA), identities.get(JUDGE)
    assert marta.mandate_id != judge.mandate_id
    assert identities.public_jwk(marta) != identities.public_jwk(judge)
    assert len(aval.mandates) == 2


def test_one_person_cannot_touch_another_persons_mandate(world) -> None:
    bot, api, aval, identities = world
    bot.handle_update(message("/start", chat_id=MARTA))
    bot.handle_update(message("/start", chat_id=JUDGE))
    marta_mandate = identities.get(MARTA).mandate_id

    bot.handle_update(tap(f"rvm:{marta_mandate}", chat_id=JUDGE))

    assert "não é seu" in api.last_text
    assert aval.mandates[marta_mandate]["status"] == "ACTIVE"


# ── the purchase, in free text ──────────────────────────────────────────────
def test_a_purchase_inside_the_mandate_settles_and_returns_a_receipt(world) -> None:
    bot, api, _, _ = world
    bot.handle_update(message("/start"))
    api.sent.clear()

    bot.handle_update(message("/comprar um voo pra Cordoba"))

    assert "Comprado" in api.sent[0][1].text
    assert "psp_abc123" in api.sent[0][1].text
    # A4: the record of what was bought arrives without being asked for.
    assert "Extrato" in api.sent[1][1].text


def test_a_purchase_above_the_ceiling_is_refused_with_no_approve_button(world) -> None:
    bot, api, _, _ = world
    bot.handle_update(message("/start"))
    api.sent.clear()

    bot.handle_update(message("/comprar a executiva"))

    view = api.sent[0][1]
    assert "Recusado" in view.text and "mandate_ceiling" in view.text
    assert view.buttons == (), "a ceiling is not negotiable, so it gets no approve button"


def test_a_purchase_over_budget_escalates_with_a_decision_card(world) -> None:
    bot, api, _, _ = world
    bot.handle_update(message("/start"))
    api.sent.clear()

    bot.handle_update(message("/comprar o voo pra Santiago"))

    assert "Precisa de você" in api.sent[0][1].text
    labels = [label for row in api.sent[1][1].buttons for label, _ in row]
    assert labels == ["✅ Aprovar", "❌ Recusar"]


# ── the signed tap ──────────────────────────────────────────────────────────
def test_approving_sends_a_signature_the_core_can_verify(world) -> None:
    bot, api, aval, identities = world
    bot.handle_update(message("/start"))
    bot.handle_update(message("/comprar o voo pra Santiago"))
    escalation_id = next(iter(aval.escalations))

    bot.handle_update(tap(f"apr:{escalation_id}"))

    assert aval.escalations[escalation_id]["status"] == "APPROVED"
    claims = aval.verified_claims[-1]
    assert claims["decision_handle"] == escalation_id
    assert claims["decision"] == "approve"
    assert claims["amount_minor_units"] == 30000
    assert "assinado pela sua chave" in api.last_text


def test_denying_closes_the_escalation_without_charging(world) -> None:
    bot, api, aval, _ = world
    bot.handle_update(message("/start"))
    bot.handle_update(message("/comprar o voo pra Santiago"))
    escalation_id = next(iter(aval.escalations))

    bot.handle_update(tap(f"den:{escalation_id}"))

    assert aval.escalations[escalation_id]["status"] == "DENIED"
    assert "Nada foi cobrado" in api.last_text


def test_revoking_is_signed_and_stops_the_next_purchase(world) -> None:
    bot, api, aval, identities = world
    bot.handle_update(message("/start"))
    mandate_id = identities.get(MARTA).mandate_id

    bot.handle_update(tap(f"rvm:{mandate_id}"))
    assert aval.mandates[mandate_id]["status"] == "REVOKED"
    assert aval.verified_claims[-1]["scope"] == "mandate"

    api.sent.clear()
    bot.handle_update(message("/comprar um voo pra Cordoba"))
    assert "mandate_revoked" in api.sent[0][1].text


def test_a_limit_change_carries_the_holders_signature(world) -> None:
    bot, api, aval, identities = world
    bot.handle_update(message("/start"))
    mandate_id = identities.get(MARTA).mandate_id

    bot.handle_update(message("/limite 50"))

    assert aval.mandates[mandate_id]["limit"]["minor_units"] == 5000
    assert aval.verified_claims[-1]["limit_minor_units"] == 5000
    assert "assinado pela sua chave" in api.last_text


def test_a_limit_change_without_a_number_changes_nothing(world) -> None:
    bot, api, aval, identities = world
    bot.handle_update(message("/start"))
    mandate_id = identities.get(MARTA).mandate_id

    bot.handle_update(message("/limite muito"))

    assert aval.mandates[mandate_id]["limit"]["minor_units"] == 20000
    assert "valor positivo" in api.sent[-1][1].text


# ── push ────────────────────────────────────────────────────────────────────
def test_an_escalation_is_pushed_once_and_not_twice(world) -> None:
    bot, api, aval, identities = world
    bot.handle_update(message("/start", chat_id=JUDGE))
    mandate_id = identities.get(JUDGE).mandate_id
    aval.escalations["dh_x"] = {
        "id": "dh_x",
        "mandate_id": mandate_id,
        "checkout_id": "chk",
        "merchant_id": "vuelaya",
        "category": "travel",
        "amount": {"minor_units": 30000, "currency": "USD", "scale": 2},
        "reason_code": "budget_exceeded",
        "status": "OPEN",
        "created_at": datetime.now(UTC).isoformat(),
        "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
    }
    api.sent.clear()

    assert bot.push_pending_approvals() == 1
    assert api.sent[0][0] == JUDGE
    assert bot.push_pending_approvals() == 0


def test_an_escalation_shown_inline_is_not_pushed_again(world) -> None:
    bot, api, _, _ = world
    bot.handle_update(message("/start"))
    bot.handle_update(message("/comprar o voo pra Santiago"))
    assert bot.push_pending_approvals() == 0


# ── failure is never dressed up as success ──────────────────────────────────
def test_an_unreachable_core_reports_that_nothing_ran(world) -> None:
    bot, api, aval, _ = world
    bot.handle_update(message("/start"))
    aval.offline = True
    api.sent.clear()

    bot.handle_update(message("/mandato"))

    assert "Nenhuma ação foi executada" in api.sent[-1][1].text


def test_a_refused_write_leaves_no_confirmation_on_screen(world) -> None:
    bot, api, aval, identities = world
    bot.handle_update(message("/start"))
    mandate_id = identities.get(MARTA).mandate_id
    aval.offline = True

    bot.handle_update(tap(f"rvm:{mandate_id}"))

    assert api.answers[-1] == ("cb1", "AVAL indisponível.")
    assert api.edited == []
    assert aval.mandates[mandate_id]["status"] == "ACTIVE"


def test_the_core_reason_code_reaches_the_screen(world) -> None:
    gateway = AvalGateway("http://127.0.0.1:9000", identities=IdentityStore(Path("nowhere.json")))

    def refusing(request, timeout=None):  # noqa: ANN001 - urlopen shape
        raise urllib.error.HTTPError(
            request.full_url,
            403,
            "forbidden",
            {},
            _Payload(json.dumps({"reason_code": "limit_change_unsigned", "human_summary": "x"}).encode()),
        )

    gateway._opener = refusing  # noqa: SLF001 - transport seam
    with pytest.raises(GatewayError) as raised:
        gateway.mandate("mandate_1")
    assert raised.value.reason_code == "limit_change_unsigned"


# ── plumbing ────────────────────────────────────────────────────────────────
def test_a_person_without_a_mandate_is_told_to_start(world) -> None:
    bot, api, _, _ = world
    bot.handle_update(message("/mandato"))
    assert "Mande /start" in api.sent[-1][1].text


def test_meuid_answers_even_a_chat_with_no_authority(tmp_path: Path) -> None:
    config = BotConfig.from_env(
        {
            "TELEGRAM_BOT_TOKEN": "t",
            "TELEGRAM_ALLOWED_CHAT_IDS": "1",
            "TELEGRAM_IDENTITY_PATH": str(tmp_path / "i.json"),
        }
    )
    api = FakeApi()
    bot = Bot(config, None, IdentityStore(config.identity_path), api)  # type: ignore[arg-type]
    bot.handle_update(message("/meuid", chat_id=JUDGE))
    assert str(JUDGE) in api.sent[0][1].text

    bot.handle_update(message("/mandato", chat_id=JUDGE))
    assert "não tem autoridade" in api.sent[-1][1].text


def test_the_display_name_falls_back_to_the_chat_id() -> None:
    assert _display_name({"first_name": "Marta", "last_name": "Silva"}, 1) == "Marta Silva"
    assert _display_name({}, 77) == "Titular 77"


def test_the_keyboard_is_built_the_way_telegram_expects() -> None:
    calls: list[tuple[str, dict]] = []
    api = TelegramApi("token")
    api.call = lambda method, payload, timeout=None: calls.append((method, payload)) or {}
    api.send_message(MARTA, views.View("oi", ((("Aprovar", "apr:dh_1"),),)))
    assert calls[0][1]["reply_markup"] == {
        "inline_keyboard": [[{"text": "Aprovar", "callback_data": "apr:dh_1"}]]
    }


# ── the dispute, straight from the receipt ──────────────────────────────────
def test_a_settled_purchase_offers_a_way_to_deny_it_later(world) -> None:
    bot, api, _, _ = world
    bot.handle_update(message("/start"))
    api.sent.clear()

    bot.handle_update(message("/comprar um voo pra Cordoba"))

    labels = [label for row in api.sent[0][1].buttons for label, _ in row]
    assert labels == ["⚠️ Não reconheço esta compra"]


def test_denying_a_purchase_opens_a_dispute_against_the_reservation(world) -> None:
    bot, api, aval, _ = world
    bot.handle_update(message("/start"))
    bot.handle_update(message("/comprar um voo pra Cordoba"))

    bot.handle_update(tap("dsp:rsv_1"))

    assert aval.disputes[0]["reservation_id"] == "rsv_1"
    assert "dsp_1" in api.last_text


def test_a_crafted_tap_cannot_dispute_someone_elses_purchase(world) -> None:
    """Disputes are not signed, so the core cannot catch a forged reservation id.

    The bot is the only gate: a judge who crafts `dsp:<another judge's rsv>` must
    be refused here, or one person opens a dispute against another's purchase.
    """
    bot, api, aval, _ = world
    bot.handle_update(message("/start", chat_id=MARTA))
    bot.handle_update(message("/comprar um voo pra Cordoba", chat_id=MARTA))
    bot.handle_update(message("/start", chat_id=JUDGE))
    aval.disputes.clear()

    bot.handle_update(tap("dsp:rsv_1", chat_id=JUDGE))

    assert aval.disputes == [], "a stranger must not open a dispute on this purchase"
    assert "não é sua" in api.last_text


# ── someone arriving for the first time ─────────────────────────────────────
def test_the_welcome_leads_with_a_way_to_buy(world) -> None:
    """The first screen has to answer "what do I do now" without being read twice."""
    bot, api, _, _ = world
    bot.handle_update(message("/start"))

    view = api.sent[0][1]
    first_button = view.buttons[0][0][0]
    assert "comprar" in first_button.lower(), "buying is the point, so it is the first button"
    assert "Ver o que posso comprar" in view.text


def test_the_catalogue_button_asks_what_the_person_wants(world) -> None:
    bot, api, _, _ = world
    bot.handle_update(message("/start"))

    bot.handle_update(tap("cat:_"))

    view = api.edited[-1][2]
    assert "O que você quer?" in view.text
    labels = [label for row in view.buttons for label, _ in row]
    # Two destinations, not three offers: the person names a wish, the agent picks.
    assert len(labels) == 2
    assert any("Córdoba" in label and "US$ 130,00" in label for label in labels)


def test_the_catalogue_marks_what_the_mandate_will_refuse(world) -> None:
    bot, api, _, _ = world
    bot.handle_update(message("/start"))

    bot.handle_update(tap("cat:_"))

    lines = [line for line in api.edited[-1][2].text.splitlines() if line.startswith(("✈️", "🏨"))]
    flight = next(line for line in lines if "✈️" in line)
    stay = next(line for line in lines if "🏨" in line)
    assert "⚠️" not in flight, "US$ 130 fits the US$ 200 budget"
    assert "⚠️" in stay, "lodging is outside the mandate categories"


def test_buying_from_the_catalogue_goes_through_the_agent(world) -> None:
    bot, api, aval, _ = world
    bot.handle_update(message("/start"))
    api.sent.clear()
    api.edited.clear()

    bot.handle_update(tap("buy:travel-cordoba"))

    sent = [body for path, body in aval.received if path == "POST /agent/purchase"][-1]
    assert sent["instruction"] == "voo para Córdoba", "the button feeds the agent an intent"
    assert "Comprado" in api.edited[0][2].text
    # A purchase produces more than one screen; the extras must not be swallowed.
    assert "Extrato" in api.sent[-1][1].text


def test_a_stale_offer_button_says_so_instead_of_failing(world) -> None:
    bot, api, _, _ = world
    bot.handle_update(message("/start"))

    bot.handle_update(tap("buy:travel-atlantida"))

    assert "saiu do catálogo" in api.edited[-1][2].text


def test_a_revoked_mandate_offers_no_way_to_buy(world) -> None:
    bot, api, _, identities = world
    bot.handle_update(message("/start"))
    mandate_id = identities.get(MARTA).mandate_id
    bot.handle_update(tap(f"rvm:{mandate_id}"))
    api.sent.clear()

    bot.handle_update(message("/mandato"))

    labels = [label for row in api.sent[0][1].buttons for label, _ in row]
    assert not any("comprar" in label.lower() for label in labels)


def test_start_issues_a_mandate_that_cannot_pay_for_anything_yet(world) -> None:
    """The case's fourth field is the person's to fill, and it starts empty.

    A mandate born naming a card out of the environment is the system deciding, on
    somebody's behalf, whose money the agent spends. It has authority and no means.
    """
    bot, api, aval, _ = world

    bot.handle_update(message("/start"))

    created = next(body for route, body in aval.received if route == "POST /mandates")
    assert "payment_method" not in created
    assert "••••" not in api.last_text


def test_the_card_is_typed_at_the_processor_and_never_in_the_chat(world) -> None:
    """A number typed here would live in Telegram's servers, the history on every
    logged-in device, the polling response and the log. No care afterwards removes it."""
    bot, api, aval, identities = world
    bot.handle_update(message("/start"))

    bot.handle_update(message("/cartao"))

    assert aval.card_sessions == [identities.get(MARTA).mandate_id]
    assert "checkout.stripe.test" in api.last_text
    assert "não passa por este chat" in api.last_text


def test_an_unfinished_registration_binds_nothing(world) -> None:
    bot, api, aval, _ = world
    bot.handle_update(message("/start"))
    bot.handle_update(message("/cartao"))

    bot.handle_update(message("/cartao"))

    assert aval.bindings == []
    assert "Ainda não vi um cartão" in api.last_text


def _instrument_claims(aval) -> dict:
    """The claims of the binding, found by its scope rather than by its position.

    Reading a mandate is holder-signed too, so the last signature a `/cartao` produces
    is the read that renders the card back — not the binding. Asserting on `[-1]` was
    reading an ordering the test never meant to pin.
    """
    return next(
        claims
        for claims in reversed(aval.verified_claims)
        if claims.get("scope") == "instrument"
    )


def test_the_registered_card_is_bound_with_the_holders_own_signature(world) -> None:
    bot, api, aval, identities = world
    bot.handle_update(message("/start"))
    bot.handle_update(message("/cartao"))
    aval.card_ready = True

    bot.handle_update(message("/cartao"))

    binding = aval.bindings[-1]
    assert binding["token"] == "pm_test_1"
    claims = _instrument_claims(aval)
    assert claims["scope"] == "instrument"
    assert claims["instrument_token"] == "pm_test_1"
    # First card on this mandate: it supersedes nothing, and saying so is what makes
    # the next binding's compare-and-swap meaningful.
    assert claims["supersedes"] is None
    assert "•••• 4242" in api.last_text


def test_replacing_a_card_names_the_one_it_supersedes(world) -> None:
    """Compare-and-swap: without the predecessor, a captured binding could be replayed."""
    bot, api, aval, identities = world
    bot.handle_update(message("/start"))
    bot.handle_update(message("/cartao"))
    aval.card_ready = True
    bot.handle_update(message("/cartao"))

    aval.card_token = "pm_test_2"
    bot.handle_update(message("/cartao"))
    bot.handle_update(message("/cartao"))

    claims = _instrument_claims(aval)
    assert (claims["instrument_token"], claims["supersedes"]) == ("pm_test_2", "pm_test_1")


def test_cancelling_the_card_is_signed_and_leaves_the_mandate_alive(world) -> None:
    """Two brakes, not one. The card stops the money; the mandate keeps the authority.

    A holder who loses a card should not have to end their agent to stop it being
    charged, and the next purchase should say which of the two actually happened.
    """
    bot, api, aval, identities = world
    bot.handle_update(message("/start"))
    mandate_id = identities.get(MARTA).mandate_id
    bot.handle_update(message("/cartao"))
    aval.card_ready = True
    bot.handle_update(message("/cartao"))

    bot.handle_update(tap(f"{views.CALLBACK_CARD_MENU}:{mandate_id}"))
    assert "mandato continua ativo" in api.last_text

    bot.handle_update(tap(f"{views.CALLBACK_CARD_CONFIRM}:{mandate_id}"))

    # Signed by the holder's own key, over this mandate and this scope.
    claims = aval.verified_claims[-1]
    assert claims["mandate_id"] == mandate_id
    assert claims["scope"] == "instrument:pm_test_1"
    assert aval.mandates[mandate_id]["status"] == "ACTIVE", "the agent is still authorized"

    bot.handle_update(message("/comprar um voo pra Córdoba"))
    # `last_text` prefers the edited card left by the tap, so read what was sent.
    assert "instrument_revoked" in api.sent[-1][1].text


def test_a_chat_without_the_card_scope_refuses_rather_than_guessing_one(world) -> None:
    """A guessed scope is a signature over the wrong thing, so it is never signed."""
    bot, api, aval, identities = world
    bot.handle_update(message("/start"))
    mandate_id = identities.get(MARTA).mandate_id
    identities.bind_mandate(MARTA, mandate_id, instrument_scope=None)
    # Authority-bearing signatures only. Reads are signed too now, and counting those
    # would make this test pass or fail on how many screens the bot happened to draw.
    authority_before = [claims for claims in aval.verified_claims if "mandate_id" in claims]

    bot.handle_update(tap(f"{views.CALLBACK_CARD_CONFIRM}:{mandate_id}"))

    assert "escopo do cartão" in api.last_text
    authority_after = [claims for claims in aval.verified_claims if "mandate_id" in claims]
    assert authority_after == authority_before, "nothing was signed"


def test_an_incomplete_request_is_answered_with_a_question_and_buttons(world) -> None:
    """The agent stops and asks, and the answers are the ordinary wish buttons — so
    answering needs no memory of what was asked."""
    bot, api, aval, _ = world
    bot.handle_update(message("/start"))

    bot.handle_update(message("/comprar uma passagem"))

    screen = api.sent[-1][1]
    assert "Para onde" in screen.text
    assert screen.buttons, "a question with no answers is a dead end"
    assert all(
        button[1].startswith(f"{views.CALLBACK_BUY}:") for row in screen.buttons for button in row
    )


# ── the mandate the chat remembers may be gone ──────────────────────────────
def test_a_chat_whose_mandate_vanished_is_told_to_start_again(world) -> None:
    """The stored id outlives the mandate: a reset environment, an expiry purge, a
    fresh database. Every command below the guard needs it to exist.

    Before this, `/comprar` answered "nenhuma ação foi executada" — true, unhelpful,
    and indistinguishable from the backend being down. The person had no way to know
    that `/start` would fix it.
    """
    bot, api, aval, identities = world
    bot.handle_update(message("/start"))
    identities.bind_mandate(MARTA, "mandate_que_nao_existe")

    for command in ("/comprar um voo pra Córdoba", "/extrato", "/aprovacoes", "/mandato"):
        bot.handle_update(message(command))
        assert "/start" in api.sent[-1][1].text, f"{command} não orientou a pessoa"


def test_a_vanished_mandate_does_not_spam_the_escalation_poller(world, caplog) -> None:
    bot, api, aval, identities = world
    bot.handle_update(message("/start"))
    identities.bind_mandate(MARTA, "mandate_que_nao_existe")

    with caplog.at_level("WARNING"):
        assert bot.push_pending_approvals() == 0

    assert not [record for record in caplog.records if "escalações" in record.message]


def test_the_catalogue_leads_with_what_the_mandate_can_actually_buy(world) -> None:
    """A judge taps the first button. It must not be a guaranteed escalation.

    Out-of-scope offers stay on the screen on purpose — the agent trying and the
    mandate barring is the demonstration — but they go below the ones that work, and
    the button says so before it is pressed rather than after.
    """
    bot, api, aval, identities = world
    bot.handle_update(message("/start"))

    bot.handle_update(message("/catalogo"))

    screen = api.sent[-1][1]
    buttons = [button for row in screen.buttons for button in row]
    assert buttons, "o catálogo não ofereceu nada"
    allowed = set(aval.mandates[identities.get(MARTA).mandate_id]["allowed_categories"])

    def category_of(button) -> str:
        return button[1].split(":", 1)[1].split("-", 1)[0]

    assert category_of(buttons[0]) in allowed, (
        f"o primeiro botão é um beco sem saída: {buttons[0][0]}"
    )
    reachable = [index for index, b in enumerate(buttons) if category_of(b) in allowed]
    barred = [index for index, b in enumerate(buttons) if category_of(b) not in allowed]
    assert barred, "o fake precisa oferecer algo fora do escopo para este teste valer"
    assert min(barred) > max(reachable), "o que o mandato permite vem antes do que ele barra"
    assert all("⚠️" in buttons[index][0] for index in barred), (
        "um botão que o mandato vai barrar tem de avisar antes de ser tocado"
    )


# ── the agent that keeps working after you stop typing ──────────────────────
def test_an_unreachable_target_offers_to_watch_instead_of_giving_up(world) -> None:
    """*Buy me a flight if it drops below X* is not a dead end, it is a standing order.

    Answering "nada no catálogo atende" to the case's own scenario throws away the one
    behaviour that makes the buyer an agent rather than a form.
    """
    bot, api, aval, _ = world
    bot.handle_update(message("/start"))

    bot.handle_update(message("/comprar um voo pra Córdoba abaixo de $80"))

    screen = api.sent[-1][1]
    buttons = [button for row in screen.buttons for button in row]
    # The offer is the button: the text may explain, but the tap is what accepts.
    assert any("vigiar" in label.lower() for label, _ in buttons)
    assert any(data.startswith(views.CALLBACK_WATCH) for _, data in buttons)


def test_watching_is_registered_only_when_the_person_asks_for_it(world) -> None:
    """An agent that starts buying on its own without being told to is the failure the
    case calls a silent approval. The tap is the consent."""
    bot, api, aval, identities = world
    bot.handle_update(message("/start"))
    mandate_id = identities.get(MARTA).mandate_id

    bot.handle_update(message("/comprar um voo pra Córdoba abaixo de $80"))
    assert aval.watches == {}, "oferecer não é registrar"

    bot.handle_update(tap(f"{views.CALLBACK_WATCH}:{mandate_id}"))

    assert [watch["instruction"] for watch in aval.watches.values()] == [
        "um voo pra Córdoba abaixo de $80"
    ]
    assert "vigiando" in api.sent[-1][1].text.lower()


def test_the_agent_reports_a_purchase_nobody_asked_it_to_make_now(world) -> None:
    """The moment the case is actually about: the price falls, and the phone buzzes.

    The bot no longer drives this. The core decided and charged on its own schedule and
    wrote what happened to its outbox; all this side does is read it and speak.
    """
    bot, api, aval, identities = world
    bot.handle_update(message("/start"))
    principal_id = identities.get(MARTA).principal_id
    before = len(api.sent)

    aval.enqueue_watch_closed(
        principal_id=principal_id,
        outcome="settled",
        title="Notebook Acer Aspire 5",
        source_merchant="shop.example",
        source_url="https://shop.example/aspire-5",
        amount_minor_units=7500,
        currency="USD",
        scale=2,
        settlement_reference="pi_test_1",
    )

    assert bot.push_watch_results() == 1
    delivered = api.sent[before][1].text
    assert "sozinho" in delivered.lower(), "a mensagem tem de dizer que ninguém pediu"
    assert "US$ 75,00" in delivered


def test_bot_sends_offer_link_then_acknowledges_event(world) -> None:
    """The link is the deliverable, and the acknowledgement comes after the send."""
    bot, api, aval, identities = world
    bot.handle_update(message("/start"))
    principal_id = identities.get(MARTA).principal_id
    event_id = aval.enqueue_watch_closed(
        principal_id=principal_id,
        outcome="settled",
        title="Notebook",
        source_url="https://shop.example/item",
        amount_minor_units=7500,
        currency="USD",
        scale=2,
    )

    bot.push_watch_results()

    assert "shop.example/item" in api.sent[-1][1].text
    assert aval.acknowledged_event_ids == [event_id]


def test_the_message_never_claims_an_order_reached_the_seller(world) -> None:
    """A signed offer and a real charge together read as "an order was placed", and no
    order was. The copy has to say so, every time."""
    bot, api, aval, identities = world
    bot.handle_update(message("/start"))
    aval.enqueue_watch_closed(
        principal_id=identities.get(MARTA).principal_id,
        outcome="settled",
        title="Notebook",
        source_url="https://shop.example/item",
        amount_minor_units=7500,
        currency="USD",
        scale=2,
    )

    bot.push_watch_results()

    assert "Não enviei pedido ao vendedor" in api.sent[-1][1].text


def test_a_revoked_mandate_makes_the_agent_report_the_attempt_not_the_purchase(world) -> None:
    """The thesis, delivered by a machine acting alone: the agent kept working, the
    authority did not."""
    bot, api, aval, identities = world
    bot.handle_update(message("/start"))
    before = len(api.sent)

    aval.enqueue_watch_closed(
        principal_id=identities.get(MARTA).principal_id,
        outcome="mandate_revoked",
        title="Notebook Acer Aspire 5",
        source_url="https://shop.example/aspire-5",
        amount_minor_units=7500,
        currency="USD",
        scale=2,
        human_summary="O mandato foi revogado.",
    )

    assert bot.push_watch_results() == 1
    delivered = api.sent[before][1].text
    assert "mandate_revoked" in delivered
    assert "não comprei" in delivered.lower()


def test_a_fired_watch_is_reported_once(world) -> None:
    """Nobody wants the same autonomous purchase announced twice."""
    bot, api, aval, identities = world
    bot.handle_update(message("/start"))
    aval.enqueue_watch_closed(
        principal_id=identities.get(MARTA).principal_id,
        outcome="settled",
        title="Notebook",
        source_url="https://shop.example/item",
        amount_minor_units=7500,
        currency="USD",
        scale=2,
    )

    assert bot.push_watch_results() == 1
    assert bot.push_watch_results() == 0


def test_an_event_that_telegram_refuses_is_not_acknowledged(world) -> None:
    """The whole reason the outbox exists. A send that failed must come back."""
    bot, api, aval, identities = world
    bot.handle_update(message("/start"))
    aval.enqueue_watch_closed(
        principal_id=identities.get(MARTA).principal_id, outcome="settled", title="Notebook"
    )
    api.fail_next = True

    assert bot.push_watch_results() == 0
    assert aval.acknowledged_event_ids == []

    api.fail_next = False
    assert bot.push_watch_results() == 1


def test_an_event_for_a_buyer_this_bot_does_not_know_is_left_alone(world) -> None:
    """Another edge may hold that chat. Acknowledging here would silence news meant
    for someone else."""
    bot, api, aval, _ = world
    bot.handle_update(message("/start"))
    aval.enqueue_watch_closed(principal_id="usr_someone_else", outcome="settled")

    assert bot.push_watch_results() == 0
    assert aval.acknowledged_event_ids == []


def test_an_unreachable_core_outbox_is_not_a_crash(world) -> None:
    bot, api, aval, identities = world
    bot.handle_update(message("/start"))
    aval.enqueue_watch_closed(principal_id=identities.get(MARTA).principal_id, outcome="settled")
    aval.edge_open = False

    assert bot.push_watch_results() == 0


def test_the_mandate_card_says_what_the_agent_is_watching(world) -> None:
    """An agent that may buy on its own has to show what it is waiting for.

    Otherwise the standing order is invisible authority: the person consented once and
    then has no way to see, or reconsider, what is still armed.
    """
    bot, api, aval, identities = world
    bot.handle_update(message("/start"))
    mandate_id = identities.get(MARTA).mandate_id
    bot.handle_update(message("/comprar um voo pra Córdoba abaixo de $80"))
    bot.handle_update(tap(f"{views.CALLBACK_WATCH}:{mandate_id}"))

    bot.handle_update(message("/mandato"))

    assert "abaixo de $80" in api.sent[-1][1].text


def test_a_payment_in_confirmation_is_neither_bought_nor_refused():
    """Two words the bot must not use for a held purchase: comprado, recusado."""
    from aval.interfaces.telegram.views import purchase_result
    from aval.interfaces.telegram.gateway import MoneyView, PurchaseView

    view = purchase_result(
        PurchaseView(
            outcome="in_doubt",
            reason_code="settlement_unreachable",
            human_summary="Compra autorizada e em confirmação.",
            title="Voo GRU→COR",
            amount=MoneyView(minor_units=13000, currency="USD", scale=2),
            escalation_id=None,
            reservation_id=None,
            settlement_reference=None,
        )
    )

    assert "confirmação" in view.text.lower()
    assert "comprado" not in view.text.lower()
    assert "recusado" not in view.text.lower()
# ── the trail answers the dispute ───────────────────────────────────────────
def test_denying_a_purchase_returns_the_verdict_the_trail_produced(world) -> None:
    """The bonus the case asks for: the denial is answered, not just filed.

    Opening a dispute and leaving it open would show the person a promise. The
    resolution reads the ledger and asks nobody, so the verdict arrives in the
    same tap or the feature is theatre.
    """
    bot, api, aval, _ = world
    bot.handle_update(message("/start"))
    bot.handle_update(message("/comprar um voo pra Cordoba"))

    bot.handle_update(tap("dsp:rsv_1"))

    assert "MANDATE_HELD" in api.last_text
    assert "terms_hash th_1" in api.last_text


def test_a_purchase_with_no_proof_behind_it_resolves_for_the_holder(world) -> None:
    bot, api, aval, _ = world
    bot.handle_update(message("/start"))
    bot.handle_update(message("/comprar um voo pra Cordoba"))
    aval.dispute_status = "MANDATE_FAILED"

    bot.handle_update(tap("dsp:rsv_1"))

    assert "MANDATE_FAILED" in api.last_text
    assert "estorno é seu" in api.last_text


def test_the_dispute_button_survives_a_restart_of_the_bot(world, restart) -> None:
    """A restart that forgets what the person bought turns the denial into a lie.

    The identity store already outlives the process; the reservations belong there
    for the same reason the keys do.
    """
    bot, _, aval, identities = world
    bot.handle_update(message("/start"))
    bot.handle_update(message("/comprar um voo pra Cordoba"))

    revived, revived_api, _, _ = restart(aval)
    revived.handle_update(tap("dsp:rsv_1"))

    assert "MANDATE_HELD" in revived_api.last_text


# ── the extract proves itself ───────────────────────────────────────────────
def test_the_extract_says_the_chain_was_checked(world) -> None:
    bot, api, _, _ = world
    bot.handle_update(message("/start"))

    bot.handle_update(message("/extrato"))

    assert "Trilha íntegra" in api.last_text
    assert "3 evento(s) conferidos" in api.last_text


def test_a_broken_chain_is_reported_instead_of_being_claimed_intact(world) -> None:
    """Tampering has to reach the person's own screen, not only the auditor's."""
    bot, api, aval, _ = world
    bot.handle_update(message("/start"))
    aval.chain_intact = False

    bot.handle_update(message("/extrato"))

    assert "TRILHA VIOLADA" in api.last_text
    assert "#2" in api.last_text


# ── frequency is authority, and it is visible ───────────────────────────────
def test_the_mandate_is_created_with_the_frequency_rule_and_shows_it(world) -> None:
    """The case's "up to 3 times a month" — enforced by the core, said by the card."""
    bot, api, aval, _ = world

    bot.handle_update(message("/start"))

    created = next(body for route, body in aval.received if route == "POST /mandates")
    assert created["usage_limit"] == {"max_uses": 3, "window_seconds": 30 * 86_400}
    assert "3 de 3</b> compra(s) livres nos últimos 30 dia(s)" in api.last_text


# ── two identities, two keys ────────────────────────────────────────────────
def test_the_agent_is_shown_as_an_identity_of_its_own(world) -> None:
    """The case separates the agent's identity from the human's; the bot has to say so.

    Both keys exist and neither can produce the other's signature — a screen that
    names them is what turns that from architecture into something a judge can check.
    """
    bot, api, _, identities = world
    bot.handle_update(message("/start"))

    bot.handle_update(message("/agente"))

    text = api.last_text
    assert "agt_marta" in text and "agent-demo" in text
    assert identities.get(MARTA).kid in text
    assert "usr_tg_" in text


def test_the_agent_card_holds_when_the_core_cannot_name_the_agent(world) -> None:
    """An unknown agent is said plainly, never rendered as a confident identity."""
    bot, api, aval, _ = world
    bot.handle_update(message("/start"))
    aval.offline = True

    bot.handle_update(message("/agente"))

    assert "perfil indisponível" in api.last_text


# ── a room of judges, not a queue ───────────────────────────────────────────
def test_a_slow_purchase_in_one_chat_does_not_hold_up_another(world) -> None:
    """The demo is several people tapping at once, not one person taking turns.

    Serial handling made every judge wait behind whoever bought last — with an HTTP
    timeout measured in seconds, that reads as a dead bot. Two things are asserted
    because both can break alone: the poll loop is never blocked by a slow chat, and
    the other chat is answered *while* that call is still in flight.
    """
    bot, api, aval, _ = world
    bot.handle_update(message("/start"))
    aval.hold = threading.Event()

    started = time.monotonic()
    bot.dispatch(message("/comprar um voo pra Cordoba"))
    bot.dispatch(message("/start", chat_id=JUDGE, first_name="Juíza"))
    handed_off = time.monotonic() - started

    answered_while_held = False
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        if any(chat == JUDGE for chat, _ in api.sent):
            answered_while_held = True
            break
        time.sleep(0.01)
    aval.hold.set()

    assert handed_off < 1, "dispatch segurou a thread que faz o polling"
    assert answered_while_held, "o outro chat só foi atendido depois da compra lenta"


def test_one_chat_is_still_answered_in_the_order_it_typed(world) -> None:
    """Parallel across chats, serial within one: a person's own messages are a sequence."""
    bot, api, _, _ = world

    bot.dispatch(message("/start"))
    bot.dispatch(message("/mandato"))
    bot.dispatch(message("/extrato"))

    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and len(api.sent) < 3:
        time.sleep(0.01)
    assert "AVAL" in api.sent[0][1].text
    assert "Extrato" in api.sent[2][1].text


# ── the person defines the mandate, not the environment ─────────────────────
def test_the_spec_reads_what_how_much_and_until_when(world) -> None:
    """The case's first line, read off one sentence.

    Counts and money share a sentence and must not be confused: `por 7 dias` is a
    deadline, not a seven-real budget.
    """
    bot, _, _, _ = world
    defaults = bot._config.mandate_defaults

    spec = views.parse_mandate_spec("hotel até 300 por 7 dias, 2x", defaults=defaults)

    assert spec.categories == ("lodging",)
    assert spec.limit.minor_units == 30_000
    assert spec.valid_for_days == 7
    assert spec.max_uses == 2


def test_an_empty_spec_is_refused_rather_than_defaulted(world) -> None:
    """Silence is not a mandate: the defaults must never stand in for consent."""
    bot, _, _, _ = world
    assert views.parse_mandate_spec("   ", defaults=bot._config.mandate_defaults) is None


def test_what_the_sentence_omits_falls_back_to_the_default(world) -> None:
    bot, _, _, _ = world
    defaults = bot._config.mandate_defaults

    spec = views.parse_mandate_spec("voo", defaults=defaults)

    assert spec.categories == ("travel",)
    assert spec.limit.minor_units == defaults.limit_minor_units
    assert spec.valid_for_days == defaults.valid_for.days


def test_a_new_mandate_is_previewed_before_anything_is_issued(world) -> None:
    """Replacing a mandate revokes the one in force — far too much for a typo."""
    bot, api, aval, identities = world
    bot.handle_update(message("/start"))
    first = identities.get(MARTA).mandate_id
    api.sent.clear()

    bot.handle_update(message("/novo hotel até 300 por 7 dias"))

    assert "confira antes" in api.last_text
    assert "revoga" in api.last_text
    assert identities.get(MARTA).mandate_id == first
    assert aval.mandates[first]["status"] == "ACTIVE"


def test_confirming_revokes_the_old_mandate_and_issues_the_described_one(world) -> None:
    bot, api, aval, identities = world
    bot.handle_update(message("/start"))
    first = identities.get(MARTA).mandate_id
    bot.handle_update(message("/novo hotel até 300 por 7 dias, 2x"))

    bot.handle_update(tap(f"{views.CALLBACK_NEW_CONFIRM}:{first}"))

    second = identities.get(MARTA).mandate_id
    assert second != first
    assert aval.mandates[first]["status"] == "REVOKED"
    issued = aval.mandates[second]
    assert issued["allowed_categories"] == ["lodging"]
    assert issued["limit"]["minor_units"] == 30_000
    assert issued["usage_limit"]["max_uses"] == 2
    # A new mandate is authority and nothing else: the card is registered separately,
    # and does not follow the person from the mandate they just replaced.
    assert issued.get("instrument_label") is None


def test_confirming_a_spec_the_bot_no_longer_holds_issues_nothing(world) -> None:
    """A restart between describing and confirming must not invent the mandate."""
    bot, api, aval, identities = world
    bot.handle_update(message("/start"))
    first = identities.get(MARTA).mandate_id

    bot.handle_update(tap(f"{views.CALLBACK_NEW_CONFIRM}:{first}"))

    assert identities.get(MARTA).mandate_id == first
    assert "Descreva o mandato de novo" in api.last_text


# ── conversation ────────────────────────────────────────────────────────────
class ScriptedTalker:
    """A model that says what the test needs, in the order the test needs it."""

    def __init__(self, *drafts) -> None:
        self.drafts = list(drafts)
        self.seen: list[tuple[str, ...]] = []
        self.categories: tuple[str, ...] = ()

    def respond(self, history, *, categories, defaults):
        self.seen.append(tuple(turn.text for turn in history))
        self.categories = tuple(categories)
        return self.drafts.pop(0)


def test_free_text_is_answered_in_chat_until_the_mandate_is_complete(tmp_path) -> None:
    """The bot converses, then always lands on a spec the person can sign."""
    talker = ScriptedTalker(
        conversation.Draft("Até quanto você quer poder gastar?", None),
        conversation.Draft(
            "Hotel até 300 dólares, por 7 dias.",
            views.MandateSpec(("lodging",), MoneyView(30_000, "USD", 2), 7, 2),
        ),
    )
    bot, api, aval, identities = _build(tmp_path, FakeAval())
    bot._talker = talker
    bot.handle_update(message("/start"))
    first = identities.get(MARTA).mandate_id
    api.sent.clear()

    bot.handle_update(message("queria poder reservar hotel"))
    assert api.last_text == "Até quanto você quer poder gastar?"
    assert not api.sent[-1][1].buttons
    # Nothing was granted from words alone.
    assert aval.mandates[first]["status"] == "ACTIVE"
    assert identities.get(MARTA).mandate_id == first

    api.sent.clear()
    bot.handle_update(message("até 300, por uma semana"))
    preview = api.sent[-1][1]
    assert "confira antes" in preview.text
    assert "US$ 300,00" in preview.text and "7 dia" in preview.text
    confirm = [label for row in preview.buttons for label, _ in row]
    assert confirm == ["✅ Emitir este mandato"]

    # The whole exchange, and only the catalogue's own categories, reached the model.
    assert talker.seen[-1] == (
        "queria poder reservar hotel",
        "Até quanto você quer poder gastar?",
        "até 300, por uma semana",
    )
    assert "lodging" in talker.categories

    bot.handle_update(tap(f"{views.CALLBACK_NEW_CONFIRM}:{first}"))
    second = identities.get(MARTA).mandate_id
    assert second != first
    assert aval.mandates[first]["status"] == "REVOKED"
    assert aval.mandates[second]["limit"]["minor_units"] == 30_000


# ── the shopping watch, end to end on the edge ──────────────────────────────
def _shopping_draft(days: int = 30):
    return conversation.Draft(
        "Entendi: vou acompanhar um notebook.",
        views.MandateSpec(("shopping",), MoneyView(200_000, "USD", 2), 30, 1),
        conversation.ShoppingDraft(
            query="notebook para faculdade",
            category="shopping",
            max_minor_units=200_000,
            currency="USD",
            watch_days=days,
        ),
    )


def test_the_search_is_previewed_as_its_own_decision(tmp_path) -> None:
    """Authority and a standing order are two things, and the person reads them as two.

    The mandate card says what may be spent. This says the agent will spend it without
    asking again — which is the part somebody might want to say no to on its own.
    """
    bot, api, aval, identities = _build(tmp_path, FakeAval())
    bot._talker = ScriptedTalker(_shopping_draft())
    bot.handle_update(message("/start"))
    api.sent.clear()

    bot.handle_update(message("acompanhe um notebook até 2000 por 30 dias"))

    preview = api.sent[-1][1].text
    assert "notebook para faculdade" in preview
    assert "US$ 2.000,00" in preview
    assert "30 dia" in preview
    assert "compro sozinho" in preview
    assert "Não enviei pedido ao vendedor" in preview


def test_confirming_arms_the_watch_with_a_structured_request(tmp_path) -> None:
    """The tap is what grants. Only after it does a watch exist at all."""
    bot, api, aval, identities = _build(tmp_path, FakeAval())
    bot._talker = ScriptedTalker(_shopping_draft())
    bot.handle_update(message("/start"))
    first = identities.get(MARTA).mandate_id
    bot.handle_update(message("acompanhe um notebook até 2000 por 30 dias"))

    assert aval.watches == {}, "nada é vigiado antes da confirmação"

    bot.handle_update(tap(f"{views.CALLBACK_NEW_CONFIRM}:{first}"))

    watch = next(iter(aval.watches.values()))
    request = decode_shopping_request(watch["instruction"])
    assert request is not None, "a vigília guarda um pedido estruturado, não uma frase"
    assert request.query == "notebook para faculdade"
    assert request.max_minor_units == 200_000
    assert request.currency == "USD"
    assert "Vigilância ligada" in api.sent[-1][1].text


def test_a_shopping_mandate_names_the_marketplace_that_signs_discovered_pages(tmp_path) -> None:
    """Without it every page a search finds is refused as an out-of-scope merchant —
    and the travel sellers have to survive, not be replaced."""
    bot, api, aval, identities = _build(tmp_path, FakeAval())
    bot._talker = ScriptedTalker(_shopping_draft())
    bot.handle_update(message("/start"))
    first = identities.get(MARTA).mandate_id
    bot.handle_update(message("acompanhe um notebook até 2000 por 30 dias"))

    bot.handle_update(tap(f"{views.CALLBACK_NEW_CONFIRM}:{first}"))

    merchants = aval.mandates[identities.get(MARTA).mandate_id]["allowed_merchant_ids"]
    assert TEST_MARKETPLACE_ID in merchants
    assert "vuelaya" in merchants


def test_a_mandate_without_a_search_arms_nothing(tmp_path) -> None:
    """Describing only authority is a perfectly good thing to do."""
    bot, api, aval, identities = _build(tmp_path, FakeAval())
    bot._talker = ScriptedTalker(
        conversation.Draft(
            "Hotel até 300 dólares, por 7 dias.",
            views.MandateSpec(("lodging",), MoneyView(30_000, "USD", 2), 7, 2),
        )
    )
    bot.handle_update(message("/start"))
    first = identities.get(MARTA).mandate_id
    bot.handle_update(message("hotel até 300 por 7 dias"))

    bot.handle_update(tap(f"{views.CALLBACK_NEW_CONFIRM}:{first}"))

    assert aval.watches == {}


def test_shopping_is_offered_even_though_no_catalogue_row_carries_it(tmp_path) -> None:
    """Every `shopping` offer is minted from a page a search just found, so the
    category would never appear from the catalogue alone — and a person could then
    never scope a mandate to the thing this MVP is for."""
    bot, api, aval, identities = _build(tmp_path, FakeAval())
    talker = ScriptedTalker(_shopping_draft())
    bot._talker = talker
    bot.handle_update(message("/start"))

    bot.handle_update(message("acompanhe um notebook"))

    assert "shopping" in talker.categories
