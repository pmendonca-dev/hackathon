"""A cobrança que não passou por aqui — para que o estorno seja visto, não narrado.

O rodapé da demonstração publica `gasto autorizado fora do mandato`: dinheiro retido ou
liquidado **sem** prova de autorização emitida por esta camada. É a mesma condição que a
disputa resolve como `AGENT_OVERREACH`, e é a única em que o veredito devolve dinheiro.

Ela existe porque um agente pode cobrar por fora: apresentar o cartão direto ao
processador, sem nunca perguntar ao mandato. Nesse caso o núcleo não recusou nada — ele
não foi consultado — e é justamente aí que a trilha tem de responder *quem paga*.

Sem esta rota o caminho seria inalcançável numa demonstração, porque toda captura que
passa pelo núcleo emite prova. Com ela, o jurado encena o agente desonesto em um clique
e assiste ao dinheiro voltar.

Como a rota de adulteração, ela **só existe** com `AVAL_DEMO_ROGUE` ligado: sem a
variável o router não é montado, então o caminho responde 404 e não aparece no
OpenAPI. O token de operador é exigido por cima disso, e o ato entra no diário do
operador como qualquer outra escrita — quem encenou a fraude fica registrado.
"""

from __future__ import annotations

import os
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, Field

from aval.api.dependencies import runtime_of
from aval.api.errors import ApiError
from aval.api.operator_auth import require_operator
from aval.domain.entities import Reservation
from aval.domain.money import Money
from aval.infrastructure.sqlite.audit_ledger import SqliteAuditLedger
from aval.infrastructure.sqlite.ledger_repository import SqliteLedgerRepository
from aval.infrastructure.sqlite.transaction import run_in_write_transaction

ROGUE_FLAG = "AVAL_DEMO_ROGUE"


def rogue_charges_enabled() -> bool:
    return os.environ.get(ROGUE_FLAG, "").strip() not in ("", "0", "false", "False")


class RogueChargeRequest(BaseModel):
    mandate_id: str = Field(min_length=1)
    minor_units: int = Field(gt=0)
    merchant_id: str = "unknown_merchant"


def create_demo_rogue_router() -> APIRouter:
    router = APIRouter(tags=["demo"])

    @router.post(
        "/admin/demo/rogue-charge",
        status_code=status.HTTP_201_CREATED,
        dependencies=[Depends(require_operator)],
    )
    def rogue_charge(request: Request, body: RogueChargeRequest) -> dict[str, Any]:
        """Settle money against a mandate without asking the mandate.

        No authorization is evaluated and no proof is issued — that is the whole point.
        What is written is a settled reservation and one trail line saying where it came
        from, so the auditor sees a charge nobody in this system authorized.
        """
        runtime = runtime_of(request)
        mandate = runtime.core.mandate(body.mandate_id)
        if mandate is None:
            raise ApiError(404, "mandate_not_found", "Mandato não encontrado.")
        amount = Money(body.minor_units, mandate.limit.currency, mandate.limit.scale)

        def operation(connection) -> str:
            ledger = SqliteLedgerRepository(connection)
            reservation = Reservation(
                id=f"rsv_{uuid4().hex}",
                mandate_id=mandate.id,
                checkout_intent_id=f"chk_rogue_{uuid4().hex[:8]}",
                amount=amount,
            )
            ledger.save(reservation, merchant_id=body.merchant_id)
            charged = reservation.commit(f"rogue_{uuid4().hex}").settle()
            ledger.update(charged, at=runtime.clock.now())
            SqliteAuditLedger(connection).append(
                mandate_id=mandate.id,
                event_type="charge_outside_aval",
                human_summary="Cobrança feita fora desta camada: nenhum mandato foi consultado.",
                actor="agent_operator:rogue",
                detail={
                    "reservation_id": charged.id,
                    "merchant_id": body.merchant_id,
                    "amount_minor_units": amount.minor_units,
                    "currency": amount.currency,
                    "scale": amount.scale,
                },
                occurred_at=runtime.clock.now(),
            )
            return charged.id

        return {
            "reservation_id": run_in_write_transaction(runtime.engine, operation),
            "note": "Nenhuma prova de autorização foi emitida: esta cobrança não passou pelo núcleo.",
        }

    return router
