from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json

import pytest

from aval.interfaces.telegram import views
from aval.interfaces.telegram.bot import Bot, TelegramApi, _idempotency_key
from aval.interfaces.telegram.config import BotConfig, ConfigError
from aval.interfaces.telegram.gateway import (
    GatewayError,
    HttpGateway,
    MockGateway,
    MoneyView,
    build_gateway,
)

ALLOWED_CHAT = 4242
INTRUDER_CHAT = 777


class FakeApi:
    """Records outbound calls instead of talking to Telegram."""

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


class BrokenGateway:
    def health(self):
        raise GatewayError("connection refused")

    def list_mandates(self):
        raise GatewayError("connection refused")

    def get_mandate(self, mandate_id):
        raise GatewayError("connection refused")

    def list_pending_approvals(self):
        raise GatewayError("connection refused")

    def resolve_approval(self, approval_id, *, approve, actor, idempotency_key):
        raise GatewayError("connection refused")

    def revoke(self, mandate_id, *, scope, reason, actor, idempotency_key):
        raise GatewayError("connection refused")

    def activity(self, mandate_id=None, limit=10):
        raise GatewayError("connection refused")


def make_config(**overrides) -> BotConfig:
    env = {
        "TELEGRAM_BOT_TOKEN": "test-token",
        "TELEGRAM_ALLOWED_CHAT_IDS": str(ALLOWED_CHAT),
        **overrides,
    }
    return BotConfig.from_env(env)


def make_bot(gateway=None, config=None) -> tuple[Bot, FakeApi]:
    api = FakeApi()
    resolved_config = config or make_config()
    bot = Bot(resolved_config, gateway or MockGateway(), api)
    return bot, api


def message(text: str, chat_id: int = ALLOWED_CHAT) -> dict:
    return {"update_id": 1, "message": {"chat": {"id": chat_id}, "text": text}}


def callback(data: str, chat_id: int = ALLOWED_CHAT) -> dict:
    return {
        "update_id": 2,
        "callback_query": {
            "id": "cb1",
            "data": data,
            "from": {"username": "marta"},
            "message": {"message_id": 9, "chat": {"id": chat_id}},
        },
    }


# ── configuration ───────────────────────────────────────────────────────────
def test_config_requires_a_token() -> None:
    with pytest.raises(ConfigError):
        BotConfig.from_env({})


def test_config_rejects_a_non_numeric_chat_id() -> None:
    with pytest.raises(ConfigError):
        BotConfig.from_env({"TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_ALLOWED_CHAT_IDS": "4242,marta"})


def test_config_without_an_allowlist_authorizes_nobody() -> None:
    config = BotConfig.from_env({"TELEGRAM_BOT_TOKEN": "t"})
    assert config.allowed_chat_ids == frozenset()
    assert config.may_act(ALLOWED_CHAT) is False


def test_gateway_is_mock_until_the_backend_url_is_set() -> None:
    assert isinstance(build_gateway(make_config()), MockGateway)
    live = build_gateway(make_config(AVAL_API_BASE_URL="http://localhost:8000/"))
    assert isinstance(live, HttpGateway)


# ── money and callback parsing ──────────────────────────────────────────────
@pytest.mark.parametrize(
    ("money", "expected"),
    [
        (MoneyView(250_000, "BRL", 2), "R$ 2.500,00"),
        (MoneyView(5, "BRL", 2), "R$ 0,05"),
        (MoneyView(-1_234_567, "USD", 2), "-US$ 12.345,67"),
        (MoneyView(1_500, "JPY", 0), "JPY 1.500"),
    ],
)
def test_money_renders_from_minor_units_without_floats(money: MoneyView, expected: str) -> None:
    assert views.format_money(money) == expected


@pytest.mark.parametrize("data", ["", "boom", "apr:", "apr:../etc/passwd", "apr:" + "x" * 70, "drop:1"])
def test_callback_rejects_untrusted_payloads(data: str) -> None:
    assert views.parse_callback(data) is None


