"""The bot's only door into AVAL.

Every path below is an HTTP call to the running API. The bot holds no policy, no
balance and no revocation state — it renders what the core answers and forwards
what the human decides. Nothing here re-implements a rule; if a decision ever
appears in this file, it is in the wrong place.

The three privileged writes — approve, revoke, move the limit — carry a JWS
signed by the chat's own holder key. The server never signs on the human's
behalf, which is what makes the later "I never authorized this" answerable.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
import json
import urllib.error
import urllib.parse
import urllib.request

from aval.interfaces.telegram.identity import ChatIdentity, IdentityStore


class GatewayError(Exception):
    """AVAL refused or was unreachable. Never downgraded into a success."""

    def __init__(self, message: str, *, reason_code: str = "gateway_error") -> None:
        super().__init__(message)
        self.reason_code = reason_code


@dataclass(frozen=True)
class MoneyView:
    minor_units: int
    currency: str
    scale: int


@dataclass(frozen=True)
class MandateView:
    id: str
    status: str
    principal: str
    merchants: tuple[str, ...]
    categories: tuple[str, ...]
    limit: MoneyView
    ceiling: MoneyView | None
    spent: MoneyView
    remaining: MoneyView
    expires_at: datetime
    policy_version: int
    revocation_epoch: int


@dataclass(frozen=True)
class EscalationView:
    id: str
    mandate_id: str
    merchant: str
    category: str
    amount: MoneyView
    reason_code: str
    status: str
    created_at: datetime
    expires_at: datetime


@dataclass(frozen=True)
class PurchaseView:
    """What the agent managed to do with one free-text instruction."""

    outcome: str
    reason_code: str
    human_summary: str
    title: str | None
    amount: MoneyView | None
    escalation_id: str | None
    reservation_id: str | None
    settlement_reference: str | None
    proposed_by: str = "rules"
    rationale: str | None = None


@dataclass(frozen=True)
class OfferView:
    sku: str
    title: str
    total: MoneyView
    category: str


@dataclass(frozen=True)
class LedgerEntryView:
    sequence: int
    event_type: str
    human_summary: str
    occurred_at: datetime


@dataclass(frozen=True)
class ReceiptView:
    mandate: MandateView
    entries: tuple[LedgerEntryView, ...]


# Paths as the running API exposes them; `GET /docs` on the instance is the live
# reference. Change them here, never in a handler.
ENDPOINTS = {
    "health": "/health",
    "mandates": "/mandates",
    "mandate": "/mandates/{mandate_id}",
    "limit": "/mandates/{mandate_id}/limit",
    "revocation": "/mandates/{mandate_id}/revocation",
    "escalations": "/escalations",
    "escalation": "/escalations/{escalation_id}",
    "decision": "/escalations/{escalation_id}/decision",
    "ledger": "/ledger",
    "purchase": "/agent/purchase",
    "offers": "/merchant/offers",
    "disputes": "/disputes",
}


class AvalGateway:
    """Stdlib HTTP client for the AVAL API."""

    def __init__(
        self,
        base_url: str,
        *,
        identities: IdentityStore,
        timeout: int = 15,
        opener: Any | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._identities = identities
        self._timeout = timeout
        self._opener = opener or urllib.request.urlopen

    # ── reads ──────────────────────────────────────────────────────────────
    def health(self) -> str:
        return str(self._call("GET", ENDPOINTS["health"]).get("status", "unknown"))

    def mandate(self, mandate_id: str) -> MandateView | None:
        try:
            payload = self._call("GET", ENDPOINTS["mandate"].format(mandate_id=mandate_id))
        except GatewayError as error:
            if error.reason_code == "mandate_not_found":
                return None
            raise
        return _mandate(payload)

    def open_escalations(self, mandate_id: str) -> Sequence[EscalationView]:
        payload = self._call("GET", ENDPOINTS["escalations"], query={"mandate_id": mandate_id})
        return tuple(_escalation(item) for item in payload.get("escalations", []))

    def escalation(self, escalation_id: str) -> EscalationView | None:
        try:
            payload = self._call("GET", ENDPOINTS["escalation"].format(escalation_id=escalation_id))
        except GatewayError as error:
            if error.reason_code == "escalation_not_found":
                return None
            raise
        return _escalation(payload)

    def receipt(self, mandate_id: str, *, limit: int = 8) -> ReceiptView:
        payload = self._call(
            "GET", ENDPOINTS["ledger"], query={"mandate_id": mandate_id, "view": "human"}
        )
        entries = [_entry(item) for item in payload.get("entries", [])]
        entries.sort(key=lambda item: item.sequence, reverse=True)
        return ReceiptView(_mandate(payload["mandate"]), tuple(entries[:limit]))

    def catalogue(self) -> Sequence[OfferView]:
        payload = self._call("GET", ENDPOINTS["offers"])
        return tuple(
            OfferView(
                sku=str(item["item"]["sku"]),
                title=str(item["item"]["title"]),
                total=_money(item["total"]),
                category=str(item["item"]["category"]),
            )
            for item in payload.get("offers", [])
        )

    # ── writes ─────────────────────────────────────────────────────────────
    def create_mandate(
        self,
        identity: ChatIdentity,
        *,
        merchants: Sequence[str],
        categories: Sequence[str],
        limit: MoneyView,
        ceiling: MoneyView | None,
        valid_for: timedelta,
    ) -> str:
        payload = self._call(
            "POST",
            ENDPOINTS["mandates"],
            body={
                "principal": {
                    "id": identity.principal_id,
                    "display_name": identity.display_name,
                },
                "allowed_merchant_ids": list(merchants),
                "allowed_categories": list(categories),
                "limit": _money_body(limit),
                "ceiling": None if ceiling is None else _money_body(ceiling),
                "expires_at": (datetime.now(UTC) + valid_for).isoformat(),
                # The holder key lives in this bot, so the mandate is revocable by
                # the person who created it and by nobody else.
                "authorities": [
                    {
                        "id": f"ath_{identity.chat_id}",
                        "kid": identity.kid,
                        "role": "holder",
                        "public_jwk": self._identities.public_jwk(identity),
                        "allowed_scopes": ["mandate"],
                    }
                ],
            },
        )
        return str(payload["mandate_id"])

    def purchase(self, mandate_id: str, instruction: str) -> PurchaseView:
        payload = self._call(
            "POST", ENDPOINTS["purchase"], body={"mandate_id": mandate_id, "instruction": instruction}
        )
        offer = payload.get("offer") or {}
        item = offer.get("item") or {}
        return PurchaseView(
            outcome=str(payload.get("outcome", "unknown")),
            reason_code=str(payload.get("reason_code", "unknown")),
            human_summary=str(payload.get("human_summary", "")),
            title=item.get("title"),
            amount=_money(offer["total"]) if "total" in offer else None,
            escalation_id=payload.get("escalation_id"),
            reservation_id=payload.get("reservation_id"),
            settlement_reference=payload.get("settlement_reference"),
            proposed_by=str(payload.get("proposed_by", "rules")),
            rationale=payload.get("rationale"),
        )

    def decide(self, identity: ChatIdentity, escalation: EscalationView, *, approve: bool) -> str:
        """Sign the tap, then send it. The signature is the evidence, not the button."""
        decision = "approve" if approve else "deny"
        approval_jws = self._identities.sign(
            identity,
            {
                "decision_handle": escalation.id,
                "mandate_id": escalation.mandate_id,
                "amount_minor_units": escalation.amount.minor_units,
                "decision": decision,
                "decided_at": datetime.now(UTC).isoformat(),
            },
        )
        payload = self._call(
            "POST",
            ENDPOINTS["decision"].format(escalation_id=escalation.id),
            body={"decision": decision, "approval_jws": approval_jws},
        )
        capture = payload.get("capture") or {}
        if not approve:
            return "Compra negada. Nada foi cobrado."
        if capture.get("approved"):
            return "Compra aprovada e liquidada."
        # An approval is not a bypass: the core re-checks everything on resume.
        return f"Aprovação registrada, mas a compra não passou: {capture.get('reason_code', 'desconhecido')}."

    def open_dispute(self, reservation_id: str, reason: str) -> str:
        """A later denial, answered by the trail rather than by trust."""
        payload = self._call(
            "POST", ENDPOINTS["disputes"], body={"reservation_id": reservation_id, "reason": reason}
        )
        return f"Disputa {payload.get('dispute_id', '?')} aberta ({payload.get('status', 'OPEN')})."

    def revoke(self, identity: ChatIdentity, mandate_id: str, *, epoch: int, reason: str) -> str:
        token = self._identities.sign(
            identity,
            {"mandate_id": mandate_id, "scope": "mandate", "reason": reason, "epoch": epoch + 1},
        )
        payload = self._call(
            "POST", ENDPOINTS["revocation"].format(mandate_id=mandate_id), body={"token": token}
        )
        return f"Mandato revogado (epoch {payload.get('epoch', epoch + 1)})."

    def replace_limit(self, identity: ChatIdentity, mandate_id: str, limit: MoneyView) -> str:
        authorization_jws = self._identities.sign(
            identity,
            {
                "mandate_id": mandate_id,
                "limit_minor_units": limit.minor_units,
                "currency": limit.currency,
                "scale": limit.scale,
            },
        )
        payload = self._call(
            "PATCH",
            ENDPOINTS["limit"].format(mandate_id=mandate_id),
            body={"limit": _money_body(limit), "authorization_jws": authorization_jws},
        )
        return f"Limite alterado. Política v{payload.get('policy_version', '?')}."

    # ── transport ──────────────────────────────────────────────────────────
    def _call(
        self,
        method: str,
        path: str,
        *,
        query: Mapping[str, str] | None = None,
        body: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"{self._base_url}{path}"
        if query:
            url = f"{url}?{urllib.parse.urlencode(query)}"
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(url, data=data, method=method)
        request.add_header("Accept", "application/json")
        if data is not None:
            request.add_header("Content-Type", "application/json")
        try:
            with self._opener(request, timeout=self._timeout) as response:
                raw = response.read()
        except urllib.error.HTTPError as error:
            raise _from_http_error(error, method, path) from error
        except OSError as error:
            raise GatewayError(f"AVAL inacessível: {error}", reason_code="unreachable") from error
        if not raw:
            return {}
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as error:
            raise GatewayError("AVAL devolveu JSON inválido", reason_code="malformed") from error
        return payload if isinstance(payload, dict) else {"items": payload}


def _from_http_error(error: urllib.error.HTTPError, method: str, path: str) -> GatewayError:
    """Carry the core's own reason code out; it is already written for humans."""
    try:
        detail = json.loads(error.read() or b"{}")
    except (json.JSONDecodeError, ValueError):
        detail = {}
    reason = str(detail.get("reason_code") or f"http_{error.code}")
    summary = str(detail.get("human_summary") or f"{method} {path} devolveu {error.code}")
    return GatewayError(summary, reason_code=reason)


