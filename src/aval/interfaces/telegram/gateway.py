"""The only seam between the bot and AVAL.

The bot never touches the database, the ledger or policy — it reads and writes
through this port. While the backend is under construction the port resolves to
``MockGateway``; setting ``AVAL_API_BASE_URL`` swaps in ``HttpGateway`` with no
change to the handlers. The HTTP paths live in ``ENDPOINTS`` so wiring the real
API is a one-line edit per route.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol
import json
import urllib.error
import urllib.parse
import urllib.request

from aval.interfaces.telegram.config import BotConfig


class GatewayError(Exception):
    """The backend refused or was unreachable. Never downgraded to a success."""


@dataclass(frozen=True)
class MoneyView:
    minor_units: int
    currency: str
    scale: int


@dataclass(frozen=True)
class MandateView:
    id: str
    principal: str
    agent: str
    status: str
    limit: MoneyView
    spent: MoneyView
    merchants: tuple[str, ...]
    expires_at: datetime
    policy_version: int
    revocation_epoch: int


@dataclass(frozen=True)
class ApprovalView:
    id: str
    mandate_id: str
    merchant: str
    item: str
    amount: MoneyView
    reason_code: str
    human_summary: str
    created_at: datetime


@dataclass(frozen=True)
class ActivityView:
    id: str
    mandate_id: str
    event_type: str
    human_summary: str
    occurred_at: datetime


@dataclass(frozen=True)
class ActionResult:
    ok: bool
    message: str


class AvalGateway(Protocol):
    def health(self) -> str: ...
    def list_mandates(self) -> Sequence[MandateView]: ...
    def get_mandate(self, mandate_id: str) -> MandateView | None: ...
    def list_pending_approvals(self) -> Sequence[ApprovalView]: ...
    def resolve_approval(
        self, approval_id: str, *, approve: bool, actor: str, idempotency_key: str
    ) -> ActionResult: ...
    def revoke(
        self, mandate_id: str, *, scope: str, reason: str, actor: str, idempotency_key: str
    ) -> ActionResult: ...
    def activity(self, mandate_id: str | None = None, limit: int = 10) -> Sequence[ActivityView]: ...


# HTTP contract expected from the AVAL API, documented in
# docs/contracts/aval-telegram-gateway.md. When the backend lands, adjust these
# paths (and the JSON readers below) instead of touching any handler.
ENDPOINTS = {
    "health": "/health",
    "mandates": "/v1/mandates",
    "mandate": "/v1/mandates/{mandate_id}",
    "revocations": "/v1/mandates/{mandate_id}/revocations",
    "approvals": "/v1/escalations",
    "approval_decision": "/v1/escalations/{approval_id}/decision",
    "activity": "/v1/audit-events",
}


class HttpGateway:
    """Talks to the AVAL API over HTTP. Stdlib only, and it owns no state."""

    def __init__(self, config: BotConfig, *, opener: Any | None = None) -> None:
        if config.api_base_url is None:
            raise GatewayError("HttpGateway requires AVAL_API_BASE_URL")
        self._base_url = config.api_base_url
        self._token = config.api_token
        self._timeout = config.request_timeout_seconds
        self._opener = opener or urllib.request.urlopen

    def health(self) -> str:
        return str(self._request("GET", ENDPOINTS["health"]).get("status", "unknown"))

    def list_mandates(self) -> Sequence[MandateView]:
        payload = self._request("GET", ENDPOINTS["mandates"])
        return tuple(_mandate_from_json(item) for item in payload.get("mandates", []))

    def get_mandate(self, mandate_id: str) -> MandateView | None:
        try:
            payload = self._request("GET", ENDPOINTS["mandate"].format(mandate_id=mandate_id))
        except GatewayError as error:
            if "404" in str(error):
                return None
            raise
        return _mandate_from_json(payload)

    def list_pending_approvals(self) -> Sequence[ApprovalView]:
        payload = self._request("GET", ENDPOINTS["approvals"], query={"status": "pending"})
        return tuple(_approval_from_json(item) for item in payload.get("escalations", []))

    def resolve_approval(
        self, approval_id: str, *, approve: bool, actor: str, idempotency_key: str
    ) -> ActionResult:
        payload = self._request(
            "POST",
            ENDPOINTS["approval_decision"].format(approval_id=approval_id),
            body={"decision": "approve" if approve else "deny", "actor": actor},
            idempotency_key=idempotency_key,
        )
        return ActionResult(bool(payload.get("ok", True)), str(payload.get("human_summary", "")))

    def revoke(
        self, mandate_id: str, *, scope: str, reason: str, actor: str, idempotency_key: str
    ) -> ActionResult:
        payload = self._request(
            "POST",
            ENDPOINTS["revocations"].format(mandate_id=mandate_id),
            body={"scope": scope, "reason": reason, "actor": actor},
            idempotency_key=idempotency_key,
        )
        return ActionResult(bool(payload.get("ok", True)), str(payload.get("human_summary", "")))

    def activity(self, mandate_id: str | None = None, limit: int = 10) -> Sequence[ActivityView]:
        query: dict[str, str] = {"limit": str(limit)}
        if mandate_id:
            query["mandate_id"] = mandate_id
        payload = self._request("GET", ENDPOINTS["activity"], query=query)
        return tuple(_activity_from_json(item) for item in payload.get("events", []))

    def _request(
        self,
        method: str,
        path: str,
        *,
        query: Mapping[str, str] | None = None,
        body: Mapping[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        url = f"{self._base_url}{path}"
        if query:
            url = f"{url}?{urllib.parse.urlencode(query)}"
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(url, data=data, method=method)
        request.add_header("Accept", "application/json")
        if data is not None:
            request.add_header("Content-Type", "application/json")
        if self._token:
            request.add_header("Authorization", f"Bearer {self._token}")
        if idempotency_key:
            request.add_header("Idempotency-Key", idempotency_key)
        try:
            with self._opener(request, timeout=self._timeout) as response:
                raw = response.read()
        except urllib.error.HTTPError as error:
            raise GatewayError(f"AVAL API returned {error.code} for {method} {path}") from error
        except OSError as error:
            raise GatewayError(f"AVAL API unreachable: {error}") from error
        if not raw:
            return {}
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as error:
            raise GatewayError(f"AVAL API returned malformed JSON for {method} {path}") from error
        return payload if isinstance(payload, dict) else {"items": payload}


def _money_from_json(payload: Mapping[str, Any]) -> MoneyView:
    return MoneyView(int(payload["minor_units"]), str(payload["currency"]), int(payload["scale"]))


def _instant(value: Any) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _mandate_from_json(payload: Mapping[str, Any]) -> MandateView:
    limit = _money_from_json(payload["limit"])
    spent = _money_from_json(payload["spent"]) if "spent" in payload else replace(limit, minor_units=0)
    return MandateView(
        id=str(payload["id"]),
        principal=str(payload.get("principal", "—")),
        agent=str(payload.get("agent", "—")),
        status=str(payload.get("status", "UNKNOWN")),
        limit=limit,
        spent=spent,
        merchants=tuple(str(item) for item in payload.get("allowed_merchant_ids", ())),
        expires_at=_instant(payload["expires_at"]),
        policy_version=int(payload.get("policy_version", 1)),
        revocation_epoch=int(payload.get("revocation_epoch", 0)),
    )


def _approval_from_json(payload: Mapping[str, Any]) -> ApprovalView:
    return ApprovalView(
        id=str(payload["id"]),
        mandate_id=str(payload["mandate_id"]),
        merchant=str(payload.get("merchant_id", "—")),
        item=str(payload.get("item", "—")),
        amount=_money_from_json(payload["amount"]),
        reason_code=str(payload.get("reason_code", "awaiting_human")),
        human_summary=str(payload.get("human_summary", "")),
        created_at=_instant(payload.get("created_at", datetime.now(timezone.utc).isoformat())),
    )


def _activity_from_json(payload: Mapping[str, Any]) -> ActivityView:
    return ActivityView(
        id=str(payload["id"]),
        mandate_id=str(payload.get("mandate_id", "—")),
        event_type=str(payload.get("event_type", "event")),
        human_summary=str(payload.get("human_summary", "")),
        occurred_at=_instant(payload.get("occurred_at", datetime.now(timezone.utc).isoformat())),
    )


class MockGateway:
    """Fixtures for the demo while the backend is being built.

    Marked mock on purpose: it holds no policy of its own, it only replays the
    shapes the real API will return so the Telegram surface can be finished and
    rehearsed today.
    """

    def __init__(self, *, now: datetime | None = None) -> None:
        moment = now or datetime.now(timezone.utc)
        brl = {"currency": "BRL", "scale": 2}
        self._mandates: dict[str, MandateView] = {
            "mnd_marta_01": MandateView(
                id="mnd_marta_01",
                principal="Marta Ribeiro",
                agent="agent://shopper.aval.dev",
                status="ACTIVE",
                limit=MoneyView(250_000, **brl),
                spent=MoneyView(87_400, **brl),
                merchants=("mrc_zenith", "mrc_lumen"),
                expires_at=moment + timedelta(days=27),
                policy_version=3,
                revocation_epoch=1,
            ),
            "mnd_marta_02": MandateView(
                id="mnd_marta_02",
                principal="Marta Ribeiro",
                agent="agent://groceries.aval.dev",
                status="ACTIVE",
                limit=MoneyView(60_000, **brl),
                spent=MoneyView(59_100, **brl),
                merchants=("mrc_hortifruti",),
                expires_at=moment + timedelta(days=6),
                policy_version=1,
                revocation_epoch=0,
            ),
        }
        self._approvals: dict[str, ApprovalView] = {
            "esc_9f21": ApprovalView(
                id="esc_9f21",
                mandate_id="mnd_marta_01",
                merchant="mrc_orion",
                item="Monitor 27\" UltraSharp",
                amount=MoneyView(189_900, **brl),
                reason_code="merchant_out_of_scope",
                human_summary="Merchant fora do escopo do mandato; aprovação humana necessária.",
                created_at=moment - timedelta(minutes=4),
            ),
            "esc_be07": ApprovalView(
                id="esc_be07",
                mandate_id="mnd_marta_02",
                merchant="mrc_hortifruti",
                item="Cesta semanal",
                amount=MoneyView(12_800, **brl),
                reason_code="budget_exceeded",
                human_summary="Compra excede o orçamento vivo do mandato.",
                created_at=moment - timedelta(minutes=1),
            ),
        }
        self._activity: list[ActivityView] = [
            ActivityView(
                id="aud_0003",
                mandate_id="mnd_marta_01",
                event_type="capture.committed",
                human_summary="Captura liquidada. Zenith Store, R$ 412,00.",
                occurred_at=moment - timedelta(hours=2),
            ),
            ActivityView(
                id="aud_0002",
                mandate_id="mnd_marta_01",
                event_type="capture.declined",
                human_summary="Captura recusada. Merchant fora do escopo.",
                occurred_at=moment - timedelta(hours=5),
            ),
            ActivityView(
                id="aud_0001",
                mandate_id="mnd_marta_02",
                event_type="mandate.issued",
                human_summary="Mandato emitido com autoridade de revogação registrada.",
                occurred_at=moment - timedelta(days=1),
            ),
        ]
        self._resolved: dict[str, ActionResult] = {}
        self._now = lambda: datetime.now(timezone.utc)

    def health(self) -> str:
        return "mock"

    def list_mandates(self) -> Sequence[MandateView]:
        return tuple(self._mandates.values())

    def get_mandate(self, mandate_id: str) -> MandateView | None:
        return self._mandates.get(mandate_id)

    def list_pending_approvals(self) -> Sequence[ApprovalView]:
        return tuple(self._approvals.values())

    def resolve_approval(
        self, approval_id: str, *, approve: bool, actor: str, idempotency_key: str
    ) -> ActionResult:
        if idempotency_key in self._resolved:
            return self._resolved[idempotency_key]
        approval = self._approvals.pop(approval_id, None)
        if approval is None:
            return ActionResult(False, "Essa aprovação já foi resolvida ou não existe.")
        verb = "aprovada" if approve else "recusada"
        result = ActionResult(True, f"Compra {verb} por {actor}.")
        self._resolved[idempotency_key] = result
        self._activity.insert(
            0,
            ActivityView(
                id=f"aud_{approval_id}",
                mandate_id=approval.mandate_id,
                event_type="escalation.approved" if approve else "escalation.denied",
                human_summary=result.message,
                occurred_at=self._now(),
            ),
        )
        return result

    def revoke(
        self, mandate_id: str, *, scope: str, reason: str, actor: str, idempotency_key: str
    ) -> ActionResult:
        if idempotency_key in self._resolved:
            return self._resolved[idempotency_key]
        mandate = self._mandates.get(mandate_id)
        if mandate is None:
            return ActionResult(False, "Mandato não encontrado.")
        if scope == "mandate":
            mandate = replace(mandate, status="REVOKED")
            message = "Mandato revogado. Nenhuma captura nova será autorizada."
        else:
            message = f"Escopo {scope} revogado para este mandato."
        mandate = replace(mandate, revocation_epoch=mandate.revocation_epoch + 1)
        self._mandates[mandate_id] = mandate
        result = ActionResult(True, message)
        self._resolved[idempotency_key] = result
        self._activity.insert(
            0,
            ActivityView(
                id=f"aud_rev_{mandate.revocation_epoch}",
                mandate_id=mandate_id,
                event_type="mandate.revoked",
                human_summary=f"{message} Motivo: {reason} ({actor}).",
                occurred_at=self._now(),
            ),
        )
        return result

    def activity(self, mandate_id: str | None = None, limit: int = 10) -> Sequence[ActivityView]:
        events = [item for item in self._activity if mandate_id is None or item.mandate_id == mandate_id]
        return tuple(events[:limit])


def build_gateway(config: BotConfig) -> AvalGateway:
    """Mock until the backend exists; HTTP the moment AVAL_API_BASE_URL is set."""
    return MockGateway() if config.uses_mock_gateway else HttpGateway(config)
