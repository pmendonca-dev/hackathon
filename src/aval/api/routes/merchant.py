"""The merchant side: what is for sale, and whether a purchase really was authorized.

The five checks answer the merchant's actual question — *may I hand over the goods* —
and nothing else. Notice what the answer does not contain: no mandate, no buyer, no
budget. A merchant that had to learn who is buying in order to trust the purchase
would make the mandate pointless.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from aval.api.dependencies import runtime_of
from aval.api.errors import ApiError
from aval.api.offer_binding import offer_claims
from aval.merchant.offers import terms_hash_of

router = APIRouter(tags=["merchant"])


class VerifyRequest(BaseModel):
    authorization_proof: str = Field(min_length=1)
    merchant_authorization: str = Field(min_length=1)


def _check(name: str, passed: bool, note: str) -> dict[str, Any]:
    return {"name": name, "passed": passed, "note": note}


@router.get("/merchant/offers")
def list_offers(request: Request) -> dict[str, Any]:
    return {"offers": runtime_of(request).offers.catalog()}


@router.get("/merchant/.well-known/jwks.json")
def merchant_jwks(request: Request) -> dict[str, Any]:
    """Published so the merchant signature can be checked by anyone, offline."""
    return runtime_of(request).offers.public_jwks()


@router.get("/.well-known/jwks.json")
def aval_jwks(request: Request) -> dict[str, Any]:
    """AVAL's authorization key. A merchant can verify a proof without asking us."""
    from aval.runtime import PROOF_KID

    return {"keys": [runtime_of(request).custody.public_jwk(PROOF_KID)]}


@router.post("/merchant/verify")
def verify(request: Request, body: VerifyRequest) -> dict[str, Any]:
    runtime = runtime_of(request)
    checks: list[dict[str, Any]] = []

    claims = offer_claims(body.merchant_authorization, runtime)
    checks.append(_check("offer_signature_valid", True, "ES256 · chave do merchant"))

    now = runtime.clock.now()
    try:
        not_after = datetime.fromisoformat(str(claims["not_after"]))
        within_validity = now < not_after
    except (KeyError, TypeError, ValueError):
        within_validity = False
    checks.append(
        _check(
            "offer_within_validity",
            within_validity,
            "dentro da janela" if within_validity else "oferta vencida",
        )
    )

    proof: dict[str, Any] | None = None
    try:
        proof = runtime.proofs.verify_and_consume(body.authorization_proof)
        checks.append(_check("authorization_proof_valid", True, "ES256 · chave do AVAL"))
    except ValueError as error:
        checks.append(_check("authorization_proof_valid", False, str(error)))

    if proof is None:
        checks.append(_check("terms_hash_matches", False, "sem prova para comparar"))
        checks.append(_check("authority_still_valid", False, "sem prova para consultar"))
        return {"accepted": False, "checks": checks, "merchant_id": claims.get("merchant_id")}

    # The proof names an amount, a merchant and a terms hash. All three have to be the
    # ones this offer carries, or the proof belongs to some other purchase.
    offered = claims.get("total", {})
    bound = (
        proof.get("terms_hash") == terms_hash_of(claims)
        and proof.get("merchant_id") == claims.get("merchant_id")
        and proof.get("amount_minor_units") == offered.get("minor_units")
        and proof.get("currency") == offered.get("currency")
    )
    checks.append(
        _check(
            "terms_hash_matches",
            bound,
            "a prova cobre esta oferta" if bound else "a prova é de outra compra",
        )
    )

    state = runtime.core.reservation_authority_state(str(proof.get("reservation_id", "")))
    if state is None:
        checks.append(_check("authority_still_valid", False, "reserva desconhecida"))
    else:
        still_valid = (
            not state["revoked"]
            and not state["expired"]
            and state["epoch"] == proof.get("revocation_epoch")
            and state["policy_version"] == proof.get("policy_version")
        )
        note = "autoridade vigente"
        if state["revoked"]:
            note = "mandato revogado"
        elif state["expired"]:
            note = "mandato expirado"
        elif not still_valid:
            note = "política mudou depois da prova"
        checks.append(_check("authority_still_valid", still_valid, note))

    accepted = all(check["passed"] for check in checks)
    if not claims.get("merchant_id"):
        raise ApiError(409, "offer_malformed", "Oferta sem merchant.")
    return {
        "accepted": accepted,
        "checks": checks,
        "merchant_id": claims.get("merchant_id"),
        "offer_id": claims.get("offer_id"),
        "amount": claims.get("total"),
        # Present so the merchant can quote the decision it relied on, and absent of
        # everything it is not entitled to.
        "decision_handle": proof.get("jti"),
    }
