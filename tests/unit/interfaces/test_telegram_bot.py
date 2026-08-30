from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
import json
import urllib.error

import pytest

from aval.interfaces.telegram import views
from aval.interfaces.telegram.bot import Bot, TelegramApi, _display_name
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
        self.offline = False
        self._sequence = 0

    # transport ------------------------------------------------------------
    def opener(self, request, timeout=None):  # noqa: ANN001 - urlopen shape
        if self.offline:
            raise OSError("connection refused")
        path = request.full_url.split("127.0.0.1:9000", 1)[1]
        body = json.loads(request.data) if request.data else {}
        status, payload = self._route(request.get_method(), path, body)
        if status >= 400:
            raise urllib.error.HTTPError(
                request.full_url, status, "error", {}, _Payload(json.dumps(payload).encode())
            )
        return _Payload(json.dumps(payload).encode())

    def _route(self, method: str, path: str, body: dict[str, Any]):
        route, _, query = path.partition("?")
        params = dict(pair.split("=", 1) for pair in query.split("&") if "=" in pair)
        self.received.append((f"{method} {route}", body))
        if route == "/health":
            return 200, {"status": "ok"}
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
        if route.startswith("/mandates/") and route.endswith("/revocation"):
            return self._revoke(route.split("/")[2], body)
        if route.startswith("/mandates/") and route.endswith("/limit"):
            return self._replace_limit(route.split("/")[2], body)
        if route.startswith("/mandates/"):
            mandate = self.mandates.get(route.split("/")[2])
            return (200, mandate) if mandate else (404, {"reason_code": "mandate_not_found"})
        if route == "/escalations":
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
            mandate = self.mandates[params["mandate_id"]]
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
            self.disputes.append(body)
            return 201, {"dispute_id": "dsp_1", "status": "OPEN", "reason": body["reason"]}
        if route == "/agent/purchase":
            return self._purchase(body)
        return 404, {"reason_code": "not_found"}

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
            "_jwk": body["authorities"][0]["public_jwk"],
        }
        return {"mandate_id": mandate_id, "policy_version": 1, "revocation_id": "rev_1"}

    def _verify(self, mandate_id: str, token: str) -> dict[str, Any]:
        """Exactly what the core does: the holder's published key, or nothing."""
        claims = verify_compact_jws(token, public_key_from_jwk(self.mandates[mandate_id]["_jwk"]))
        self.verified_claims.append(claims)
        return claims

    def _revoke(self, mandate_id: str, body: dict[str, Any]):
        claims = self._verify(mandate_id, body["token"])
        if claims.get("mandate_id") != mandate_id:
            return 400, {"reason_code": "revocation_mandate_mismatch"}
        self.mandates[mandate_id]["status"] = "REVOKED"
        self.mandates[mandate_id]["revocation_epoch"] = claims["epoch"]
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

    def _purchase(self, body: dict[str, Any]):
        mandate_id = body["mandate_id"]
        if self.mandates[mandate_id]["status"] == "REVOKED":
            return 200, {
                "outcome": "rejected",
                "reason_code": "mandate_revoked",
                "human_summary": "Mandato revogado.",
                "offer": _offer("Voo Córdoba", 13000, "travel"),
                "escalation_id": None,
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
        return 200, {
            "outcome": "settled",
            "reason_code": "settled",
            "human_summary": "Compra concluída.",
            "offer": _offer("Voo Córdoba", 13000, "travel"),
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

    def send_message(self, chat_id: int, view: views.View) -> dict:
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


@pytest.fixture
def world(tmp_path: Path):
    aval = FakeAval()
    config = BotConfig.from_env(
        {
            "TELEGRAM_BOT_TOKEN": "t",
            "TELEGRAM_OPEN_MODE": "1",
            "AVAL_API_BASE_URL": "http://127.0.0.1:9000",
            "TELEGRAM_IDENTITY_PATH": str(tmp_path / "identities.json"),
        }
    )
    identities = IdentityStore(config.identity_path)
    gateway = AvalGateway("http://127.0.0.1:9000", identities=identities, opener=aval.opener)
    api = FakeApi()
    return Bot(config, gateway, identities, api), api, aval, identities


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
