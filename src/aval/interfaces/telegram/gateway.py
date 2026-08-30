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
    # How often the agent may act, and how much of that window it has already used.
    max_uses: int | None = None
    window_seconds: int | None = None
    uses_in_window: int = 0
    # The card the mandate names, as four digits. The token behind it is never served.
    instrument_label: str | None = None
    instrument_revoked: bool = False


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
class WatchView:
    """A standing order, and what happened when it stopped waiting."""

    id: str
    instruction: str
    status: str
    outcome: str | None
    expires_at: datetime
    # Absent while it is still watching, and when it expired without ever asking.
    purchase: "PurchaseView | None" = None


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
class CardSessionView:
    """A card registration in progress: a page to open, and an id to watch."""

    session_id: str
    url: str


@dataclass(frozen=True)
class AgentProfileView:
    """Who the agent is, as an identity of its own.

    The case keeps the agent's identity separate from the human's, and the two are
    separate here down to the key: the agent signs its requests with `kid`, the person
    signs their decisions with theirs. Neither can produce the other's signature.
    """

    agent_id: str
    kid: str
    trusted: bool
    profile_url: str | None


@dataclass(frozen=True)
class ChainView:
    """The hash chain behind the trail, as the core itself verified it."""

    intact: bool
    checked: int
    broken_at: int | None


@dataclass(frozen=True)
class DisputeView:
    """A denial, and what the trail answered back.

    `MANDATE_HELD` means an authorization proof binds this purchase to this
    mandate; `MANDATE_FAILED` means nothing does. The bot never picks a side —
    it repeats the verdict the ledger produced.
    """

    id: str
    status: str
    resolution: str | None