def test_callback_accepts_a_known_verb() -> None:
    assert views.parse_callback("apr:esc_9f21") == (views.CALLBACK_APPROVE, "esc_9f21")


# ── authorization is fail-closed ────────────────────────────────────────────
def test_unlisted_chat_cannot_read_mandates() -> None:
    bot, api = make_bot()
    bot.handle_update(message("/mandatos", chat_id=INTRUDER_CHAT))
    assert len(api.sent) == 1
    assert "não tem autoridade" in api.sent[0][1].text


def test_unlisted_chat_cannot_approve_a_purchase() -> None:
    gateway = MockGateway()
    bot, api = make_bot(gateway)
    bot.handle_update(callback("apr:esc_9f21", chat_id=INTRUDER_CHAT))
    assert api.answers == [("cb1", "Chat sem autoridade.")]
    assert api.edited == []
    assert any(item.id == "esc_9f21" for item in gateway.list_pending_approvals())


def test_start_tells_an_unlisted_chat_how_to_be_authorized() -> None:
    bot, api = make_bot()
    bot.handle_update(message("/start", chat_id=INTRUDER_CHAT))
    assert str(INTRUDER_CHAT) in api.sent[0][1].text


# ── the human decisions ─────────────────────────────────────────────────────
def test_approving_resolves_the_escalation_once() -> None:
    gateway = MockGateway()
    bot, api = make_bot(gateway)

    bot.handle_update(callback("apr:esc_9f21"))
    assert "aprovada" in api.edited[-1][2].text
    assert all(item.id != "esc_9f21" for item in gateway.list_pending_approvals())

    bot.handle_update(callback("apr:esc_9f21"))
    assert "aprovada" in api.edited[-1][2].text, "a replayed tap must not turn into a failure"


def test_revoking_a_mandate_stops_the_mandate_and_bumps_the_epoch() -> None:
    gateway = MockGateway()
    bot, api = make_bot(gateway)
    before = gateway.get_mandate("mnd_marta_01")

    bot.handle_update(callback("rvm:mnd_marta_01"))

    after = gateway.get_mandate("mnd_marta_01")
    assert after.status == "REVOKED"
    assert after.revocation_epoch == before.revocation_epoch + 1
    assert "revogado" in api.edited[-1][2].text.lower()


def test_a_decision_key_is_stable_per_chat_and_target() -> None:
    assert _idempotency_key("apr", "esc_1", ALLOWED_CHAT) == _idempotency_key("apr", "esc_1", ALLOWED_CHAT)
    assert _idempotency_key("apr", "esc_1", ALLOWED_CHAT) != _idempotency_key("den", "esc_1", ALLOWED_CHAT)


# ── escalation push ─────────────────────────────────────────────────────────
def test_pending_escalations_are_pushed_once_per_approval() -> None:
    bot, api = make_bot()
    assert bot.push_pending_approvals() == 2
    assert {chat for chat, _ in api.sent} == {ALLOWED_CHAT}
    assert bot.push_pending_approvals() == 0


# ── an unreachable backend never reads as success ───────────────────────────
def test_backend_failure_is_reported_not_swallowed() -> None:
    bot, api = make_bot(BrokenGateway())
    bot.handle_update(message("/mandatos"))
    assert "indisponível" in api.sent[-1][1].text
    assert "Nenhuma ação foi executada" in api.sent[-1][1].text


def test_backend_failure_on_a_decision_leaves_no_confirmation() -> None:
    bot, api = make_bot(BrokenGateway())
    bot.handle_update(callback("apr:esc_9f21"))
    assert api.answers == [("cb1", "AVAL indisponível.")]
    assert api.edited == []


# ── http gateway wiring ─────────────────────────────────────────────────────
class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = json.dumps(payload).encode()

    def read(self) -> bytes:
        return self._payload

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_: object) -> None:
        return None


