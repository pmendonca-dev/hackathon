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
    EscalationView,
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


def mandate_card(mandate: MandateView) -> View:
    return View(_mandate_body(mandate), _mandate_buttons(mandate))


def _mandate_body(mandate: MandateView) -> str:
    badge = _STATUS_BADGE.get(mandate.status, "⚪")
    days = max((mandate.expires_at - datetime.now(UTC)).days, 0)
    lines = [
        f"{badge} <b>{escape(mandate.status)}</b> · <code>{escape(mandate.id[:20])}</code>",
        f"Orçamento: <b>{format_money(mandate.remaining)}</b> livres de {format_money(mandate.limit)}",
    ]
    if mandate.ceiling is not None:
        lines.append(f"Teto por compra: {format_money(mandate.ceiling)} — <i>ninguém atravessa</i>")
    if mandate.instrument_label is not None:
        # The fourth thing the mandate authorizes, next to the other three. The
        # agent holds a token for it and never the number.
        lines.append(f"Paga com: <b>{escape(mandate.instrument_label)}</b>")
    lines += [
        f"Pode comprar: {escape(', '.join(mandate.categories))} em {escape(', '.join(mandate.merchants))}",
        f"Vence em {days} dia(s) · política v{mandate.policy_version} · epoch {mandate.revocation_epoch}",
    ]
    return "\n".join(lines)


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
        if mandate.instrument_label is not None:
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
    return View("\n".join(lines), _mandate_buttons(view.mandate))


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
    for wish in wishes(items):
        allowed = mandate is None or wish.category in mandate.categories
        affordable = mandate is None or wish.cheapest.minor_units <= mandate.remaining.minor_units
        mark = "" if allowed and affordable else "  ⚠️"
        lines.append(
            f"{wish.label} — a partir de <b>{format_money(wish.cheapest)}</b>"
            f" <i>({wish.count} opções)</i>{mark}"
        )
        rows.append(
            ((f"{wish.label} · {format_money(wish.cheapest)}", f"{CALLBACK_BUY}:{wish.slug}"),)
        )
    lines += [
        "",
        "⚠️ o agente vai tentar mesmo assim — e o mandato vai barrar.",
        "",
        "Também aceita texto livre: <code>/comprar um voo barato pra Córdoba</code>",
    ]
    return View("\n".join(lines), tuple(rows))


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
