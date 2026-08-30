"""Pure rendering: gateway data in, message text and buttons out.

Nothing here performs I/O or decides anything, so every screen the judges will
touch is testable without a token, a network or a server. Reason codes are shown
next to the core's own `human_summary` and never rewritten — the bot repeats what
the core decided, it does not paraphrase it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from html import escape
import re
import unicodedata

from aval.interfaces.telegram.gateway import (
    ChainView,
    DisputeView,
    EscalationView,
    WatchView,
    OfferView,
    MandateView,
    MoneyView,
    PurchaseView,
    ReceiptView,
)

Button = tuple[str, str]
Row = tuple[Button, ...]

# Telegram caps callback data at 64 bytes, so verbs stay at three characters.
CALLBACK_APPROVE = "apr"
CALLBACK_DENY = "den"
CALLBACK_MANDATE = "mnd"
CALLBACK_RECEIPT = "rec"
CALLBACK_REVOKE_MENU = "rvk"
CALLBACK_REVOKE_CONFIRM = "rvm"
CALLBACK_DISPUTE = "dsp"
CALLBACK_WATCH = "wat"
CALLBACK_CARD_MENU = "crd"
CALLBACK_CARD_CONFIRM = "crm"
CALLBACK_CATALOGUE = "cat"
CALLBACK_BUY = "buy"

_VERBS = frozenset(
    {
        CALLBACK_APPROVE,
        CALLBACK_DENY,
        CALLBACK_MANDATE,
        CALLBACK_RECEIPT,
        CALLBACK_REVOKE_MENU,
        CALLBACK_REVOKE_CONFIRM,
        CALLBACK_DISPUTE,
        CALLBACK_CATALOGUE,
        CALLBACK_BUY,
        CALLBACK_CARD_MENU,
        CALLBACK_CARD_CONFIRM,
        CALLBACK_WATCH,
    }
)

_STATUS_BADGE = {"ACTIVE": "🟢", "REVOKED": "🔴", "EXPIRED": "⚫"}
_SYMBOL = {"BRL": "R$", "USD": "US$", "EUR": "€"}


@dataclass(frozen=True)
class View:
    text: str
    buttons: tuple[Row, ...] = ()


def format_money(amount: MoneyView) -> str:
    """Integer arithmetic only. Money never becomes a float, not even to print."""
    sign = "-" if amount.minor_units < 0 else ""
    whole, fraction = divmod(abs(amount.minor_units), 10**amount.scale)
    grouped = f"{whole:,}".replace(",", ".")
    symbol = _SYMBOL.get(amount.currency, amount.currency)
    if amount.scale == 0:
        return f"{sign}{symbol} {grouped}"
    return f"{sign}{symbol} {grouped},{fraction:0{amount.scale}d}"


def parse_money(raw: str, *, currency: str, scale: int) -> MoneyView | None:
    """Read what a person typed. No float ever touches the amount."""
    cleaned = raw.strip().replace(_SYMBOL.get(currency, currency), "").strip()
    cleaned = cleaned.replace(".", "").replace(",", ".") if "," in cleaned else cleaned
    if not cleaned:
        return None
    whole, _, decimals = cleaned.partition(".")
    if not whole.isdigit() or (decimals and not decimals.isdigit()):
        return None
    decimals = (decimals + "0" * scale)[:scale]
    minor = int(whole) * 10**scale + (int(decimals) if decimals else 0)
    return MoneyView(minor, currency, scale) if minor > 0 else None


def parse_callback(data: str) -> tuple[str, str] | None:
    """Callback data comes from a client; treat it as untrusted input."""
    if not data or len(data) > 64:
        return None
    verb, _, argument = data.partition(":")
    if verb not in _VERBS:
        return None
    if verb == CALLBACK_CATALOGUE:
        return verb, ""
    if not argument:
        return None
    if not all(char.isalnum() or char in "_-" for char in argument):
        return None
    return verb, argument


# ── screens ─────────────────────────────────────────────────────────────────
def welcome(*, display_name: str, mandate: MandateView) -> View:
    """Lead with what to do next.

    The mandate details matter, but they are not an instruction. Someone arriving
    for the first time needs the next move to be obvious and one tap away.
    """
    lines = [
        f"<b>AVAL</b> — olá, {escape(display_name)}.",
        "",
        "Você acabou de ganhar um <b>agente de compras</b>. Ele compra sozinho,",
        "mas só até onde você autorizou — e você pode cortar a qualquer momento.",
        "",
        "<b>👉 Toque em «Ver o que posso comprar» para começar.</b>",
        "",
        "Ou peça em português: <code>/comprar um voo pra Córdoba</code>",
        "",
        "─────────────",
        "<b>Seu mandato</b>, assinado com a sua chave:",
        _mandate_body(mandate),
    ]
    return View("\n".join(lines), _mandate_buttons(mandate, primary=True))


def mandate_card(mandate: MandateView, watches: Sequence[WatchView] = ()) -> View:
    """The mandate, plus anything armed to fire without being asked.

    A standing order is authority the person granted once and can no longer see.
    Listing it here is what keeps it from becoming invisible authority.
    """
    body = _mandate_body(mandate)
    if watches:
        body += "\n\n\U0001f440 <b>Vigiando</b>\n" + "\n".join(
            f"· <i>{escape(watch.instruction)}</i>" for watch in watches
        )
    return View(body, _mandate_buttons(mandate))


def _mandate_body(mandate: MandateView) -> str:
    badge = _STATUS_BADGE.get(mandate.status, "⚪")
    days = max((mandate.expires_at - datetime.now(UTC)).days, 0)
    lines = [
        f"{badge} <b>{escape(mandate.status)}</b> · <code>{escape(mandate.id[:20])}</code>",
        f"Orçamento: <b>{format_money(mandate.remaining)}</b> livres de {format_money(mandate.limit)}",
    ]
    if mandate.ceiling is not None:
        lines.append(f"Teto por compra: {format_money(mandate.ceiling)} — <i>ninguém atravessa</i>")
    if mandate.max_uses is not None:
        # Frequency reads as authority, not as a counter: what is left, and over what
        # window. The core escalates the use past this — it is not a wall, it is a
        # point where the person is asked again.
        left = max(mandate.max_uses - mandate.uses_in_window, 0)
        lines.append(
            f"Frequência: <b>{left} de {mandate.max_uses}</b> compra(s) livres "
            f"{_window_label(mandate.window_seconds)}"
        )
    if mandate.instrument_label is not None:
        # The fourth thing the mandate authorizes, next to the other three. The
        # agent holds a token for it and never the number. Once cancelled the label
        # stays — the holder still needs to know which card it was — but the line
        # stops claiming the mandate can pay, because it cannot.
        card = escape(mandate.instrument_label)
        lines.append(
            f"Cartão: <b>{card}</b> — \U0001f534 <b>cancelado</b>, nada pode ser pago"
            if mandate.instrument_revoked
            else f"Paga com: <b>{card}</b>"
        )
    lines += [
        f"Pode comprar: {escape(', '.join(mandate.categories))} em {escape(', '.join(mandate.merchants))}",
        f"Vence em {days} dia(s) · política v{mandate.policy_version} · epoch {mandate.revocation_epoch}",
    ]
    return "\n".join(lines)


def _window_label(window_seconds: int | None) -> str:
    """`2592000` becomes `nos últimos 30 dias` — a person counts in days, not seconds."""
    if not window_seconds:
        return "na janela do mandato"
    days = window_seconds // 86_400
    if days >= 1:
        return f"nos últimos {days} dia(s)"
    return f"nas últimas {max(window_seconds // 3_600, 1)} hora(s)"


def _mandate_buttons(mandate: MandateView, *, primary: bool = False) -> tuple[Row, ...]:
    """Buying is the point; the rest is housekeeping, so it comes first."""
    rows: list[Row] = []
    if mandate.status == "ACTIVE":
        rows.append((("🛒 Ver o que posso comprar", f"{CALLBACK_CATALOGUE}:_"),))
    rows.append(
        (
            ("🔄 Atualizar", f"{CALLBACK_MANDATE}:{mandate.id}"),
            ("🧾 Extrato", f"{CALLBACK_RECEIPT}:{mandate.id}"),
        )
    )
    if mandate.status == "ACTIVE":
        # Two different things end here, so they are two different buttons: the
        # card stops the money, the revocation stops the authority.
        if mandate.instrument_label is not None and not mandate.instrument_revoked:
            rows.append(
                (("💳 Cancelar o cartão", f"{CALLBACK_CARD_MENU}:{mandate.id}"),)
            )
        label = "🛑 Revogar a autoridade" if primary else "🛑 Revogar"
        rows.append(((label, f"{CALLBACK_REVOKE_MENU}:{mandate.id}"),))
    return tuple(rows)


def _why(result: PurchaseView) -> str:
    """The agent's reasoning, credited to whoever did it.

    It is shown next to the outcome and never instead of it: the reason explains the
    proposal, and the line above it is what the mandate did with that proposal.
    """
    if not result.rationale:
        return ""
    who = "🤖 O agente escolheu" if result.proposed_by == "llm" else "⚙️ Escolha por regra"
    return f"\n\n<b>{who}:</b> <i>{escape(result.rationale)}</i>"


def purchase_result(result: PurchaseView) -> View:
    """Four outcomes, four different things to say. Never a silent approval."""
    what = escape(result.title or "—")
    price = f" — <b>{format_money(result.amount)}</b>" if result.amount else ""
    buttons: tuple[Row, ...] = ()
    if result.outcome == "settled":
        head = f"✅ <b>Comprado.</b>\n{what}{price}"
        tail = f"\nReferência: <code>{escape(result.settlement_reference or '—')}</code>"
        if result.reservation_id:
            # The bonus the case asks for: a purchase can be denied later, and the
            # trail — not anyone's word — is what answers it.
            buttons = (
                (("⚠️ Não reconheço esta compra", f"{CALLBACK_DISPUTE}:{result.reservation_id}"),),
            )
    elif result.outcome == "awaiting_human":
        head = f"🟡 <b>Precisa de você.</b>\n{what}{price}"
        tail = "\nO agente parou aqui. Decida abaixo."
    elif result.outcome == "needs_clarification":
        # Answered by the catalogue screen, which carries the buttons. This branch
        # exists so a caller that renders only the result still says the right thing.
        head = "\U0001f914 <b>Preciso saber mais.</b>"
        tail = ""
    elif result.outcome == "no_offer":
        head = "🔍 <b>Nada no catálogo atende.</b>"
        tail = "\nVeja /catalogo e tente com outras palavras."
    else:
        head = f"⛔ <b>Recusado.</b>\n{what}{price}"
        tail = ""
    return View(
        f"{head}\n\n{escape(result.human_summary)}\n<i>{escape(result.reason_code)}</i>{tail}",
        buttons,
    )


def escalation_card(escalation: EscalationView) -> View:
    return View(
        "\n".join(
            [
                "🟡 <b>Aprovação necessária</b>",
                "",
                f"<b>{format_money(escalation.amount)}</b> em {escape(escalation.merchant)}"
                f" · {escape(escalation.category)}",
                f"Handle: <code>{escape(escalation.id)}</code>",
                "",
                f"<i>{escape(escalation.reason_code)}</i>",
                "Sua decisão vai assinada com a sua chave.",
            ]
        ),
        (
            (
                ("✅ Aprovar", f"{CALLBACK_APPROVE}:{escalation.id}"),
                ("❌ Recusar", f"{CALLBACK_DENY}:{escalation.id}"),
            ),
        ),
    )


def escalation_list(escalations: Sequence[EscalationView]) -> tuple[View, ...]:
    if not escalations:
        return (View("Nada aguardando você. 🟢"),)
    return tuple(escalation_card(item) for item in escalations)


def revoke_menu(mandate: MandateView) -> View:
    return View(
        "\n".join(
            [
                "🛑 <b>Revogar o mandato?</b>",
                "",
                "É irreversível e vale a partir da próxima decisão do núcleo.",
                "Compras já liquidadas não são desfeitas — a autoridade acaba, o histórico fica.",
            ]
        ),
        (
            (("🛑 Revogar agora", f"{CALLBACK_REVOKE_CONFIRM}:{mandate.id}"),),
            (("← Voltar", f"{CALLBACK_MANDATE}:{mandate.id}"),),
        ),
    )


def cancel_card_menu(mandate: MandateView) -> View:
    """Ending the card is not ending the agent, and the screen has to say so."""
    return View(
        "\n".join(
            [
                f"💳 <b>Cancelar {escape(mandate.instrument_label or 'o cartão')}?</b>",
                "",
                "O <b>mandato continua ativo</b>: o agente segue podendo decidir,",
                "mas fica sem com o que pagar. A próxima compra é recusada",
                "por <code>instrument_revoked</code>, não por revogação.",
                "",
                "Compras já liquidadas não são desfeitas.",
            ]
        ),
        (
            (("💳 Cancelar o cartão", f"{CALLBACK_CARD_CONFIRM}:{mandate.id}"),),
            (("← Voltar", f"{CALLBACK_MANDATE}:{mandate.id}"),),
        ),
    )


def receipt(view: ReceiptView) -> View:
    lines = [
        "🧾 <b>Extrato</b>",
        "",
        _mandate_body(view.mandate),
        "",
        "<b>Trilha auditável</b>",
    ]
    for entry in view.entries:
        lines.append(
            f"{entry.occurred_at:%d/%m %H:%M} · <code>{escape(entry.event_type)}</code>"
            f"\n    {escape(entry.human_summary)}"
        )
    if view.chain is not None:
        lines += ["", _chain_line(view.chain)]
    return View("\n".join(lines), _mandate_buttons(view.mandate))


def _chain_line(chain: ChainView) -> str:
    """An extract that says it is auditable without proving it is only a claim."""
    if chain.intact:
        return f"🔗 <i>Trilha íntegra — {chain.checked} evento(s) conferidos agora.</i>"
    where = "desconhecido" if chain.broken_at is None else f"#{chain.broken_at}"
    return (
        f"⛓️‍💥 <b>TRILHA VIOLADA</b> no evento {where} — {chain.checked} conferidos. "
        "Nada aqui serve como prova."
    )


_DISPUTE_VERDICT = {
    "MANDATE_HELD": (
        "🟢",
        "O mandato sustenta a compra",
        "Existe prova de autorização assinada ligando esta compra ao seu mandato. "
        "Numa contestação real é o emissor que responde ao titular, não o merchant.",
    ),
    "MANDATE_FAILED": (
        "🔴",
        "Nada vincula essa compra ao seu mandato",
        "Não há prova de autorização para esta reserva. A cobrança não se sustenta "
        "e o estorno é seu por direito.",
    ),
}


def dispute_verdict(dispute: DisputeView) -> View:
    """Who is right, decided by the trail — the only part of a dispute that matters.

    The bot states no opinion of its own: the badge comes from the ledger's verdict
    and the fine print is the core's own sentence, quoted.
    """
    badge, headline, meaning = _DISPUTE_VERDICT.get(
        dispute.status,
        ("⚪", "Disputa aberta", "O veredito ainda não saiu. A trilha é quem responde."),
    )
    lines = [
        f"{badge} <b>{escape(headline)}</b>",
        f"<code>{escape(dispute.id[:24])}</code> · {escape(dispute.status)}",
        "",
        escape(meaning),
    ]
    if dispute.resolution:
        lines += ["", f"<i>{escape(dispute.resolution)}</i>"]
    return View("\n".join(lines))


@dataclass(frozen=True)
class Wish:
    """One thing a person can ask the agent for, and what it would cost.

    A wish is not an offer. The person says *a flight to Córdoba*; the agent is
    what picks which flight — that is the whole point of the product, so the
    buttons express intent and let the agent shop.
    """

    slug: str
    label: str
    instruction: str
    cheapest: MoneyView
    category: str
    count: int


def _destination(title: str) -> str:
    """`São Paulo → Córdoba, 17 set · direto` becomes `Córdoba`."""
    tail = title.split("→")[-1] if "→" in title else title
    return tail.split(",")[0].split("·")[0].strip()


def _slugify(text: str) -> str:
    folded = unicodedata.normalize("NFD", text.lower())
    stripped = "".join(char for char in folded if unicodedata.category(char) != "Mn")
    return "-".join(part for part in re.split(r"[^a-z0-9]+", stripped) if part)


# The only two things the agent's reader can be asked for: `parse_intent` returns
# `travel` or `lodging` and nothing else. Offering a button for a category it
# cannot express would produce a guaranteed `no_offer` — a dead button.
_WISH_SHAPES = {
    "travel": ("✈️", "voo para {}"),
    "lodging": ("🏨", "hotel em {}"),
}


def wishes(items: Sequence[OfferView]) -> tuple[Wish, ...]:
    """Group the catalogue the way a person would ask for it."""
    grouped: dict[tuple[str, str], list[OfferView]] = {}
    for offer in items:
        if offer.category not in _WISH_SHAPES:
            continue
        key = (offer.category, _destination(offer.title))
        grouped.setdefault(key, []).append(offer)
    built: list[Wish] = []
    for (category, destination), offers in grouped.items():
        icon, phrasing = _WISH_SHAPES.get(category, ("🛒", "{}"))
        cheapest = min(offers, key=lambda item: item.total.minor_units)
        built.append(
            Wish(
                slug=_slugify(f"{category}-{destination}"),
                label=f"{icon} {destination}",
                instruction=phrasing.format(destination),
                cheapest=cheapest.total,
                category=category,
                count=len(offers),
            )
        )
    return tuple(sorted(built, key=lambda wish: (wish.category, wish.cheapest.minor_units)))


def wish_for(items: Sequence[OfferView], slug: str) -> Wish | None:
    return next((wish for wish in wishes(items) if wish.slug == slug), None)


def _reachable(wish: "Wish", mandate: MandateView | None) -> bool:
    """Whether this mandate could actually complete this purchase today.

    Two different refusals, one answer for the screen: a category the mandate never
    allowed, and a price the live budget can no longer cover.
    """
    if mandate is None:
        return True
    return (
        wish.category in mandate.categories
        and wish.cheapest.minor_units <= mandate.remaining.minor_units
    )


def catalogue(items: Sequence[OfferView], *, mandate: MandateView | None = None) -> View:
    """What to ask for, not what to pick.

    Someone holding a phone should be able to buy without being taught a command
    first. Free text still works and is where the adversarial story lives.
    """
    lines = [
        "<b>O que você quer?</b>",
        "",
        "Diga o destino — <b>quem escolhe a passagem é o seu agente</b>,",
        "e o mandato decide se ele pode.",
        "",
    ]
    rows: list[Row] = []
    # What the mandate can actually buy comes first. The out-of-scope offers stay —
    # the agent trying and the mandate barring is the demonstration — but a judge who
    # taps the top button must land on a purchase, not on an escalation, and the mark
    # belongs on the button rather than only on the line above it: the button is what
    # gets pressed.
    for wish in sorted(wishes(items), key=lambda w: (not _reachable(w, mandate), w.category, w.cheapest.minor_units)):
        mark = "" if _reachable(wish, mandate) else " ⚠️"
        lines.append(
            f"{wish.label} — a partir de <b>{format_money(wish.cheapest)}</b>"
            f" <i>({wish.count} opções)</i>{mark}"
        )
        rows.append(
            (
                (
                    f"{wish.label} · {format_money(wish.cheapest)}{mark}",
                    f"{CALLBACK_BUY}:{wish.slug}",
                ),
            )
        )
    lines += [
        "",
        "⚠️ o agente vai tentar mesmo assim — e o mandato vai barrar.",
        "",
        "Também aceita texto livre: <code>/comprar um voo barato pra Córdoba</code>",
    ]
    return View("\n".join(lines), tuple(rows))


def clarification(
    result: PurchaseView,
    items: Sequence[OfferView],
    *,
    mandate: MandateView | None = None,
) -> View:
    """The agent asking, with the answers as buttons.

    The buttons are the ordinary wish buttons, so answering the question *is* a normal
    purchase and the bot needs no memory of what was asked. Free text still works, and
    the question is the agent's own words — the bot does not paraphrase it.
    """
    lines = [
        "\U0001f914 <b>" + escape(result.human_summary) + "</b>",
        "",
        "<i>O agente parou aqui em vez de escolher por você.</i>",
        "",
    ]
    rows: list[Row] = []
    # Ordered and marked exactly like the catalogue: two screens that offer the same
    # answers must not disagree about which of them the mandate can pay for. Nothing
    # is hidden, so a nearly spent budget still gets a screen with answers on it.
    for wish in sorted(
        wishes(items), key=lambda w: (not _reachable(w, mandate), w.category, w.cheapest.minor_units)
    ):
        mark = "" if _reachable(wish, mandate) else " ⚠️"
        lines.append(f"{wish.label} — a partir de <b>{format_money(wish.cheapest)}</b>{mark}")
        rows.append(
            (
                (
                    f"{wish.label} · {format_money(wish.cheapest)}{mark}",
                    f"{CALLBACK_BUY}:{wish.slug}",
                ),
            )
        )
    lines += ["", "Ou responda em texto: <code>/comprar um voo pra Córdoba</code>"]
    return View("\n".join(lines), tuple(rows))


def watch_offer(instruction: str, mandate: MandateView) -> View:
    """Nothing meets the target *yet*, which is a standing order, not a dead end.

    The case's own scenario starts here — *buy me a flight if it drops below $150* —
    and answering "nothing matched" would throw away the one behaviour that makes the
    buyer an agent instead of a form.
    """
    return View(
        "\n".join(
            [
                "\U0001f50d <b>Nada atende a esse preço agora.</b>",
                "",
                f"Você pediu: <i>{escape(instruction)}</i>",
                "",
                "Posso <b>ficar vigiando</b> e comprar sozinho assim que cair —",
                "dentro do seu mandato, que decide cada tentativa.",
                "",
                "Você não precisa fazer mais nada.",
            ]
        ),
        ((("\U0001f440 Vigiar e comprar quando cair", f"{CALLBACK_WATCH}:{mandate.id}"),),),
    )


def watch_registered(watch: WatchView) -> View:
    days = max((watch.expires_at - datetime.now(UTC)).days, 0)
    return View(
        "\n".join(
            [
                "\U0001f440 <b>Vigiando.</b>",
                "",
                f"<i>{escape(watch.instruction)}</i>",
                f"Até {days} dia(s), ou até você revogar.",
                "",
                "Se cair, eu compro e te aviso aqui — <b>sem você pedir</b>.",
                "Se o mandato não permitir na hora, eu não compro e te conto.",
            ]
        )
    )


def watch_fired(watch: WatchView) -> View:
    """What the agent did while nobody was looking.

    The wording carries the whole point: on success it says it bought *by itself*, and
    on a refusal it says it tried and did not. An agent that only reported its wins
    would be hiding the half the mandate exists for.
    """
    what = escape(watch.instruction)
    if watch.purchase is None:
        return View(
            f"\U0001f440 <b>Parei de vigiar.</b>\n<i>{what}</i>\n\nO prazo acabou "
            "e eu não comprei nada."
        )
    result = watch.purchase
    title = escape(result.title or "—")
    price = f" — <b>{format_money(result.amount)}</b>" if result.amount else ""
    if result.outcome == "settled":
        return View(
            "\n".join(
                [
                    f"\u2705 <b>Comprei sozinho.</b>\n{title}{price}",
                    "",
                    f"O preço caiu e estava dentro do seu mandato. <i>{what}</i>",
                    f"Referência: <code>{escape(result.settlement_reference or '—')}</code>",
                ]
            )
            + _why(result),
            (
                (("\u26a0\ufe0f Não reconheço esta compra", f"{CALLBACK_DISPUTE}:{result.reservation_id}"),),
            )
            if result.reservation_id
            else (),
        )
    if result.outcome == "awaiting_human":
        return View(
            f"\U0001f7e1 <b>O preço caiu e eu parei em você.</b>\n{title}{price}\n\n"
            f"{escape(result.human_summary)}\n<i>{escape(result.reason_code)}</i>"
        )
    return View(
        "\n".join(
            [
                f"\u26d4 <b>O preço caiu e eu tentei comprar. Não comprei.</b>\n{title}{price}",
                "",
                escape(result.human_summary),
                f"<i>{escape(result.reason_code)}</i>",
                "",
                "A tentativa está na trilha. Sua autoridade é que decidiu, não eu.",
            ]
        )
    )


def help_text() -> View:
    return View(
        "\n".join(
            [
                "<b>Comandos</b>",
                "/comprar &lt;pedido&gt; — o agente tenta comprar em texto livre",
                "/mandato — orçamento vivo e estado",
                "/catalogo — o que está à venda",
                "/aprovacoes — compras aguardando você",
                "/extrato — recibos e trilha auditável",
                "/limite &lt;valor&gt; — muda o orçamento (assinado por você)",
                "/revogar — encerra a autoridade do agente",
                "/status — saúde do backend",
                "/meuid — o id deste chat",
            ]
        )
    )


def signed_note(action: str, message: str) -> View:
    return View(f"✅ <b>{escape(action)}</b>\n{escape(message)}\n\n<i>assinado pela sua chave</i>")


def plain(message: str) -> View:
    return View(escape(message))


def denied() -> View:
    return View("⛔ Este chat não tem autoridade neste bot.")


def no_mandate() -> View:
    return View("Você ainda não tem mandato. Mande /start para emitir o seu.")


def unavailable(detail: str, reason_code: str = "") -> View:
    """Fail-closed on screen: an unreachable core is never drawn as a success."""
    tail = f"\n<i>{escape(reason_code)}</i>" if reason_code else ""
    return View(f"⚠️ Nenhuma ação foi executada.\n{escape(detail)}{tail}")


def chat_id_view(chat_id: int) -> View:
    return View(f"Este chat é <code>{chat_id}</code>.")


def status(*, backend: str, base_url: str, open_mode: bool, pending: int) -> View:
    return View(
        "\n".join(
            [
                "<b>Status</b>",
                f"Núcleo: <code>{escape(backend)}</code> em {escape(base_url)}",
                f"Modo: {'aberto (um mandato por pessoa)' if open_mode else 'lista de autorizados'}",
                f"Aprovações pendentes: {pending}",
            ]
        )
    )
