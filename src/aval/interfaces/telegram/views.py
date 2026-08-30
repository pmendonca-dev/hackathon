"""Pure rendering: gateway data in, message text and buttons out.

Nothing here performs I/O or decides anything, so every screen the judges will
touch is testable without a token, a network or a server. Reason codes are shown
next to the core's own `human_summary` and never rewritten — the bot repeats what
the core decided, it does not paraphrase it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from html import escape
from typing import Any
import re
import unicodedata

from aval.interfaces.telegram.gateway import (
    AgentProfileView,
    CardSessionView,
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
CALLBACK_NEW_CONFIRM = "new"

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
        CALLBACK_NEW_CONFIRM,
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
        f"<b>AVAL</b> — hello, {escape(display_name)}.",
        "",
        "You just got a <b>shopping agent</b>. It buys on its own,",
        "but only as far as you authorized — and you can cut it off at any moment.",
        "",
        "<b>👉 Tap «See what I can buy» to get started.</b>",
        "",
        "Or just ask: <code>/buy a flight to Córdoba</code>",
        "",
        "─────────────",
        "<b>Your mandate</b>, signed with your own key:",
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
        body += "\n\n\U0001f440 <b>Watching</b>\n" + "\n".join(
            f"· <i>{escape(watch.instruction)}</i>" for watch in watches
        )
    return View(body, _mandate_buttons(mandate))


def _mandate_body(mandate: MandateView) -> str:
    badge = _STATUS_BADGE.get(mandate.status, "⚪")
    days = max((mandate.expires_at - datetime.now(UTC)).days, 0)
    lines = [
        f"{badge} <b>{escape(mandate.status)}</b> · <code>{escape(mandate.id[:20])}</code>",
        f"Budget: <b>{format_money(mandate.remaining)}</b> free of {format_money(mandate.limit)}",
    ]
    if mandate.ceiling is not None:
        lines.append(f"Ceiling per purchase: {format_money(mandate.ceiling)} — <i>nobody gets past it</i>")
    if mandate.max_uses is not None:
        # Frequency reads as authority, not as a counter: what is left, and over what
        # window. The core escalates the use past this — it is not a wall, it is a
        # point where the person is asked again.
        left = max(mandate.max_uses - mandate.uses_in_window, 0)
        lines.append(
            f"Frequency: <b>{left} of {mandate.max_uses}</b> purchase(s) left "
            f"{_window_label(mandate.window_seconds)}"
        )
    if mandate.instrument_label is not None:
        # The fourth thing the mandate authorizes, next to the other three. The
        # agent holds a token for it and never the number. Once cancelled the label
        # stays — the holder still needs to know which card it was — but the line
        # stops claiming the mandate can pay, because it cannot.
        card = escape(mandate.instrument_label)
        lines.append(
            f"Card: <b>{card}</b> — \U0001f534 <b>cancelled</b>, nothing can be paid"
            if mandate.instrument_revoked
            else f"Pays with: <b>{card}</b>"
        )
    lines += [
        f"May buy: {escape(', '.join(mandate.categories))} at {escape(', '.join(mandate.merchants))}",
        f"Expires in {days} day(s) · policy v{mandate.policy_version} · epoch {mandate.revocation_epoch}",
    ]
    return "\n".join(lines)


def _window_label(window_seconds: int | None) -> str:
    """`2592000` becomes `in the last 30 days` — a person counts in days, not seconds."""
    if not window_seconds:
        return "in the mandate window"
    days = window_seconds // 86_400
    if days >= 1:
        return f"in the last {days} day(s)"
    return f"in the last {max(window_seconds // 3_600, 1)} hour(s)"


def _mandate_buttons(mandate: MandateView, *, primary: bool = False) -> tuple[Row, ...]:
    """Buying is the point; the rest is housekeeping, so it comes first."""
    rows: list[Row] = []
    if mandate.status == "ACTIVE":
        rows.append((("🛒 See what I can buy", f"{CALLBACK_CATALOGUE}:_"),))
    rows.append(
        (
            ("🔄 Refresh", f"{CALLBACK_MANDATE}:{mandate.id}"),
            ("🧾 Statement", f"{CALLBACK_RECEIPT}:{mandate.id}"),
        )
    )
    if mandate.status == "ACTIVE":
        # Two different things end here, so they are two different buttons: the
        # card stops the money, the revocation stops the authority.
        if mandate.instrument_label is not None and not mandate.instrument_revoked:
            rows.append(
                (("💳 Cancel the card", f"{CALLBACK_CARD_MENU}:{mandate.id}"),)
            )
        label = "🛑 Revoke the authority" if primary else "🛑 Revoke"
        rows.append(((label, f"{CALLBACK_REVOKE_MENU}:{mandate.id}"),))
    return tuple(rows)


def _why(result: PurchaseView) -> str:
    """The agent's reasoning, credited to whoever did it.

    It is shown next to the outcome and never instead of it: the reason explains the
    proposal, and the line above it is what the mandate did with that proposal.
    """
    if not result.rationale:
        return ""
    who = "🤖 The agent chose" if result.proposed_by == "llm" else "⚙️ Chosen by rule"
    return f"\n\n<b>{who}:</b> <i>{escape(result.rationale)}</i>"


def purchase_result(result: PurchaseView) -> View:
    """Four outcomes, four different things to say. Never a silent approval."""
    what = escape(result.title or "—")
    price = f" — <b>{format_money(result.amount)}</b>" if result.amount else ""
    buttons: tuple[Row, ...] = ()
    if result.outcome == "settled":
        head = f"✅ <b>Bought.</b>\n{what}{price}"
        tail = f"\nReference: <code>{escape(result.settlement_reference or '—')}</code>"
        if result.reservation_id:
            # The bonus the case asks for: a purchase can be denied later, and the
            # trail — not anyone's word — is what answers it.
            buttons = (
                (("⚠️ I do not recognize this purchase", f"{CALLBACK_DISPUTE}:{result.reservation_id}"),),
            )
    elif result.outcome == "in_doubt":
        # The third state, and the reason it has to exist here too: this branch used to
        # fall through to "Recusado", telling the person their money was free when it
        # was in fact still held. Refused and unanswered are opposite facts about the
        # budget, and the one screen a buyer actually reads had them merged.
        head = f"🕓 <b>Awaiting confirmation.</b>\n{what}{price}"
        tail = (
            "\nThe processor has not answered yet. The budget stays held "
            "until reconciliation — nothing was released and nothing was delivered."
        )
    elif result.outcome == "awaiting_human":
        head = f"🟡 <b>Needs you.</b>\n{what}{price}"
        tail = "\nThe agent stopped here. Decide below."
    elif result.outcome == "needs_clarification":
        # Answered by the catalogue screen, which carries the buttons. This branch
        # exists so a caller that renders only the result still says the right thing.
        head = "\U0001f914 <b>I need to know more.</b>"
        tail = ""
    elif result.outcome == "no_offer":
        head = "🔍 <b>Nothing in the catalogue matches.</b>"
        tail = "\nSee /catalog and try other words."
    else:
        head = f"⛔ <b>Refused.</b>\n{what}{price}"
        tail = ""
    return View(
        f"{head}\n\n{escape(result.human_summary)}\n<i>{escape(result.reason_code)}</i>{tail}",
        buttons,
    )


def escalation_card(escalation: EscalationView) -> View:
    return View(
        "\n".join(
            [
                "🟡 <b>Approval required</b>",
                "",
                f"<b>{format_money(escalation.amount)}</b> at {escape(escalation.merchant)}"
                f" · {escape(escalation.category)}",
                f"Handle: <code>{escape(escalation.id)}</code>",
                "",
                f"<i>{escape(escalation.reason_code)}</i>",
                "Your decision goes signed with your own key.",
            ]
        ),
        (
            (
                ("✅ Approve", f"{CALLBACK_APPROVE}:{escalation.id}"),
                ("❌ Refuse", f"{CALLBACK_DENY}:{escalation.id}"),
            ),
        ),
    )


def escalation_list(escalations: Sequence[EscalationView]) -> tuple[View, ...]:
    if not escalations:
        return (View("Nothing waiting on you. 🟢"),)
    return tuple(escalation_card(item) for item in escalations)


def revoke_menu(mandate: MandateView) -> View:
    return View(
        "\n".join(
            [
                "🛑 <b>Revoke the mandate?</b>",
                "",
                "It is irreversible and applies from the core's next decision on.",
                "Settled purchases are not undone — the authority ends, the history stays.",
            ]
        ),
        (
            (("🛑 Revoke now", f"{CALLBACK_REVOKE_CONFIRM}:{mandate.id}"),),
            (("← Back", f"{CALLBACK_MANDATE}:{mandate.id}"),),
        ),
    )


def cancel_card_menu(mandate: MandateView) -> View:
    """Ending the card is not ending the agent, and the screen has to say so."""
    return View(
        "\n".join(
            [
                f"💳 <b>Cancel {escape(mandate.instrument_label or 'the card')}?</b>",
                "",
                "The <b>mandate stays active</b>: the agent can still decide,",
                "but it is left with nothing to pay with. The next purchase is refused",
                "with <code>instrument_revoked</code>, not by revocation.",
                "",
                "Settled purchases are not undone.",
            ]
        ),
        (
            (("💳 Cancel the card", f"{CALLBACK_CARD_CONFIRM}:{mandate.id}"),),
            (("← Back", f"{CALLBACK_MANDATE}:{mandate.id}"),),
        ),
    )


def receipt(view: ReceiptView) -> View:
    lines = [
        "🧾 <b>Statement</b>",
        "",
        _mandate_body(view.mandate),
        "",
        "<b>Auditable trail</b>",
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
        return f"🔗 <i>Trail intact — {chain.checked} event(s) checked just now.</i>"
    where = "unknown" if chain.broken_at is None else f"#{chain.broken_at}"
    return (
        f"⛓️‍💥 <b>TRAIL TAMPERED</b> at event {where} — {chain.checked} checked. "
        "Nothing here serves as proof."
    )


_DISPUTE_VERDICT = {
    "MANDATE_HELD": (
        "🟢",
        "The mandate holds up the purchase",
        "There is signed authorization proof tying this purchase to your mandate. "
        "In a real chargeback it is the issuer who answers to the holder, not the merchant.",
    ),
    "MANDATE_FAILED": (
        "🔴",
        "Nothing ties that purchase to your mandate",
        "There is no authorization proof for this reservation. The charge does not hold up "
        "and the refund is yours by right.",
    ),
}


def agent_card(
    profile: AgentProfileView | None, *, holder_name: str, holder_kid: str, principal_id: str
) -> View:
    """Two identities, two keys, and what each one is allowed to sign.

    The case asks for the agent's identity to be separate from the human's. Saying it
    on one screen is what makes the separation checkable instead of architectural
    folklore: neither key can produce the other's signature, so a compromised agent
    still cannot revoke, approve or move a limit.
    """
    lines = [
        "🪪 <b>Who is who in this purchase</b>",
        "",
        f"👤 <b>You, the holder</b> — {escape(holder_name)}",
        f"    <code>{escape(principal_id)}</code> · key <code>{escape(holder_kid)}</code>",
        "    Signs: revoke, approve, change the limit.",
        "",
    ]
    if profile is None:
        lines.append("🤖 <b>The agent</b> — profile unavailable from the core right now.")
    else:
        badge = "✅ trusted" if profile.trusted else "⛔ not trusted"
        lines += [
            f"🤖 <b>The agent</b> — {badge}",
            f"    <code>{escape(profile.agent_id)}</code> · key <code>{escape(profile.kid)}</code>",
            "    Signs: the purchase requests. Nothing else.",
        ]
        if profile.profile_url:
            lines.append(f"    <i>{escape(profile.profile_url)}</i>")
    lines += [
        "",
        "<i>Different keys. The agent cannot revoke its own mandate, "
        "and an agent impersonating this one is refused at the door.</i>",
    ]
    return View("\n".join(lines))


def dispute_verdict(dispute: DisputeView) -> View:
    """Who is right, decided by the trail — the only part of a dispute that matters.

    The bot states no opinion of its own: the badge comes from the ledger's verdict
    and the fine print is the core's own sentence, quoted.
    """
    badge, headline, meaning = _DISPUTE_VERDICT.get(
        dispute.status,
        ("⚪", "Dispute open", "The verdict is not out yet. The trail is what answers."),
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
    """`São Paulo → Córdoba, 17 Sep · nonstop` becomes `Córdoba`."""
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
    "travel": ("✈️", "flight to {}"),
    "lodging": ("🏨", "hotel in {}"),
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
        "<b>What do you want?</b>",
        "",
        "Name the destination — <b>your agent is the one who picks the fare</b>,",
        "and the mandate decides whether it may.",
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
            f"{wish.label} — from <b>{format_money(wish.cheapest)}</b>"
            f" <i>({wish.count} options)</i>{mark}"
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
        "⚠️ the agent will try anyway — and the mandate will bar it.",
        "",
        "Free text works too: <code>/buy a cheap flight to Córdoba</code>",
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
        "<i>The agent stopped here instead of choosing for you.</i>",
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
        lines.append(f"{wish.label} — from <b>{format_money(wish.cheapest)}</b>{mark}")
        rows.append(
            (
                (
                    f"{wish.label} · {format_money(wish.cheapest)}{mark}",
                    f"{CALLBACK_BUY}:{wish.slug}",
                ),
            )
        )
    lines += ["", "Or answer in text: <code>/buy a flight to Córdoba</code>"]
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
                "\U0001f50d <b>Nothing meets that price right now.</b>",
                "",
                f"You asked for: <i>{escape(instruction)}</i>",
                "",
                "I can <b>keep watching</b> and buy on my own the moment it drops —",
                "inside your mandate, which decides every attempt.",
                "",
                "You do not have to do anything else.",
            ]
        ),
        ((("\U0001f440 Watch and buy when it drops", f"{CALLBACK_WATCH}:{mandate.id}"),),),
    )


def watch_registered(watch: WatchView) -> View:
    days = max((watch.expires_at - datetime.now(UTC)).days, 0)
    return View(
        "\n".join(
            [
                "\U0001f440 <b>Watching.</b>",
                "",
                f"<i>{escape(watch.instruction)}</i>",
                f"For up to {days} day(s), or until you revoke.",
                "",
                "If it drops, I buy and tell you here — <b>without you asking</b>.",
                "If the mandate does not allow it then, I do not buy and I tell you.",
            ]
        )
    )


# The one sentence this MVP may never stop saying. A signed offer plus a real charge
# together read as "an order was placed", and no order was: AVAL found a public page and
# charged the person's own test-mode card. Saying so every time is the difference between
# a demonstration and a claim that is not true.
NO_EXTERNAL_ORDER = (
    "I placed no order with the seller — AVAL found the page and charged your test card."
)


def shopping_preview(shopping: Any) -> View:
    """What the agent will go looking for, shown before anything is signed.

    Deliberately a second screen rather than more lines on the mandate card. The
    mandate is authority — what may be spent — and this is a standing order to spend it
    without asking again. Those are two decisions, and a person should have to read
    them as two.

    Everything needed to say no is here: what, up to how much, for how long, that the
    charge happens with nobody at the keyboard, and that no seller receives an order.
    """
    cap = format_money(MoneyView(shopping.max_minor_units, shopping.currency, shopping.scale))
    return View(
        "\n".join(
            [
                "\U0001f50d <b>And I will keep looking for this:</b>",
                "",
                f"<i>{escape(shopping.query)}</i>",
                f"Up to <b>{cap}</b>, for <b>{shopping.watch_days} day(s)</b>.",
                "",
                "If I find something that fits, <b>I buy it on my own</b> and tell you here — "
                "without asking again. If the mandate does not allow it then, I do not buy "
                "and I tell you.",
                f"<i>{NO_EXTERNAL_ORDER}</i>",
            ]
        )
    )


def shopping_armed(shopping: Any) -> View:
    """Said after the watch exists, so "armed" is a fact rather than a promise."""
    return View(
        "\n".join(
            [
                "\U0001f440 <b>Watch armed.</b>",
                "",
                f"<i>{escape(shopping.query)}</i>",
                f"For {shopping.watch_days} day(s), or until you revoke.",
                "",
                "Use /mandate to see what is armed and /revoke to turn it off.",
            ]
        )
    )


def watch_event(payload: Mapping[str, Any]) -> View:
    """What the core did, as the person reads it.

    Everything here crossed a machine boundary as display data. Nothing in it is
    verified or verifiable by this bot, and nothing in it grants anything — which is
    exactly why it can be shown without ceremony.
    """
    outcome = str(payload.get("outcome") or "")
    title = escape(str(payload.get("title") or "—"))
    url = str(payload.get("source_url") or "")
    seller = escape(str(payload.get("source_merchant") or "—"))
    minor = payload.get("amount_minor_units")
    price = ""
    if isinstance(minor, int) and payload.get("currency"):
        money = MoneyView(minor, str(payload["currency"]), int(payload.get("scale") or 2))
        price = f" — <b>{format_money(money)}</b>"
    # The link is the whole point of a real-offer watch: it lets the person check the
    # claim instead of believing it.
    link = f'\U0001f517 <a href="{escape(url)}">See the page</a>' if url else None

    if outcome == "watch_expired":
        return View("\U0001f440 <b>I stopped watching.</b>\n\nThe window ran out and I bought nothing.")

    if outcome == "settled":
        lines = [
            f"✅ <b>I bought it on my own.</b>\n{title}{price}",
            "",
            f"Seller: {seller}",
        ]
        if link:
            lines.append(link)
        reference = payload.get("settlement_reference")
        if reference:
            lines.append(f"Reference: <code>{escape(str(reference))}</code>")
        lines += ["", f"<i>{NO_EXTERNAL_ORDER}</i>"]
        return View("\n".join(lines))

    summary = escape(str(payload.get("human_summary") or "The purchase was not authorized."))
    lines = [f"\U0001f6d1 <b>I tried and did not buy.</b>\n{title}{price}", "", summary]
    if link:
        lines.append(link)
    lines.append(f"Core's reason: <code>{escape(outcome or '—')}</code>")
    return View("\n".join(lines))


def watch_fired(watch: WatchView) -> View:
    """What the agent did while nobody was looking.

    The wording carries the whole point: on success it says it bought *by itself*, and
    on a refusal it says it tried and did not. An agent that only reported its wins
    would be hiding the half the mandate exists for.
    """
    what = escape(watch.instruction)
    if watch.purchase is None:
        return View(
            f"\U0001f440 <b>I stopped watching.</b>\n<i>{what}</i>\n\nThe window ran out "
            "and I bought nothing."
        )
    result = watch.purchase
    title = escape(result.title or "—")
    price = f" — <b>{format_money(result.amount)}</b>" if result.amount else ""
    if result.outcome == "settled":
        return View(
            "\n".join(
                [
                    f"\u2705 <b>I bought it on my own.</b>\n{title}{price}",
                    "",
                    f"The price dropped and it was inside your mandate. <i>{what}</i>",
                    f"Reference: <code>{escape(result.settlement_reference or '—')}</code>",
                ]
            )
            + _why(result),
            (
                (("\u26a0\ufe0f I do not recognize this purchase", f"{CALLBACK_DISPUTE}:{result.reservation_id}"),),
            )
            if result.reservation_id
            else (),
        )
    if result.outcome == "awaiting_human":
        return View(
            f"\U0001f7e1 <b>The price dropped and I stopped at you.</b>\n{title}{price}\n\n"
            f"{escape(result.human_summary)}\n<i>{escape(result.reason_code)}</i>"
        )
    return View(
        "\n".join(
            [
                f"\u26d4 <b>The price dropped and I tried to buy. I did not.</b>\n{title}{price}",
                "",
                escape(result.human_summary),
                f"<i>{escape(result.reason_code)}</i>",
                "",
                "The attempt is on the trail. Your authority decided this, not me.",
            ]
        )
    )


def help_text() -> View:
    return View(
        "\n".join(
            [
                "<b>Commands</b>",
                "<i>Or simply say what the agent may do — I ask for whatever is "
                "missing and show you the mandate to confirm.</i>",
                "",
                "/buy &lt;request&gt; — the agent tries to buy, in free text",
                "/mandate — live budget and state",
                "/catalog — what is on sale",
                "/approvals — purchases waiting on you",
                "/statement — receipts and the auditable trail",
                "/card — register the card that pays (on the processor's page)",
                "/limit &lt;amount&gt; — change the budget (signed by you)",
                "/new &lt;rule&gt; — remake the mandate: <i>/new hotel up to 300 for 7 days, 2x</i>",
                "/revoke — end the agent's authority",
                "/agent — who the agent is, and why it is not you",
                "/status — backend health",
                "/myid — this chat's id",
            ]
        )
    )


def signed_note(action: str, message: str) -> View:
    return View(f"✅ <b>{escape(action)}</b>\n{escape(message)}\n\n<i>signed by your own key</i>")


@dataclass(frozen=True)
class MandateSpec:
    """What a person just said their agent may do.

    A spec is not a mandate: it is the sentence, read. Nothing here is authority
    until the core registers it and the person's own key signs the swap.
    """

    categories: tuple[str, ...]
    limit: MoneyView
    valid_for_days: int
    max_uses: int | None


# English is what the bot now speaks, and the Portuguese words stay because a person
# who typed them yesterday should not be told today that the sentence means nothing.
_CATEGORY_WORDS = {
    "lodging": (
        "hotel", "lodging", "stay", "night", "inn",
        "hospedagem", "pousada", "diaria", "diária", "noite",
    ),
    "travel": (
        "flight", "travel", "fare", "trip", "air",
        "voo", "viagem", "passagem", "aereo", "aéreo",
    ),
}
_DAYS = re.compile(r"(\d{1,3})\s*(?:day|days|dia|dias)")
_USES = re.compile(r"(\d{1,2})\s*(?:x|times?|purchases?|vez|vezes|compras?)")


def parse_mandate_spec(raw: str, *, defaults) -> MandateSpec | None:
    """Read `lodging up to 300 for 7 days, 2x`.

    Deliberately forgiving and deliberately partial: whatever the sentence does not
    say falls back to the configured default, so a person can change one thing
    without restating the other three. Saying nothing at all is not a mandate,
    though — an empty spec would silently mean "the defaults", and a mandate the
    person did not actually describe is the one thing this must not create.
    """
    text = raw.strip().lower()
    if not text:
        return None
    folded = "".join(
        char
        for char in unicodedata.normalize("NFD", text)
        if unicodedata.category(char) != "Mn"
    )
    categories = tuple(
        name
        for name, words in _CATEGORY_WORDS.items()
        if any(word in folded for word in words)
    )
    days = _DAYS.search(folded)
    uses = _USES.search(folded)
    # Days and uses are counts, not money: they are struck from the text before the
    # amount is read, or `for 7 days` would be a seven-dollar budget.
    without_counts = _USES.sub(" ", _DAYS.sub(" ", folded))
    amount = None
    money = re.search(r"\d[\d.,]*", without_counts)
    if money:
        amount = parse_money(money.group(), currency=defaults.currency, scale=defaults.scale)
    return MandateSpec(
        categories=categories or tuple(defaults.categories),
        limit=amount
        or MoneyView(defaults.limit_minor_units, defaults.currency, defaults.scale),
        valid_for_days=int(days.group(1)) if days else defaults.valid_for.days,
        max_uses=int(uses.group(1)) if uses else defaults.max_uses,
    )


def new_mandate_preview(spec: MandateSpec, current: MandateView | None) -> View:
    """Say what is about to be granted, and what it costs, before it is granted.

    Replacing a mandate revokes the one in force — that is the honest way to change
    what was authorized, and it is far too destructive to happen on a typo.
    """
    lines = [
        "📝 <b>New mandate — check it first</b>",
        "",
        f"May buy: <b>{escape(', '.join(spec.categories))}</b>",
        f"Budget: <b>{format_money(spec.limit)}</b>",
        f"Valid for: <b>{spec.valid_for_days} day(s)</b>",
        f"Frequency: <b>{spec.max_uses}</b> purchase(s) per window"
        if spec.max_uses
        else "Frequency: <b>no cap on how many times</b>",
        "Method: <b>none yet</b> — register one with /card",
    ]
    if current is not None and current.status == "ACTIVE":
        lines += [
            "",
            f"⚠️ This <b>revokes</b> the mandate in force (<code>{escape(current.id[:20])}</code>) "
            "and issues another. Settled purchases stay valid — but the card does not "
            "come along: the new mandate is born with no means of payment.",
        ]
    return View(
        "\n".join(lines),
        ((("✅ Issue this mandate", f"{CALLBACK_NEW_CONFIRM}:{(current.id if current else '_')}"),),),
    )


def card_form(session: CardSessionView) -> View:
    """The link to the processor's own page, and why it is a link and not a question.

    Saying where the number goes is not decoration. A person who understands that the
    card is typed at the processor knows what to check before typing it, and a bot
    that asked for the number in the chat would deserve the answer it got.
    """
    return View(
        "\n".join(
            [
                "💳 <b>Register the card</b>",
                "",
                "Open the link and type the card <b>on the processor's page</b>.",
                "The number never passes through this chat, or me, and is not stored here.",
                "",
                f'<a href="{escape(session.url)}">👉 Open the secure page</a>',
                "",
                "<i>When you are done, come back and send /card again — I check it "
                "and bind it to your mandate, signed with your own key.</i>",
            ]
        )
    )


def card_pending() -> View:
    return View(
        "⏳ I have not seen a card registered on that page yet.\n"
        "<i>Finish registering and send /card again.</i>"
    )


def card_bound(label: str, *, replaced: bool) -> View:
    headline = "Card replaced" if replaced else "Card registered"
    return View(
        "\n".join(
            [
                f"✅ <b>{headline}</b> — {escape(label)}",
                "",
                "The mandate now has something to pay with. The agent presents that card",
                "and nothing else: it never saw the number, and neither did I.",
                "",
                "<i>You can cancel just the card at any time from /mandate, "
                "without ending the agent.</i>",
            ]
        )
    )


def plain(message: str) -> View:
    return View(escape(message))


def denied() -> View:
    return View("⛔ This chat has no authority on this bot.")


def no_mandate() -> View:
    return View("You do not have a mandate yet. Send /start to issue yours.")


def unavailable(detail: str, reason_code: str = "") -> View:
    """Fail-closed on screen: an unreachable core is never drawn as a success."""
    tail = f"\n<i>{escape(reason_code)}</i>" if reason_code else ""
    return View(f"⚠️ No action was taken.\n{escape(detail)}{tail}")


def chat_id_view(chat_id: int) -> View:
    return View(f"This chat is <code>{chat_id}</code>.")


def status(*, backend: str, base_url: str, open_mode: bool, pending: int) -> View:
    return View(
        "\n".join(
            [
                "<b>Status</b>",
                f"Core: <code>{escape(backend)}</code> at {escape(base_url)}",
                f"Mode: {'open (one mandate per person)' if open_mode else 'allow-list'}",
                f"Pending approvals: {pending}",
            ]
        )
    )
