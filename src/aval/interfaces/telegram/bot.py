"""Telegram long-polling runtime. Stdlib only.

The bot is a surface, never an authority: it renders what the gateway returns
and forwards human decisions back. It holds no policy, no balance and no
revocation state of its own.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any
import hashlib
import json
import logging
import os
import time
import urllib.error
import urllib.request

from aval.interfaces.telegram import views
from aval.interfaces.telegram.config import BotConfig
from aval.interfaces.telegram.gateway import AvalGateway, GatewayError, build_gateway
from aval.interfaces.telegram.views import View

logger = logging.getLogger("aval.telegram")

_API_ROOT = "https://api.telegram.org"


class TelegramError(Exception):
    def __init__(self, message: str, *, retry_after: int = 0) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class TelegramApi:
    """Minimal Bot API client: four methods is the whole surface we need."""

    def __init__(self, token: str, *, timeout: int = 10, opener: Any | None = None) -> None:
        self._token = token
        self._timeout = timeout
        self._opener = opener or urllib.request.urlopen

    def call(self, method: str, payload: Mapping[str, Any], *, timeout: int | None = None) -> Any:
        data = json.dumps(payload).encode()
        request = urllib.request.Request(
            f"{_API_ROOT}/bot{self._token}/{method}", data=data, method="POST"
        )
        request.add_header("Content-Type", "application/json")
        try:
            with self._opener(request, timeout=timeout or self._timeout) as response:
                body = json.loads(response.read())
        except urllib.error.HTTPError as error:
            raise TelegramError(
                f"{method} failed with {error.code}", retry_after=_retry_after(error)
            ) from error
        except OSError as error:
            raise TelegramError(f"{method} unreachable: {error}") from error
        if not body.get("ok"):
            raise TelegramError(f"{method} rejected: {body.get('description', 'unknown')}")
        return body.get("result")

    def get_updates(self, offset: int | None, *, timeout: int) -> Sequence[Mapping[str, Any]]:
        payload: dict[str, Any] = {"timeout": timeout, "allowed_updates": ["message", "callback_query"]}
        if offset is not None:
            payload["offset"] = offset
        return self.call("getUpdates", payload, timeout=timeout + self._timeout) or ()

    def send_message(self, chat_id: int, view: View) -> Mapping[str, Any]:
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": view.text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if view.buttons:
            payload["reply_markup"] = _keyboard(view.buttons)
        return self.call("sendMessage", payload)

    def edit_message(self, chat_id: int, message_id: int, view: View) -> None:
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": view.text,
            "parse_mode": "HTML",
            "reply_markup": _keyboard(view.buttons) if view.buttons else {"inline_keyboard": []},
        }
        self.call("editMessageText", payload)

    def answer_callback(self, callback_id: str, text: str = "") -> None:
        self.call("answerCallbackQuery", {"callback_query_id": callback_id, "text": text[:200]})


def _keyboard(rows: Iterable[views.Row]) -> dict[str, Any]:
    return {
        "inline_keyboard": [
            [{"text": label, "callback_data": data} for label, data in row] for row in rows
        ]
    }


def _retry_after(error: urllib.error.HTTPError) -> int:
    if error.code != 429:
        return 0
    try:
        return int(json.loads(error.read()).get("parameters", {}).get("retry_after", 1))
    except Exception:  # noqa: BLE001 - a malformed 429 body still means "back off"
        return 1


class Bot:
    def __init__(self, config: BotConfig, gateway: AvalGateway, api: TelegramApi) -> None:
        self._config = config
        self._gateway = gateway
        self._api = api
        self._notified: set[str] = set()

    # ── update handling ────────────────────────────────────────────────────
    def handle_update(self, update: Mapping[str, Any]) -> None:
        if "callback_query" in update:
            self._handle_callback(update["callback_query"])
        elif "message" in update:
            self._handle_message(update["message"])

    def _handle_message(self, message: Mapping[str, Any]) -> None:
        chat_id = int(message.get("chat", {}).get("id", 0))
        text = str(message.get("text", "")).strip()
        if not chat_id or not text.startswith("/"):
            return
        head, _, argument = text.partition(" ")
        command = head.split("@", 1)[0].lower()
        argument = argument.strip()

        if command == "/start":
            self._send(chat_id, views.welcome(
                chat_id=chat_id,
                allowed=self._config.may_act(chat_id),
                mock_mode=self._config.uses_mock_gateway,
            ))
            return
        if command in {"/meuid", "/chatid"}:
            self._send(chat_id, views.chat_id_view(chat_id))
            return
        if not self._config.may_act(chat_id):
            self._send(chat_id, views.denied())
            return

        try:
            self._send_all(chat_id, self._command_views(command, argument))
        except GatewayError as error:
            self._send(chat_id, views.unavailable(str(error)))

    def _command_views(self, command: str, argument: str) -> Sequence[View]:
        if command == "/ajuda" or command == "/help":
            return (views.help_text(),)
        if command == "/mandatos":
            return (views.mandate_list(self._gateway.list_mandates()),)
        if command == "/mandato":
            mandate = self._gateway.get_mandate(argument) if argument else None
            if mandate is None:
                return (View("Informe um id válido: <code>/mandato mnd_...</code>"),)
            return (views.mandate_detail(mandate),)
        if command in {"/aprovacoes", "/aprovações"}:
            return views.approval_list(self._gateway.list_pending_approvals())
        if command == "/atividade":
            return (views.activity_list(self._gateway.activity(argument or None)),)
        if command == "/revogar":
            mandate = self._gateway.get_mandate(argument) if argument else None
            if mandate is None:
                return (View("Informe um id válido: <code>/revogar mnd_...</code>"),)
            return (views.revoke_menu(mandate),)
        if command == "/status":
            return (
                views.status(
                    backend=self._gateway.health(),
                    mock_mode=self._config.uses_mock_gateway,
                    pending=len(self._gateway.list_pending_approvals()),
                ),
            )
        return (views.help_text(),)

    def _handle_callback(self, query: Mapping[str, Any]) -> None:
        callback_id = str(query.get("id", ""))
        message = query.get("message", {})
        chat_id = int(message.get("chat", {}).get("id", 0))
        message_id = int(message.get("message_id", 0))
        parsed = views.parse_callback(str(query.get("data", "")))
        if parsed is None or not chat_id:
            self._api.answer_callback(callback_id, "Ação inválida.")
            return
        verb, argument = parsed
        if not self._config.may_act(chat_id):
            self._api.answer_callback(callback_id, "Chat sem autoridade.")
            return

        actor = _actor(query, chat_id)
        try:
            view = self._callback_view(verb, argument, actor=actor, chat_id=chat_id)
        except GatewayError as error:
            self._api.answer_callback(callback_id, "AVAL indisponível.")
            self._send(chat_id, views.unavailable(str(error)))
            return
        self._api.answer_callback(callback_id)
        # Replacing the message retires its buttons, so a second tap cannot
        # re-ask; the idempotency key makes a replay harmless anyway.
        self._api.edit_message(chat_id, message_id, view)

    def _callback_view(self, verb: str, argument: str, *, actor: str, chat_id: int) -> View:
        key = _idempotency_key(verb, argument, chat_id)
        if verb == views.CALLBACK_MANDATE_LIST:
            return views.mandate_list(self._gateway.list_mandates())
        if verb == views.CALLBACK_MANDATE:
            mandate = self._gateway.get_mandate(argument)
            return views.mandate_detail(mandate) if mandate else View("Mandato não encontrado.")
        if verb == views.CALLBACK_REVOKE_MENU:
            mandate = self._gateway.get_mandate(argument)
            return views.revoke_menu(mandate) if mandate else View("Mandato não encontrado.")
        if verb in {views.CALLBACK_APPROVE, views.CALLBACK_DENY}:
            result = self._gateway.resolve_approval(
                argument,
                approve=verb == views.CALLBACK_APPROVE,
                actor=actor,
                idempotency_key=key,
            )
            return views.action_result(result)
        if verb == views.CALLBACK_REVOKE_MANDATE:
            result = self._gateway.revoke(
                argument, scope="mandate", reason="revoked_by_holder", actor=actor, idempotency_key=key
            )
            return views.action_result(result)
        if verb == views.CALLBACK_REVOKE_BUDGET:
            result = self._gateway.revoke(
                argument, scope="budget:zero", reason="budget_zeroed_by_holder", actor=actor, idempotency_key=key
            )
            return views.action_result(result)
        return View("Ação desconhecida.")

    # ── escalation push ────────────────────────────────────────────────────
    def push_pending_approvals(self) -> int:
        """Deliver approvals the human has not seen yet. Returns how many went out.

        ponytail: the seen-set is in memory, so a restart re-notifies whatever is
        still pending; persist it only if the bot starts restarting mid-demo.
        """
        try:
            pending = self._gateway.list_pending_approvals()
        except GatewayError as error:
            logger.warning("could not read pending approvals: %s", error)
            return 0
        sent = 0
        for approval in pending:
            if approval.id in self._notified:
                continue
            card = views.approval_card(approval)
            for chat_id in sorted(self._config.allowed_chat_ids):
                self._send(chat_id, card)
            self._notified.add(approval.id)
            sent += 1
        return sent

    # ── runtime ────────────────────────────────────────────────────────────
    def run(self) -> None:
        logger.info(
            "AVAL Telegram bot online (%s)",
            "mock gateway" if self._config.uses_mock_gateway else "backend gateway",
        )
        # ponytail: one update at a time, so a slow gateway call holds the next
        # ones. One human, one demo. A per-chat queue is the upgrade path.
        offset: int | None = None
        last_push = 0.0
        while True:
            try:
                updates = self._api.get_updates(offset, timeout=self._config.poll_timeout_seconds)
            except TelegramError as error:
                logger.warning("getUpdates failed: %s", error)
                time.sleep(max(error.retry_after, 3))
                continue
            for update in updates:
                offset = int(update["update_id"]) + 1
                try:
                    self.handle_update(update)
                except Exception:  # noqa: BLE001 - one bad update must not stop the bot
                    logger.exception("update %s failed", update.get("update_id"))
            if time.monotonic() - last_push >= self._config.escalation_poll_seconds:
                last_push = time.monotonic()
                try:
                    self.push_pending_approvals()
                except TelegramError as error:
                    logger.warning("could not push approvals: %s", error)

    # ── plumbing ───────────────────────────────────────────────────────────
    def _send(self, chat_id: int, view: View) -> None:
        self._api.send_message(chat_id, view)

    def _send_all(self, chat_id: int, all_views: Sequence[View]) -> None:
        for view in all_views:
            self._send(chat_id, view)


def _actor(query: Mapping[str, Any], chat_id: int) -> str:
    username = query.get("from", {}).get("username")
    return f"telegram:@{username}" if username else f"telegram:{chat_id}"


def _idempotency_key(verb: str, argument: str, chat_id: int) -> str:
    """Deterministic per decision, so a double tap can never act twice."""
    return hashlib.sha256(f"{verb}:{argument}:{chat_id}".encode()).hexdigest()[:32]


def build_bot(env: Mapping[str, str] | None = None) -> Bot:
    config = BotConfig.from_env(env if env is not None else os.environ)
    api = TelegramApi(config.token, timeout=config.request_timeout_seconds)
    return Bot(config, build_gateway(config), api)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    build_bot().run()