@dataclass(frozen=True)
class ReceiptView:
    mandate: MandateView
    entries: tuple[LedgerEntryView, ...]
    chain: ChainView | None = None


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
    "watches": "/agent/watches",
    "watch_tick": "/agent/watches/tick",
    "offers": "/merchant/offers",
    "agent_profile": "/agent/profile",
    "card_session": "/mandates/{mandate_id}/instrument/session",
    "card_session_read": "/mandates/{mandate_id}/instrument/session/{session_id}",
    "instrument": "/mandates/{mandate_id}/instrument",
    "disputes": "/disputes",
    "dispute_resolution": "/disputes/{dispute_id}/resolution",
    "ledger_verify": "/ledger/verify",
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
        return ReceiptView(_mandate(payload["mandate"]), tuple(entries[:limit]), self.verify(mandate_id))

    def verify(self, mandate_id: str) -> ChainView | None:
        """Ask the core whether its own trail still hashes.

        A statement nobody checked is a claim. Returning None when the check itself
        is unreachable keeps the receipt honest: it then says nothing rather than
        implying an integrity it never confirmed.
        """
        try:
            payload = self._call("GET", ENDPOINTS["ledger_verify"], query={"mandate_id": mandate_id})
        except GatewayError:
            return None
        broken = payload.get("broken_at")
        return ChainView(
            intact=bool(payload.get("intact")),
            checked=int(payload.get("checked", 0)),
            broken_at=None if broken is None else int(broken),
        )

    def agent_profile(self) -> AgentProfileView | None:
        try:
            payload = self._call("GET", ENDPOINTS["agent_profile"])
        except GatewayError:
            return None
        return AgentProfileView(
            agent_id=str(payload.get("agent_id", "—")),
            kid=str(payload.get("kid", "—")),
            trusted=bool(payload.get("trusted")),
            profile_url=payload.get("profile_url"),
        )

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
        card_number: str | None = None,
        max_uses: int | None = None,
        usage_window: timedelta | None = None,
    ) -> tuple[str, str | None]:
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
                **(
                    {}
                    if max_uses is None or usage_window is None
                    else {
                        "usage_limit": {
                            "max_uses": max_uses,
                            "window_seconds": int(usage_window.total_seconds()),
                        }
                    }
                ),
                "expires_at": (datetime.now(UTC) + valid_for).isoformat(),
                # The number is typed here and forgotten there. What comes back is a
                # token the agent may present and four digits the holder recognises.
                **(
                    {} if not card_number else {"payment_method": {"card_number": card_number}}
                ),
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
        return str(payload["mandate_id"]), payload.get("instrument_revocation_scope")

    def purchase(self, mandate_id: str, instruction: str) -> PurchaseView:
        return _purchase(
            self._call(
                "POST",
                ENDPOINTS["purchase"],
                body={"mandate_id": mandate_id, "instruction": instruction},
            )
        )

    def register_watch(self, mandate_id: str, instruction: str) -> WatchView:
        """Start watching. Registering authorizes nothing — firing still asks the core."""
        return _watch(
            self._call(
                "POST",
                ENDPOINTS["watches"],
                body={"mandate_id": mandate_id, "instruction": instruction},
            )
        )

    def open_watches(self, mandate_id: str) -> Sequence[WatchView]:
        payload = self._call("GET", ENDPOINTS["watches"], query={"mandate_id": mandate_id})
        return tuple(
            _watch(item) for item in payload.get("watches", []) if item.get("status") == "OPEN"
        )

    def tick_watches(self, mandate_id: str) -> Sequence[WatchView]:
        """Give every open watch one try. Returns only the ones that stopped waiting."""
        payload = self._call("POST", ENDPOINTS["watch_tick"], body={"mandate_id": mandate_id})
        return tuple(_watch(item) for item in payload.get("fired", []))

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

    # ── card registration ──────────────────────────────────────────────────
    def open_card_session(self, identity: ChatIdentity, mandate_id: str) -> CardSessionView:
        """Ask AVAL for the processor's own card form. The bot never sees a number."""
        payload = self._call(
            "POST",
            ENDPOINTS["card_session"].format(mandate_id=mandate_id),
            body={
                "authorization_jws": self._identities.sign(
                    identity, {"mandate_id": mandate_id, "scope": "instrument_session"}
                )
            },
        )
        return CardSessionView(str(payload["session_id"]), str(payload["url"]))

    def read_card_session(
        self, identity: ChatIdentity, mandate_id: str, session_id: str
    ) -> tuple[str, str] | None:
        """The registered card as (token, label), or None while the form is still open."""
        payload = self._call(
            "GET",
            ENDPOINTS["card_session_read"].format(
                mandate_id=mandate_id, session_id=session_id
            ),
            query={
                "authorization_jws": self._identities.sign(
                    identity, {"mandate_id": mandate_id, "scope": "instrument_session"}
                )
            },
        )
        if not payload.get("ready"):
            return None
        return str(payload["token"]), str(payload["label"])

    def bind_instrument(
        self,
        identity: ChatIdentity,
        mandate_id: str,
        *,
        token: str,
        label: str,
        supersedes: str | None,
    ) -> str:
        """Name the registered card on the mandate, signed by the person who registered it.

        `supersedes` is the compare-and-swap: it names the card bound right now, so a
        captured binding cannot be replayed to bring back a card already replaced.
        """
        payload = self._call(
            "POST",
            ENDPOINTS["instrument"].format(mandate_id=mandate_id),
            body={
                "token": token,
                "label": label,
                "authorization_jws": self._identities.sign(
                    identity,
                    {
                        "mandate_id": mandate_id,
                        "scope": "instrument",
                        "instrument_token": token,
                        "instrument_label": label,
                        "supersedes": supersedes,
                    },
                ),
            },
        )
        return str(payload["instrument_label"])

    def open_dispute(self, reservation_id: str, reason: str) -> DisputeView:
        """A later denial, answered by the trail rather than by trust.

        Opening and resolving are one gesture here on purpose. The resolution reads
        the ledger and nothing else, so there is nobody to wait for — leaving the
        dispute open would only mean showing the person a promise instead of an answer.
        """
        opened = self._call(
            "POST", ENDPOINTS["disputes"], body={"reservation_id": reservation_id, "reason": reason}
        )
        dispute_id = str(opened.get("dispute_id", ""))
        try:
            resolved = self._call(
                "POST", ENDPOINTS["dispute_resolution"].format(dispute_id=dispute_id)
            )
        except GatewayError:
            # Opened but unresolved is a real state, not a failure to hide: the
            # denial is registered and the verdict is simply not in yet.
            return DisputeView(dispute_id, str(opened.get("status", "OPEN")), None)
        return DisputeView(
            dispute_id,
            str(resolved.get("status", "OPEN")),
            resolved.get("resolution"),
        )

    def revoke(self, identity: ChatIdentity, mandate_id: str, *, epoch: int, reason: str) -> str:
        token = self._identities.sign(
            identity,
            {"mandate_id": mandate_id, "scope": "mandate", "reason": reason, "epoch": epoch + 1},
        )
        payload = self._call(
            "POST", ENDPOINTS["revocation"].format(mandate_id=mandate_id), body={"token": token}
        )
        return f"Mandato revogado (epoch {payload.get('epoch', epoch + 1)})."

    def cancel_instrument(
        self, identity: ChatIdentity, mandate_id: str, *, scope: str, epoch: int
    ) -> str:
        """End the card without ending the agent.

        Authority and payment are separate things, so they are revoked separately: the
        mandate stays active, the budget stays where it was, and the next purchase is
        refused for the reason that is actually true.
        """
        token = self._identities.sign(
            identity,
            {
                "mandate_id": mandate_id,
                "scope": scope,
                "reason": "cartão cancelado pelo titular",
                "epoch": epoch + 1,
            },
        )
        payload = self._call(
            "POST", ENDPOINTS["revocation"].format(mandate_id=mandate_id), body={"token": token}
        )
        return (
            "Cartão cancelado. O mandato segue ativo — o agente pode decidir, "
            f"mas não tem com o que pagar (epoch {payload.get('epoch', epoch + 1)})."
        )

    def replace_limit(self, identity: ChatIdentity, mandate_id: str, limit: MoneyView) -> str:
        # The live version is read first because the signature has to name it: a token
        # that did not would stay valid forever, and could be replayed to restore a
        # limit the holder had already lowered.
        current = self.mandate(mandate_id)
        if current is None:
            raise GatewayError("mandate_not_found", "Mandato não encontrado.")
        authorization_jws = self._identities.sign(
            identity,
            {
                "mandate_id": mandate_id,
                "limit_minor_units": limit.minor_units,
                "currency": limit.currency,
                "scale": limit.scale,
                "policy_version": current.policy_version,
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
    usage = payload.get("usage_limit") or {}
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
        instrument_label=payload.get("instrument_label"),
        instrument_revoked=bool(payload.get("instrument_revoked", False)),
        max_uses=None if not usage else int(usage["max_uses"]),
        window_seconds=None if not usage else int(usage["window_seconds"]),
        uses_in_window=int(payload.get("uses_in_window", 0)),
    )


def _purchase(payload: Mapping[str, Any]) -> PurchaseView:
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


def _watch(payload: Mapping[str, Any]) -> WatchView:
    purchase = payload.get("purchase")
    return WatchView(
        id=str(payload["watch_id"]),
        instruction=str(payload.get("instruction", "")),
        status=str(payload.get("status", "OPEN")),
        outcome=payload.get("outcome"),
        expires_at=_instant(payload["expires_at"]),
        purchase=None if not isinstance(purchase, Mapping) else _purchase(purchase),
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
