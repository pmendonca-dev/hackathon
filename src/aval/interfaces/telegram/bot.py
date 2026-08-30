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
from datetime import timedelta
from typing import Any
import json
import logging
import os
import queue
import threading
import time
import urllib.error
import urllib.request

from aval.interfaces.telegram import conversation, views
from aval.interfaces.telegram.config import BotConfig
from aval.interfaces.telegram.conversation import SpecTalker, Turn, build_talker
from aval.interfaces.telegram.gateway import AvalGateway, GatewayError, MandateView, MoneyView
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
        talker: SpecTalker | None = None,
    ) -> None:
        self._config = config
        self._gateway = gateway
        self._identities = identities
        self._api = api
        self._talker = talker or build_talker()
        self._notified: set[tuple[int, str]] = set()
        # ponytail: the last unmet request per chat, in memory. A restart forgets it and
        # the person is asked to type again — the alternative is a standing order the
        # bot registered from something it could not show them.
        self._unmet: dict[int, str] = {}
        self._watched: set[str] = set()
        # One inbox and one thread per chat. Serial within a chat, because a person's
        # own messages have to be answered in the order they sent them; parallel
        # across chats, because a room of judges is several people, and a purchase
        # that takes seconds must not be the reason someone else's tap is ignored.
        # ponytail: threads are never reaped — one per chat that ever spoke, parked on
        # an empty queue. Fine for a demo; a pool with idle timeouts if it outlives one.
        self._inboxes: dict[int, queue.Queue] = {}
        self._inboxes_lock = threading.Lock()
        # ponytail: the mandate each chat described but has not confirmed yet, in
        # memory. A restart forgets it and the person types the sentence again —
        # which beats issuing a mandate from words the bot can no longer show them.
        self._pending_spec: dict[int, views.MandateSpec] = {}
        # ponytail: the card page each chat has open, in memory. A restart forgets it
        # and /cartao opens a new one — the card itself is safe at the processor either
        # way, so the worst a restart costs is one abandoned form.
        self._card_session: dict[int, str] = {}
        # ponytail: the conversation each chat is having, in memory and trimmed. A
        # restart forgets it and the person restates what they want — which is the
        # right way to lose a draft nobody signed.
        self._history: dict[int, list[Turn]] = {}

    # ── updates ────────────────────────────────────────────────────────────
    def dispatch(self, update: Mapping[str, Any]) -> None:
        """Hand the update to its own chat's worker and go back to polling."""
        chat_id = _chat_of(update)
        if chat_id is None:
            return
        with self._inboxes_lock:
            inbox = self._inboxes.get(chat_id)
            if inbox is None:
                inbox = self._inboxes[chat_id] = queue.Queue()
                threading.Thread(
                    target=self._drain, args=(chat_id, inbox), daemon=True, name=f"chat-{chat_id}"
                ).start()
        inbox.put(update)

    def _drain(self, chat_id: int, inbox: "queue.Queue") -> None:
        while True:
            update = inbox.get()
            try:
                self.handle_update(update)
            except Exception:  # noqa: BLE001 - one bad update must not kill a chat
                logger.exception("update %s de %s falhou", update.get("update_id"), chat_id)

    def handle_update(self, update: Mapping[str, Any]) -> None:
        if "callback_query" in update:
            self._handle_callback(update["callback_query"])
        elif "message" in update:
            self._handle_message(update["message"])

    def _handle_message(self, message: Mapping[str, Any]) -> None:
        chat_id = int(message.get("chat", {}).get("id", 0))
        text = str(message.get("text", "")).strip()
        if not chat_id or not text:
            return
        if not text.startswith("/"):
            self._reply(chat_id, text)
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

    def _reply(self, chat_id: int, text: str) -> None:
        """Answer plain words, and always land on something signable.

        The model converses; it never grants. Every path out of here is either a
        question in the chat or a spec drawn in full with a confirm button — and
        the button is where the person's own key finally signs.
        """
        if not self._config.may_act(chat_id):
            self._send(chat_id, views.denied())
            return
        identity = self._identities.get(chat_id)
        if identity is None:
            self._send(chat_id, views.no_mandate())
            return
        history = self._history.setdefault(chat_id, [])
        history.append(Turn("user", text))
        del history[:-conversation.HISTORY_LIMIT]
        try:
            categories = sorted({offer.category for offer in self._gateway.catalogue()})
            draft = self._talker.respond(
                history, categories=categories, defaults=self._config.mandate_defaults
            )
            history.append(Turn("assistant", draft.reply))
            self._send(chat_id, views.plain(draft.reply))
            if draft.spec is None:
                return
            self._pending_spec[chat_id] = draft.spec
            current = (
                self._gateway.mandate(identity.mandate_id)
                if identity.mandate_id is not None
                else None
            )
            self._send(chat_id, views.new_mandate_preview(draft.spec, current))
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
        if command == "/agente":
            identity = self._identities.get(chat_id)
            return (
                views.agent_card(
                    self._gateway.agent_profile(),
                    holder_name=identity.display_name if identity else display_name,
                    holder_kid=identity.kid if identity else "—",
                    principal_id=identity.principal_id if identity else "—",
                ),
            )
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
        if command == "/cartao" or command == "/cartão":
            return self._register_card(identity, mandate)
        if command == "/novo":
            return (self._describe_mandate(identity, mandate, argument),)
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
            # No card. A mandate is authority to spend, and the means of payment is
            # the person's to provide — /cartao is where they do. Emitting one from the
            # environment was the system deciding, on their behalf, what pays.
            max_uses=defaults.max_uses,
            usage_window=defaults.usage_window,
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
                # Written to the identity store, not to memory: the person who denies
                # a purchase tomorrow must still be recognised as the one who made it.
                self._identities.record_reservation(identity.chat_id, result.reservation_id)
            # A4: the person gets the record of what was bought, under which
            # mandate, and what is left — without having to ask for it.
            screens.append(views.receipt(self._gateway.receipt(identity.mandate_id)))
        return tuple(screens)

    def _register_card(
        self, identity: ChatIdentity, mandate: "MandateView"
    ) -> Sequence[View]:
        """Hand out the processor's card form, or pick up the card left on it.

        One command does both halves because the person only has one thing in mind.
        The first /cartao opens the page; the next one asks the processor whether a
        card is sitting there, and binds it if so.
        """
        assert identity.mandate_id is not None
        session_id = self._card_session.get(identity.chat_id)
        if session_id is not None:
            card = self._gateway.read_card_session(identity, identity.mandate_id, session_id)
            if card is None:
                return (views.card_pending(),)
            token, label = card
            self._gateway.bind_instrument(
                identity,
                identity.mandate_id,
                token=token,
                label=label,
                # The card bound right now, from the revocation scope the bot was told
                # once. The API never serves the token back — a client that could read
                # it could present it — so this is the only place that holds it. A bot
                # that does not have it signs `None` and the core refuses the binding
                # as stale, which is the right way to fail.
                supersedes=(
                    None
                    if identity.instrument_scope is None
                    else identity.instrument_scope.removeprefix("instrument:")
                ),
            )
            # Remember the new scope, or the next card change cannot be signed and this
            # card cannot be cancelled.
            self._identities.bind_mandate(
                identity.chat_id, identity.mandate_id, instrument_scope=f"instrument:{token}"
            )
            self._card_session.pop(identity.chat_id, None)
            replaced = mandate.instrument_label is not None
            refreshed = self._gateway.mandate(identity.mandate_id)
            screens: list[View] = [views.card_bound(label, replaced=replaced)]
            if refreshed is not None:
                screens.append(views.mandate_card(refreshed))
            return tuple(screens)
        session = self._gateway.open_card_session(identity, identity.mandate_id)
        self._card_session[identity.chat_id] = session.session_id
        return (views.card_form(session),)

    def _describe_mandate(
        self, identity: ChatIdentity, current: "MandateView", argument: str
    ) -> View:
        """The case's first line: the person says what, how much and until when.

        Nothing is issued from the sentence alone. Replacing a mandate revokes the one
        in force, so it goes through a confirmation the same way a revocation does.
        """
        spec = views.parse_mandate_spec(argument, defaults=self._config.mandate_defaults)
        if spec is None:
            return views.plain(
                "Diga o que o agente pode fazer: /novo hotel até 300 por 7 dias, 2x"
            )
        self._pending_spec[identity.chat_id] = spec
        return views.new_mandate_preview(spec, current)

    def _issue_mandate(self, identity: ChatIdentity, spec: views.MandateSpec) -> Sequence[View]:
        """Revoke what is in force, then grant what was described.

        Changing what an agent may buy is withdrawing authority and granting other
        authority — both signed by the holder, both on the ledger, in that order. A
        mandate quietly edited underneath a running agent would be neither.
        """
        screens: list[View] = []
        current = (
            self._gateway.mandate(identity.mandate_id)
            if identity.mandate_id is not None
            else None
        )
        if current is not None and current.status == "ACTIVE":
            message = self._gateway.revoke(
                identity,
                current.id,
                epoch=current.revocation_epoch,
                reason="substituído por um novo mandato do titular",
            )
            screens.append(views.signed_note("Mandato anterior revogado", message))
        defaults = self._config.mandate_defaults
        mandate_id, instrument_scope = self._gateway.create_mandate(
            identity,
            merchants=defaults.merchants,
            categories=spec.categories,
            limit=spec.limit,
            ceiling=(
                None
                if defaults.ceiling_minor_units is None
                else MoneyView(defaults.ceiling_minor_units, defaults.currency, defaults.scale)
            ),
            valid_for=timedelta(days=spec.valid_for_days),
            max_uses=spec.max_uses,
            usage_window=defaults.usage_window,
        )
        self._identities.bind_mandate(
            identity.chat_id, mandate_id, instrument_scope=instrument_scope
        )
        mandate = self._gateway.mandate(mandate_id)
        if mandate is None:
            return (*screens, views.no_mandate())
        return (*screens, views.mandate_card(mandate))

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

        if verb == views.CALLBACK_NEW_CONFIRM:
            spec = self._pending_spec.pop(identity.chat_id, None)
            self._history.pop(identity.chat_id, None)
            if spec is None:
                return (views.plain("Descreva o mandato de novo: /novo hotel até 300 por 7 dias"),)
            return self._issue_mandate(identity, spec)

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
            if not self._identities.owns_reservation(identity.chat_id, argument):
                return (views.plain("Essa compra não é sua."),)
            dispute = self._gateway.open_dispute(
                identity, argument, "titular não reconhece a compra (aberta pelo Telegram)"
            )
            # The verdict comes back in the same tap: the resolution reads the ledger
            # and asks nobody, so making the person wait for it would be theatre.
            return (views.dispute_verdict(dispute),)

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
                    self._identities.record_reservation(chat_id, watch.purchase.reservation_id)
                delivered += 1
        return delivered

    # ── runtime ────────────────────────────────────────────────────────────
    def run(self) -> None:
        logger.info(
            "AVAL Telegram bot online · núcleo em %s · modo %s",
            self._config.api_base_url,
            "aberto" if self._config.open_mode else "lista de autorizados",
        )
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
                self.dispatch(update)
            if time.monotonic() - last_push >= self._config.escalation_poll_seconds:
                last_push = time.monotonic()
                try:
                    self.push_pending_approvals()
                    self.push_watch_results()
                except TelegramError as error:
                    logger.warning("push de escalações falhou: %s", error)

    def _send(self, chat_id: int, view: View) -> None:
        self._api.send_message(chat_id, view)


def _chat_of(update: Mapping[str, Any]) -> int | None:
    """Which conversation this update belongs to — the only routing key there is."""
    message = update.get("message") or (update.get("callback_query") or {}).get("message") or {}
    chat_id = int((message.get("chat") or {}).get("id", 0))
    return chat_id or None


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