def _money(payload: Mapping[str, Any]) -> MoneyView:
    return MoneyView(int(payload["minor_units"]), str(payload["currency"]), int(payload["scale"]))


def _money_body(money: MoneyView) -> dict[str, Any]:
    return {"minor_units": money.minor_units, "currency": money.currency, "scale": money.scale}


def _instant(value: Any) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _mandate(payload: Mapping[str, Any]) -> MandateView:
    ceiling = payload.get("ceiling")
    return MandateView(
        id=str(payload["mandate_id"]),
        status=str(payload["status"]),
        principal=str((payload.get("principal") or {}).get("display_name", "—")),
        merchants=tuple(str(item) for item in payload.get("allowed_merchant_ids", ())),
        categories=tuple(str(item) for item in payload.get("allowed_categories", ())),
        limit=_money(payload["limit"]),
        ceiling=None if ceiling is None else _money(ceiling),
        spent=_money(payload["spent"]),
        remaining=_money(payload["remaining"]),
        expires_at=_instant(payload["expires_at"]),
        policy_version=int(payload.get("policy_version", 1)),
        revocation_epoch=int(payload.get("revocation_epoch", 0)),
    )


def _escalation(payload: Mapping[str, Any]) -> EscalationView:
    return EscalationView(
        id=str(payload["id"]),
        mandate_id=str(payload["mandate_id"]),
        merchant=str(payload.get("merchant_id", "—")),
        category=str(payload.get("category", "—")),
        amount=_money(payload["amount"]),
        reason_code=str(payload.get("reason_code", "awaiting_human")),
        status=str(payload.get("status", "OPEN")),
        created_at=_instant(payload["created_at"]),
        expires_at=_instant(payload["expires_at"]),
    )


def _entry(payload: Mapping[str, Any]) -> LedgerEntryView:
    return LedgerEntryView(
        sequence=int(payload.get("sequence", 0)),
        event_type=str(payload.get("event_type", "event")),
        human_summary=str(payload.get("human_summary", "")),
        occurred_at=_instant(payload["occurred_at"]),
    )
