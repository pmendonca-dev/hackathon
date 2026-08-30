"""Telegram long-polling runtime — the human surface of AVAL.

The bot is a surface, never an authority. It renders what the core answers and
carries back what the person decided, signed with that person's own key. Every
rule about money, scope and revocation lives in `AuthorizationCore`; none of it
is repeated here.

Each chat is its own holder: its own key, its own mandate. That is what lets a
room of judges share one bot without sharing any authority.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any
import json
import logging
import os
import time
import urllib.error
import urllib.request

from aval.interfaces.telegram import views
from aval.interfaces.telegram.config import BotConfig
from aval.interfaces.telegram.gateway import AvalGateway, GatewayError, MoneyView
from aval.interfaces.telegram.identity import ChatIdentity, IdentityStore
from aval.interfaces.telegram.views import View

logger = logging.getLogger("aval.telegram")

_API_ROOT = "https://api.telegram.org"


class TelegramError(Exception):
    def __init__(self, message: str, *, retry_after: int = 0) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class TelegramApi:
    """Minimal Bot API client: four methods are the whole surface we need."""

    def __init__(self, token: str, *, timeout: int = 15, opener: Any | None = None) -> None:
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
                f"{method} falhou com {error.code}", retry_after=_retry_after(error)
            ) from error
        except OSError as error:
            raise TelegramError(f"{method} inacessível: {error}") from error
        if not body.get("ok"):
            raise TelegramError(f"{method} recusado: {body.get('description', 'desconhecido')}")
        return body.get("result")

    def get_updates(self, offset: int | None, *, timeout: int) -> Sequence[Mapping[str, Any]]:
        payload: dict[str, Any] = {
            "timeout": timeout,
            "allowed_updates": ["message", "callback_query"],
        }
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
        self.call(
            "editMessageText",
            {
                "chat_id": chat_id,
                "message_id": message_id,
                "text": view.text,
                "parse_mode": "HTML",
                "reply_markup": _keyboard(view.buttons) if view.buttons else {"inline_keyboard": []},
            },
        )

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
    def __init__(
        self,
        config: BotConfig,
        gateway: AvalGateway,
        identities: IdentityStore,
        api: TelegramApi,
    ) -> None:
        self._config = config
        self._gateway = gateway
        self._identities = identities
        self._api = api
        self._notified: set[tuple[int, str]] = set()
        # Which reservations each chat actually bought. A dispute carries no
        # signature, so the core cannot tell a forged reservation id from a real
        # one — this is the only place that can.
        # ponytail: in memory, so a restart refuses dispute buttons from older
        # messages. Fail-closed, which is the right way to lose this state.
        # ponytail: the last unmet request per chat, in memory. A restart forgets it and
        # the person is asked to type again — the alternative is a standing order the
        # bot registered from something it could not show them.
        self._unmet: dict[int, str] = {}
        self._watched: set[str] = set()
        self._own_reservations: dict[int, set[str]] = {}

    # ── updates ────────────────────────────────────────────────────────────
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
        logger.info("%s de %s", command, chat_id)

        if command in {"/meuid", "/chatid"}:
            self._send(chat_id, views.chat_id_view(chat_id))
            return
        if not self._config.may_act(chat_id):
            self._send(chat_id, views.denied())
            return

        display_name = _display_name(message.get("from", {}), chat_id)
        try:
            for view in self._command_views(command, argument, chat_id, display_name):
                self._send(chat_id, view)
        except GatewayError as error:
            self._send(chat_id, views.unavailable(str(error), error.reason_code))

    def _command_views(
        self, command: str, argument: str, chat_id: int, display_name: str
    ) -> Sequence[View]:
        if command == "/start":
            return (self._start(chat_id, display_name),)
        if command in {"/ajuda", "/help"}:
            return (views.help_text(),)
        if command in {"/catalogo", "/catálogo"}:
            return (self._catalogue(chat_id),)
        if command == "/status":
            identity = self._identities.get(chat_id)
            pending = (
                len(self._gateway.open_escalations(identity.mandate_id))
                if identity and identity.mandate_id
                else 0
            )
            return (
                views.status(
                    backend=self._gateway.health(),
                    base_url=self._config.api_base_url,
                    open_mode=self._config.open_mode,
                    pending=pending,
                ),
            )

        identity = self._identities.get(chat_id)
        if identity is None or identity.mandate_id is None:
            return (views.no_mandate(),)
        mandate_id = identity.mandate_id
        # Having an id is not having a mandate. The store survives restarts and the
        # core does not have to: a reset database, an expiry purge or a fresh
        # environment leaves this chat pointing at something nobody has. Resolved once
        # here, so every command below fails the same readable way instead of five
        # different unreadable ones.
        mandate = self._gateway.mandate(mandate_id)
        if mandate is None:
            return (views.no_mandate(),)

        if command == "/mandato":
            return (views.mandate_card(mandate, self._gateway.open_watches(mandate_id)),)
        if command == "/extrato":
            return (views.receipt(self._gateway.receipt(mandate_id)),)
        if command in {"/aprovacoes", "/aprovações"}:
            return views.escalation_list(self._gateway.open_escalations(mandate_id))
        if command == "/revogar":
            return (views.revoke_menu(mandate),)
        if command == "/comprar":
            return self._purchase(identity, argument)
        if command == "/limite":
            return (self._replace_limit(identity, argument),)
        return (views.help_text(),)

    def _start(self, chat_id: int, display_name: str) -> View:
        """Enrol the person, mint their key, and issue a mandate that is theirs."""
        identity = self._identities.enrol(chat_id, display_name)
        if identity.mandate_id is not None:
            existing = self._gateway.mandate(identity.mandate_id)
            if existing is not None and existing.status == "ACTIVE":
                return views.mandate_card(existing)
        defaults = self._config.mandate_defaults
        mandate_id, instrument_scope = self._gateway.create_mandate(
            identity,
            merchants=defaults.merchants,
            categories=defaults.categories,
            limit=MoneyView(defaults.limit_minor_units, defaults.currency, defaults.scale),
            ceiling=(
                None
                if defaults.ceiling_minor_units is None
                else MoneyView(defaults.ceiling_minor_units, defaults.currency, defaults.scale)
            ),
            valid_for=defaults.valid_for,
            card_number=defaults.card_number,
        )
        # The scope is stored because the API never serves the instrument token back:
        # the only way to hold it is to have been told it once, here.
        self._identities.bind_mandate(chat_id, mandate_id, instrument_scope=instrument_scope)
        mandate = self._gateway.mandate(mandate_id)
        assert mandate is not None
        return views.welcome(display_name=identity.display_name, mandate=mandate)

    def _catalogue(self, chat_id: int) -> View:
        """Marked against the person's own mandate, so the limits are visible."""
        identity = self._identities.get(chat_id)
        mandate = (
            self._gateway.mandate(identity.mandate_id)
            if identity and identity.mandate_id
            else None
        )
        return views.catalogue(self._gateway.catalogue(), mandate=mandate)

    def _purchase(self, identity: ChatIdentity, instruction: str) -> Sequence[View]:
        if not instruction:
            return (views.plain("Diga o que comprar: /comprar um voo pra Córdoba"),)
        assert identity.mandate_id is not None
        result = self._gateway.purchase(identity.mandate_id, instruction)
        if result.outcome == "no_offer":
            # Not a dead end: the case's own scenario is a price that has not fallen
            # yet. Offered, never registered on its own — an agent that starts buying
            # without being told to is the silent approval the case forbids.
            mandate = self._gateway.mandate(identity.mandate_id)
            if mandate is not None:
                self._unmet[identity.chat_id] = instruction
                return (views.watch_offer(instruction, mandate),)
        if result.outcome == "needs_clarification":
            # One screen, not two: the question and the answers belong together.
            return (
                views.clarification(
                    result,
                    self._gateway.catalogue(),
                    mandate=self._gateway.mandate(identity.mandate_id),
                ),
            )
        screens: list[View] = [views.purchase_result(result)]
        if result.escalation_id:
            escalation = self._gateway.escalation(result.escalation_id)
            if escalation is not None:
                screens.append(views.escalation_card(escalation))
                # Already shown here, so the background push must not repeat it.
                self._notified.add((identity.chat_id, escalation.id))
        elif result.outcome == "settled":
            if result.reservation_id:
                self._own_reservations.setdefault(identity.chat_id, set()).add(
                    result.reservation_id
                )
            # A4: the person gets the record of what was bought, under which
            # mandate, and what is left — without having to ask for it.
            screens.append(views.receipt(self._gateway.receipt(identity.mandate_id)))
        return tuple(screens)

    def _replace_limit(self, identity: ChatIdentity, argument: str) -> View:
        assert identity.mandate_id is not None
        defaults = self._config.mandate_defaults
        limit = views.parse_money(argument, currency=defaults.currency, scale=defaults.scale)
        if limit is None:
            return views.plain("Informe um valor positivo: /limite 100")
        message = self._gateway.replace_limit(identity, identity.mandate_id, limit)
        return views.signed_note("Limite alterado", message)

    # ── buttons ────────────────────────────────────────────────────────────
    def _handle_callback(self, query: Mapping[str, Any]) -> None:
        callback_id = str(query.get("id", ""))
        message = query.get("message", {})
        chat_id = int(message.get("chat", {}).get("id", 0))
        message_id = int(message.get("message_id", 0))
        parsed = views.parse_callback(str(query.get("data", "")))
        if parsed is None or not chat_id:
            self._api.answer_callback(callback_id, "Ação inválida.")
            return
        if not self._config.may_act(chat_id):
            self._api.answer_callback(callback_id, "Chat sem autoridade.")
            return
        identity = self._identities.get(chat_id)
        if identity is None:
            self._api.answer_callback(callback_id, "Mande /start primeiro.")
            return
        verb, argument = parsed
        logger.info("botao %s de %s", verb, chat_id)
        try:
            screens = self._callback_view(verb, argument, identity)
        except GatewayError as error:
            self._api.answer_callback(callback_id, "AVAL indisponível.")
            self._send(chat_id, views.unavailable(str(error), error.reason_code))
            return
        self._api.answer_callback(callback_id)
        # The first screen replaces the message, which retires its buttons so a
        # second tap cannot re-ask. Anything further arrives as a new message.
        self._api.edit_message(chat_id, message_id, screens[0])
        for extra in screens[1:]:
            self._send(chat_id, extra)

    def _callback_view(
        self, verb: str, argument: str, identity: ChatIdentity
    ) -> Sequence[View]:
        if verb in {views.CALLBACK_APPROVE, views.CALLBACK_DENY}:
            escalation = self._gateway.escalation(argument)
            if escalation is None:
                return (views.plain("Escalação não encontrada."),)
            if not self._owns(identity, escalation.mandate_id):
                return (views.plain("Essa escalação não é do seu mandato."),)
            approve = verb == views.CALLBACK_APPROVE
            message = self._gateway.decide(identity, escalation, approve=approve)
            return (views.signed_note("Aprovado" if approve else "Recusado", message),)

        if verb == views.CALLBACK_CATALOGUE:
            return (self._catalogue(identity.chat_id),)

        if verb == views.CALLBACK_BUY:
            if identity.mandate_id is None:
                return (views.no_mandate(),)
            wish = views.wish_for(self._gateway.catalogue(), argument)
            if wish is None:
                return (views.plain("Essa opção saiu do catálogo."),)
            # Deliberately routed through the agent's own free-text path: a button
            # that called capture directly would be a second way to buy that skips
            # the agent, which is exactly what the architecture forbids. The button
            # says what the person wants; the agent still picks which offer.
            return self._purchase(identity, wish.instruction)

        if verb == views.CALLBACK_WATCH:
            if not self._owns(identity, argument):
                return (views.plain("Esse mandato não é seu."),)
            instruction = self._unmet.get(identity.chat_id)
            if instruction is None:
                return (views.plain("Peça de novo o que quer, e eu ofereço vigiar."),)
            watch = self._gateway.register_watch(argument, instruction)
            self._unmet.pop(identity.chat_id, None)
            return (views.watch_registered(watch),)

        if verb == views.CALLBACK_DISPUTE:
            if argument not in self._own_reservations.get(identity.chat_id, set()):
                return (views.plain("Essa compra não é sua."),)
            message = self._gateway.open_dispute(
                identity, argument, "titular não reconhece a compra (aberta pelo Telegram)"
            )
            return (views.plain(f"⚠️ {message} A trilha do mandato é quem responde."),)

        if not self._owns(identity, argument):
            return (views.plain("Esse mandato não é seu."),)
        if verb == views.CALLBACK_MANDATE:
            mandate = self._gateway.mandate(argument)
            if mandate is None:
                return (views.no_mandate(),)
            return (views.mandate_card(mandate, self._gateway.open_watches(argument)),)
        if verb == views.CALLBACK_RECEIPT:
            return (views.receipt(self._gateway.receipt(argument)),)
        if verb == views.CALLBACK_CARD_MENU:
            mandate = self._gateway.mandate(argument)
            if mandate is None or mandate.instrument_label is None:
                return (views.plain("Esse mandato não tem cartão para cancelar."),)
            return (views.cancel_card_menu(mandate),)
        if verb == views.CALLBACK_CARD_CONFIRM:
            mandate = self._gateway.mandate(argument)
            if mandate is None:
                return (views.no_mandate(),)
            if identity.instrument_scope is None:
                # Without the scope there is nothing to sign, and the bot must not
                # invent one: a guessed scope is a signature over the wrong thing.
                return (views.plain("Não tenho o escopo do cartão deste mandato."),)
            message = self._gateway.cancel_instrument(
                identity,
                argument,
                scope=identity.instrument_scope,
                epoch=mandate.revocation_epoch,
            )
            return (views.signed_note("Cartão cancelado", message),)
        if verb == views.CALLBACK_REVOKE_MENU:
            mandate = self._gateway.mandate(argument)
            return (views.revoke_menu(mandate) if mandate else views.no_mandate(),)
        if verb == views.CALLBACK_REVOKE_CONFIRM:
            mandate = self._gateway.mandate(argument)
            if mandate is None:
                return (views.no_mandate(),)
            message = self._gateway.revoke(
                identity,
                argument,
                epoch=mandate.revocation_epoch,
                reason="revogado pelo titular no Telegram",
            )
            return (views.signed_note("Mandato revogado", message),)
        return (views.help_text(),)

    @staticmethod
    def _owns(identity: ChatIdentity, mandate_id: str) -> bool:
        """The button says what to act on; ownership says whether it may.

        Callback data is client input, so a crafted tap could name a neighbour's
        mandate. The core would refuse it anyway — the signature would not match
        — but refusing here keeps one judge from ever seeing another's numbers.
        """
        return identity.mandate_id == mandate_id

    # ── escalation push ────────────────────────────────────────────────────
    def push_pending_approvals(self) -> int:
        """Deliver escalations each person has not seen yet.

        ponytail: the seen-set is in memory, so a restart re-notifies whatever is
        still open. Harmless — the card is idempotent, and the core decides once.
        """
        sent = 0
        for chat_id in self._identities.known_chats():
            identity = self._identities.get(chat_id)
            if identity is None or identity.mandate_id is None:
                continue
            try:
                pending = self._gateway.open_escalations(identity.mandate_id)
            except GatewayError as error:
                if error.reason_code == "mandate_not_found":
                    # Not a fault to report every thirty seconds. The chat is pointing
                    # at a mandate the core does not have, and `/start` is the answer.
                    continue
                logger.warning("escalações de %s: %s", chat_id, error)
                continue
            for escalation in pending:
                seen = (chat_id, escalation.id)
                if seen in self._notified:
                    continue
                self._send(chat_id, views.escalation_card(escalation))
                self._notified.add(seen)
                sent += 1
        return sent

    def push_watch_results(self) -> int:
        """Let every standing order try once, and report what it did.

        This is the only place the system acts with nobody at the keyboard, which is
        the case's actual premise. It reports refusals as loudly as purchases: an agent
        that only announced its wins would hide the half the mandate exists for.
        """
        delivered = 0
        for chat_id in self._identities.known_chats():
            identity = self._identities.get(chat_id)
            if identity is None or identity.mandate_id is None:
                continue
            try:
                fired = self._gateway.tick_watches(identity.mandate_id)
            except GatewayError as error:
                if error.reason_code != "mandate_not_found":
                    logger.warning("vigílias de %s: %s", chat_id, error)
                continue
            for watch in fired:
                if watch.id in self._watched:
                    continue
                self._send(chat_id, views.watch_fired(watch))
                self._watched.add(watch.id)
                if watch.purchase is not None and watch.purchase.reservation_id:
                    self._own_reservations.setdefault(chat_id, set()).add(
                        watch.purchase.reservation_id
                    )
                delivered += 1
        return delivered

    # ── runtime ────────────────────────────────────────────────────────────
    def run(self) -> None:
        logger.info(
            "AVAL Telegram bot online · núcleo em %s · modo %s",
            self._config.api_base_url,
            "aberto" if self._config.open_mode else "lista de autorizados",
        )
        # ponytail: one update at a time, so a slow call holds the next ones. One
        # human per chat, one demo. A per-chat queue is the upgrade path.
        offset: int | None = None
        last_push = 0.0
        while True:
            try:
                updates = self._api.get_updates(offset, timeout=self._config.poll_timeout_seconds)
            except TelegramError as error:
                logger.warning("getUpdates falhou: %s", error)
                time.sleep(max(error.retry_after, 3))
                continue
            for update in updates:
                offset = int(update["update_id"]) + 1
                try:
                    self.handle_update(update)
                except Exception:  # noqa: BLE001 - one bad update must not stop the bot
                    logger.exception("update %s falhou", update.get("update_id"))
            if time.monotonic() - last_push >= self._config.escalation_poll_seconds:
                last_push = time.monotonic()
                try:
                    self.push_pending_approvals()
                    self.push_watch_results()
                except TelegramError as error:
                    logger.warning("push de escalações falhou: %s", error)

    def _send(self, chat_id: int, view: View) -> None:
        self._api.send_message(chat_id, view)


def _display_name(sender: Mapping[str, Any], chat_id: int) -> str:
    first = str(sender.get("first_name", "")).strip()
    last = str(sender.get("last_name", "")).strip()
    full = " ".join(part for part in (first, last) if part)
    return full or f"Titular {chat_id}"


def build_bot(env: Mapping[str, str] | None = None) -> Bot:
    config = BotConfig.from_env(env if env is not None else os.environ)
    identities = IdentityStore(config.identity_path)
    gateway = AvalGateway(
        config.api_base_url, identities=identities, timeout=config.request_timeout_seconds
    )
    api = TelegramApi(config.token, timeout=config.request_timeout_seconds)
    return Bot(config, gateway, identities, api)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    try:
        build_bot().run()
    except KeyboardInterrupt:
        # Ctrl+C is how the bot is meant to be stopped, not a crash to report.
        logger.info("bot encerrado")
