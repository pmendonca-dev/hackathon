"""Pure rendering: gateway data in, message text and buttons out.

Nothing here imports Telegram or performs I/O, so the whole conversation
surface is testable without a token, a network or the backend.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from html import escape

from aval.interfaces.telegram.gateway import (
    ActionResult,
    ActivityView,
    ApprovalView,
    MandateView,
    MoneyView,
)

Button = tuple[str, str]
Row = tuple[Button, ...]

# Callback payloads are capped at 64 bytes by Telegram, so keep verbs at three
# characters and carry only an id.
CALLBACK_APPROVE = "apr"
CALLBACK_DENY = "den"
CALLBACK_MANDATE = "mnd"
CALLBACK_REVOKE_MENU = "rvk"
CALLBACK_REVOKE_MANDATE = "rvm"
CALLBACK_REVOKE_BUDGET = "rvb"
CALLBACK_MANDATE_LIST = "lst"

_STATUS_BADGE = {
    "ACTIVE": "🟢",
    "ESCALATED": "🟡",
    "REVOKED": "🔴",
    "EXPIRED": "⚫",
}

_SYMBOL = {"BRL": "R$", "USD": "US$", "EUR": "€"}


@dataclass(frozen=True)
class View:
    text: str
    buttons: tuple[Row, ...] = ()


def format_money(amount: MoneyView) -> str:
    """Integer arithmetic only. Money never becomes a float, not even to print."""
    sign = "-" if amount.minor_units < 0 else ""
    units = abs(amount.minor_units)
    divisor = 10**amount.scale
    whole, fraction = divmod(units, divisor)
    grouped = f"{whole:,}".replace(",", ".")
    symbol = _SYMBOL.get(amount.currency, amount.currency)
    if amount.scale == 0:
        return f"{sign}{symbol} {grouped}"
    return f"{sign}{symbol} {grouped},{fraction:0{amount.scale}d}"


def parse_callback(data: str) -> tuple[str, str] | None:
    """Callback data arrives from a client; treat it as untrusted input."""
    if not data or len(data) > 64:
        return None
    verb, _, argument = data.partition(":")
    if verb not in {
        CALLBACK_APPROVE,
        CALLBACK_DENY,
        CALLBACK_MANDATE,
        CALLBACK_REVOKE_MENU,
        CALLBACK_REVOKE_MANDATE,
        CALLBACK_REVOKE_BUDGET,
        CALLBACK_MANDATE_LIST,
    }:
        return None
    if verb == CALLBACK_MANDATE_LIST:
        return verb, ""
    if not argument or not all(char.isalnum() or char in "_-" for char in argument):
        return None
    return verb, argument


def welcome(*, chat_id: int, allowed: bool, mock_mode: bool, demo_mode: bool = False) -> View:
    lines = [
        "<b>AVAL</b> — autoridade de pagamento agêntico.",
        "",
        "Seu agente compra. Você mantém a autoridade: aprova, recusa e revoga por aqui.",
    ]
    if demo_mode:
        return View(
            "\n".join(
                lines
                + [
                    "",
                    "🧪 <b>Demo aberta.</b> Você recebeu seus próprios mandatos de teste.",
                    "Só você decide sobre eles — ninguém mais vê nem toca no seu estado.",
                    "",
                    "Use /ajuda para ver os comandos.",
                ]
            )
        )
    if not allowed:
        lines += [
            "",
            "⛔ Este chat ainda não está autorizado.",
            f"Adicione <code>{chat_id}</code> a <code>TELEGRAM_ALLOWED_CHAT_IDS</code> e reinicie o bot.",
        ]
    else:
        lines += ["", "Use /ajuda para ver os comandos."]
    if mock_mode:
        lines += ["", "⚠️ <i>Modo mock: backend AVAL ainda não conectado.</i>"]
    return View("\n".join(lines))


def help_text() -> View:
    return View(
        "\n".join(
            [
                "<b>Comandos</b>",
                "/mandatos — mandatos ativos e orçamento vivo",
                "/aprovacoes — compras aguardando você",
                "/atividade — últimos eventos auditáveis",
                "/revogar &lt;id&gt; — revoga um mandato agora",
                "/status — saúde do backend e modo atual",
                "/meuid — mostra o id deste chat",
            ]
        )
    )


def denied() -> View:
    return View("⛔ Este chat não tem autoridade sobre nenhum mandato.")


def unavailable(detail: str) -> View:
    """Fail-closed surface: an unreachable backend is never rendered as success."""
    return View(f"⚠️ AVAL indisponível. Nenhuma ação foi executada.\n<code>{escape(detail)}</code>")


def chat_id_view(chat_id: int) -> View:
    return View(f"Este chat é <code>{chat_id}</code>.")


def status(*, backend: str, mock_mode: bool, pending: int, demo_mode: bool = False) -> View:
    mode = "demo aberta (sandbox por pessoa)" if demo_mode else "mock (fixtures)" if mock_mode else "backend AVAL"
    return View(
        "\n".join(
            [
                "<b>Status</b>",
                f"Modo: {escape(mode)}",
                f"Saúde: <code>{escape(backend)}</code>",
                f"Aprovações pendentes: {pending}",
            ]
        )
    )


def mandate_list(mandates: Sequence[MandateView]) -> View:
    if not mandates:
        return View("Nenhum mandato emitido ainda.")
    lines = ["<b>Mandatos</b>"]
    rows: list[Row] = []
    for mandate in mandates:
        badge = _STATUS_BADGE.get(mandate.status, "⚪")
        lines.append(
            f"{badge} <code>{escape(mandate.id)}</code> — {escape(mandate.agent)}"
            f"\n    {format_money(mandate.spent)} de {format_money(mandate.limit)}"
        )
        rows.append(((f"{badge} {mandate.id}", f"{CALLBACK_MANDATE}:{mandate.id}"),))
    return View("\n".join(lines), tuple(rows))


def mandate_detail(mandate: MandateView, *, now: datetime | None = None) -> View:
    moment = now or datetime.now(timezone.utc)
    remaining = MoneyView(
        mandate.limit.minor_units - mandate.spent.minor_units,
        mandate.limit.currency,
        mandate.limit.scale,
    )
    badge = _STATUS_BADGE.get(mandate.status, "⚪")
    days = (mandate.expires_at - moment).days
    lines = [
        f"{badge} <b>{escape(mandate.id)}</b>",
        f"Titular: {escape(mandate.principal)}",
        f"Agente: {escape(mandate.agent)}",
        f"Teto: {format_money(mandate.limit)}",
        f"Gasto: {format_money(mandate.spent)}",
        f"Disponível: {format_money(remaining)}",
        f"Merchants: {escape(', '.join(mandate.merchants) or '—')}",
        f"Expira em: {days} dia(s)",
        f"Política v{mandate.policy_version} · epoch de revogação {mandate.revocation_epoch}",
    ]
    buttons: tuple[Row, ...] = ()
    if mandate.status == "ACTIVE":
        buttons = (
            (("🛑 Revogar", f"{CALLBACK_REVOKE_MENU}:{mandate.id}"),),
            (("← Mandatos", CALLBACK_MANDATE_LIST),),
        )
    else:
        buttons = ((("← Mandatos", CALLBACK_MANDATE_LIST),),)
    return View("\n".join(lines), buttons)


def revoke_menu(mandate: MandateView) -> View:
    return View(
        "\n".join(
            [
                f"<b>Revogar {escape(mandate.id)}</b>",
                "",
                "A revogação é irreversível e vale a partir da próxima decisão.",
                "Capturas já liquidadas não são desfeitas.",
            ]
        ),
        (
            (("🛑 Revogar mandato inteiro", f"{CALLBACK_REVOKE_MANDATE}:{mandate.id}"),),
            (("💸 Zerar orçamento", f"{CALLBACK_REVOKE_BUDGET}:{mandate.id}"),),
            (("← Voltar", f"{CALLBACK_MANDATE}:{mandate.id}"),),
        ),
    )


def approval_card(approval: ApprovalView) -> View:
    return View(
        "\n".join(
            [
                "🟡 <b>Aprovação necessária</b>",
                "",
                f"{escape(approval.item)} — <b>{format_money(approval.amount)}</b>",
                f"Merchant: {escape(approval.merchant)}",
                f"Mandato: <code>{escape(approval.mandate_id)}</code>",
                "",
                escape(approval.human_summary),
                f"<i>{escape(approval.reason_code)}</i>",
            ]
        ),
        (
            (
                ("✅ Aprovar", f"{CALLBACK_APPROVE}:{approval.id}"),
                ("❌ Recusar", f"{CALLBACK_DENY}:{approval.id}"),
            ),
        ),
    )


def approval_list(approvals: Sequence[ApprovalView]) -> tuple[View, ...]:
    if not approvals:
        return (View("Nada aguardando você. 🟢"),)
    return tuple(approval_card(approval) for approval in approvals)


def activity_list(events: Sequence[ActivityView]) -> View:
    if not events:
        return View("Sem eventos registrados.")
    lines = ["<b>Atividade</b>"]
    for event in events:
        lines.append(
            f"{event.occurred_at:%d/%m %H:%M} · <code>{escape(event.event_type)}</code>"
            f"\n    {escape(event.human_summary)}"
        )
    return View("\n".join(lines))


def action_result(result: ActionResult) -> View:
    prefix = "✅" if result.ok else "⚠️"
    return View(f"{prefix} {escape(result.message)}")
