"""The half of the agent that a language model is allowed to be.

This module *proposes*. It reads what a person typed, looks at offers the sellers
signed, and picks one — with a reason a human can read. Nothing here decides anything:
the proposal is handed to the same `/authorize` call any other agent would make, and
the core re-derives every limit from the mandate without ever seeing this text.

So the prompt is deliberately not hardened. The model is told the mandate's limits
because an agent that knows the budget shops better and explains itself better — and
when a judge talks it into proposing the executive fare anyway, the ceiling still
refuses it. A system whose safety depended on the model not being fooled would be a
system with no safety at all.

No SDK: one POST with the standard library, a short timeout, and `None` on anything at
all going wrong. `None` means the rule-based reader in `intent.py` takes over, so the
demo survives a dead network, a rate limit, or an unplugged key.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-4.1-mini"
DEFAULT_TIMEOUT = 6.0

SYSTEM_PROMPT = """Você é o agente de compras de uma pessoa. Você escolhe UMA oferta do catálogo que recebeu.

Regras da sua escolha:
- O mais barato quase nunca é o melhor. Compare escalas, duração, horário de partida, bagagem e reembolso contra o que a pessoa pediu.
- Respeite o que a pessoa pediu explicitamente. Se ela pediu a executiva, proponha a executiva.
- Prefira ofertas dentro do mandato. Se a melhor resposta ao pedido estiver fora dele, proponha assim mesmo e marque excede_mandato: true — quem decide não é você.
- Escreva o motivo em uma frase curta, em português, como quem explica para o dono do dinheiro.

Responda SÓ com JSON:
{"sku": "<sku escolhido>", "motivo": "<uma frase>", "descartadas": [{"sku": "<sku>", "motivo": "<meia frase>"}], "excede_mandato": false}

O sku tem que ser um dos que você recebeu. No máximo três descartadas."""


@dataclass(frozen=True)
class Proposal:
    sku: str
    rationale: str
    alternatives: tuple[tuple[str, str], ...] = ()
    knows_it_exceeds: bool = False


def _api_key() -> str:
    return (
        os.environ.get("AVAL_LLM_API_KEY", "") or os.environ.get("OPENAI_API_KEY", "")
    ).strip()


def configured() -> bool:
    """Whether a model is reachable at all. Absent a key the agent stays rule-based."""
    return bool(_api_key())


def _offer_line(offer: dict[str, Any]) -> str:
    item = offer["item"]
    total = offer["total"]
    facts = [f"{total['minor_units'] / 10 ** total['scale']:.2f} {total['currency']}"]
    if item.get("stops") is not None:
        facts.append("direto" if item["stops"] == 0 else f"{item['stops']} escala(s)")
    if item.get("duration_minutes"):
        facts.append(f"{item['duration_minutes'] // 60}h{item['duration_minutes'] % 60:02d}")
    if item.get("departs"):
        facts.append(f"parte {item['departs']}")
    if item.get("nights"):
        facts.append(f"{item['nights']} noites")
    if "checked_bag" in item:
        # Only for things that fly. A hotel with "sem bagagem" is noise the model has to
        # read past on every single line.
        facts.append("com bagagem" if item["checked_bag"] else "sem bagagem")
    if item.get("refundable"):
        facts.append("reembolsável")
    return (
        f"- {item['sku']} | {item['title']} | vendedor {offer['merchant_id']}"
        f" | categoria {item['category']} | {', '.join(facts)}"
    )


def _mandate_line(mandate: dict[str, Any] | None) -> str:
    if mandate is None:
        return "Mandato: desconhecido."
    unit = 10 ** mandate["scale"]
    return (
        f"Mandato: pode comprar {', '.join(sorted(mandate['categories']))}"
        f" em {', '.join(sorted(mandate['merchants']))};"
        f" restam {mandate['remaining'] / unit:.2f} {mandate['currency']} de orçamento"
        + (
            f"; teto por compra {mandate['ceiling'] / unit:.2f} {mandate['currency']}"
            if mandate.get("ceiling")
            else ""
        )
        + "."
    )


def _post(payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    base = os.environ.get("AVAL_LLM_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
    request = urllib.request.Request(
        f"{base}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {_api_key()}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def propose(
    instruction: str,
    candidates: list[dict[str, Any]],
    *,
    mandate: dict[str, Any] | None = None,
) -> Proposal | None:
    """Ask the model to pick one of `candidates`, or return None and let rules decide."""
    if not candidates or not configured():
        return None

    known = {offer["item"]["sku"] for offer in candidates}
    user_prompt = "\n".join(
        [
            f"Pedido: {instruction}",
            _mandate_line(mandate),
            "",
            "Catálogo:",
            *(_offer_line(offer) for offer in candidates),
        ]
    )
    try:
        body = _post(
            {
                "model": os.environ.get("AVAL_LLM_MODEL", DEFAULT_MODEL),
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
            },
            float(os.environ.get("AVAL_LLM_TIMEOUT", DEFAULT_TIMEOUT)),
        )
        chosen = json.loads(body["choices"][0]["message"]["content"])
        sku = str(chosen["sku"])
    except (
        urllib.error.URLError,
        TimeoutError,
        OSError,
        KeyError,
        IndexError,
        TypeError,
        ValueError,
    ) as error:
        # Every failure lands here on purpose, including a model that answered with
        # something that is not the JSON it was asked for.
        logger.warning("proponente indisponível, decidindo por regras: %s", error)
        return None

    if sku not in known:
        # A model naming an offer nobody is selling has not proposed a purchase.
        logger.warning("proponente escolheu um sku fora do catálogo: %s", sku)
        return None

    alternatives = tuple(
        (str(entry.get("sku", "")), str(entry.get("motivo", "")))
        for entry in (chosen.get("descartadas") or [])[:3]
        if isinstance(entry, dict) and entry.get("sku") in known
    )
    return Proposal(
        sku=sku,
        rationale=str(chosen.get("motivo", "")).strip(),
        alternatives=alternatives,
        knows_it_exceeds=bool(chosen.get("excede_mandato")),
    )