def test_http_gateway_sends_bearer_and_idempotency_headers() -> None:
    captured: list = []

    def opener(request, timeout):  # noqa: ANN001 - urlopen shape
        captured.append(request)
        return FakeResponse({"ok": True, "human_summary": "Compra aprovada."})

    config = make_config(AVAL_API_BASE_URL="http://api.local", AVAL_API_TOKEN="s3cr3t")
    gateway = HttpGateway(config, opener=opener)

    result = gateway.resolve_approval("esc_1", approve=True, actor="telegram:@marta", idempotency_key="k1")

    assert result.ok and result.message == "Compra aprovada."
    request = captured[0]
    assert request.full_url == "http://api.local/v1/escalations/esc_1/decision"
    assert request.get_header("Authorization") == "Bearer s3cr3t"
    assert request.get_header("Idempotency-key") == "k1"
    assert json.loads(request.data)["decision"] == "approve"


def test_http_gateway_reads_a_mandate_payload() -> None:
    payload = {
        "mandates": [
            {
                "id": "mnd_1",
                "principal": "Marta",
                "agent": "agent://shopper",
                "status": "ACTIVE",
                "limit": {"minor_units": 250_000, "currency": "BRL", "scale": 2},
                "spent": {"minor_units": 1_000, "currency": "BRL", "scale": 2},
                "allowed_merchant_ids": ["mrc_zenith"],
                "expires_at": "2026-09-30T12:00:00Z",
                "policy_version": 2,
                "revocation_epoch": 1,
            }
        ]
    }
    gateway = HttpGateway(
        make_config(AVAL_API_BASE_URL="http://api.local"),
        opener=lambda request, timeout: FakeResponse(payload),
    )
    mandate = gateway.list_mandates()[0]
    assert mandate.id == "mnd_1"
    assert views.format_money(mandate.limit) == "R$ 2.500,00"
    assert mandate.expires_at == datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)


def test_http_gateway_turns_transport_failure_into_a_gateway_error() -> None:
    def opener(request, timeout):  # noqa: ANN001 - urlopen shape
        raise OSError("connection refused")

    gateway = HttpGateway(make_config(AVAL_API_BASE_URL="http://api.local"), opener=opener)
    with pytest.raises(GatewayError):
        gateway.list_mandates()


# ── rendering ───────────────────────────────────────────────────────────────
def test_mandate_detail_shows_the_live_remainder_and_a_revoke_button() -> None:
    now = datetime.now(timezone.utc)
    mandate = MockGateway(now=now).get_mandate("mnd_marta_01")
    view = views.mandate_detail(mandate, now=now)
    assert "R$ 1.626,00" in view.text  # 2500,00 ceiling minus 874,00 spent
    assert any("Revogar" in label for row in view.buttons for label, _ in row)


def test_revoked_mandate_offers_no_revoke_button() -> None:
    gateway = MockGateway()
    gateway.revoke("mnd_marta_01", scope="mandate", reason="test", actor="t", idempotency_key="k")
    view = views.mandate_detail(gateway.get_mandate("mnd_marta_01"))
    assert all("Revogar" not in label for row in view.buttons for label, _ in row)


def test_telegram_api_builds_an_inline_keyboard() -> None:
    calls: list[tuple[str, dict]] = []
    api = TelegramApi("token")
    api.call = lambda method, payload, timeout=None: calls.append((method, payload)) or {}
    api.send_message(ALLOWED_CHAT, views.View("hi", ((("Aprovar", "apr:esc_1"),),)))
    method, payload = calls[0]
    assert method == "sendMessage"
    assert payload["reply_markup"] == {
        "inline_keyboard": [[{"text": "Aprovar", "callback_data": "apr:esc_1"}]]
    }


def test_mock_activity_records_the_human_decision() -> None:
    gateway = MockGateway()
    bot, _ = make_bot(gateway)
    bot.handle_update(callback("den:esc_be07"))
    assert gateway.activity()[0].event_type == "escalation.denied"


def test_expiry_is_reported_in_whole_days() -> None:
    now = datetime.now(timezone.utc)
    mandate = MockGateway(now=now).get_mandate("mnd_marta_02")
    assert mandate.expires_at - now == timedelta(days=6)
    assert "6 dia(s)" in views.mandate_detail(mandate, now=now).text
