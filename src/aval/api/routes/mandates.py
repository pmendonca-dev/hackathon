"""Mandate lifecycle: create, move the live limit, revoke.

The last two are the surfaces a judge touches during the trial by fire, so they
read and write straight through to the core. No cache sits in front of them.
"""

from __future__ import annotations

import base64
import json
from uuid import uuid4

from fastapi import APIRouter, Request, status

from aval.api.dependencies import runtime_of
from aval.api.errors import ApiError
from aval.application.authorization_core import ApprovalError
from aval.api.schemas import (
    CreateMandateRequest,
    CreateMandateResponse,
    ReplaceLimitRequest,
    ReplaceLimitResponse,
    RevocationRequest,
    RevocationResponse,
)
from aval.adapters.acp.delegate_payment import OpaqueTestCredentialTokenizer
from aval.domain.entities import (
    Mandate,
    PaymentInstrument,
    Principal,
    RevocationAuthority,
    UsageLimit,
)
from aval.domain.enums import RevocationRole

router = APIRouter(tags=["mandates"])

# The core raises ValueError with these exact sentences. Mapping them here keeps the
# vocabulary stable for callers without teaching the core about HTTP.
REVOCATION_REASONS = {
    "malformed revocation JWS": "revocation_malformed",
    "malformed compact JWS": "revocation_malformed",
    "unsupported compact JWS": "revocation_malformed",
    "invalid compact JWS signature": "revocation_signature_invalid",
    "revocation mandate does not match authority": "revocation_mandate_mismatch",
    "revocation scope is not allowed": "revocation_scope_not_allowed",
    "revocation payload is incomplete": "revocation_payload_incomplete",
    "unknown revocation authority": "revocation_authority_unknown",
    "only P-256 EC JWKs are supported": "revocation_key_unsupported",
    "invalid P-256 JWK": "revocation_key_unsupported",
}


def unverified_claims(token: str) -> dict:
    """Read the payload without trusting it. Used only to route the token to the
    mandate it names; the signature is checked by the core straight after."""
    try:
        encoded = token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
    except (IndexError, ValueError, json.JSONDecodeError) as error:
        raise ApiError(400, "revocation_malformed", "Token de revogação malformado.") from error
    if not isinstance(claims, dict):
        raise ApiError(400, "revocation_malformed", "Token de revogação malformado.")
    return claims


@router.post("/mandates", status_code=status.HTTP_201_CREATED, response_model=CreateMandateResponse)
def create_mandate(request: Request, body: CreateMandateRequest) -> CreateMandateResponse:
    runtime = runtime_of(request)
    if not body.creation_jws:
        raise ApiError(
            422,
            "mandate_creation_unsigned",
            "A criação do mandato exige a assinatura do titular.",
        )
    # Validity is time-dependent, so it is checked here rather than in the domain: the
    # entity has no clock, and a mandate created already expired would be accepted and
    # then refuse everything, which reads as the system being broken rather than as the
    # mistake it is.
    if body.expires_at <= runtime.clock.now():
        raise ApiError(422, "mandate_already_expired", "O mandato já nasceria expirado.")
    mandate_id = f"mandate_{uuid4().hex}"
    revocation_id = f"rev_{uuid4().hex}"
    try:
        roles = [RevocationRole(authority.role) for authority in body.authorities]
    except ValueError as error:
        raise ApiError(422, "unknown_revocation_role", "Papel de autoridade desconhecido.") from error

    # The card is read here and forgotten here. `instrument` carries a token and four
    # digits from this line onwards; the number itself is not stored, logged or passed
    # on, and the request object holding it dies with this call.
    instrument: PaymentInstrument | None = None
    if body.payment_method is not None:
        try:
            token = OpaqueTestCredentialTokenizer().tokenize(body.payment_method.card_number)
        except ValueError as error:
            raise ApiError(
                422, "payment_method_invalid", "Número de cartão inválido."
            ) from error
        instrument = PaymentInstrument(token, f"•••• {body.payment_method.card_number[-4:]}")
    mandate = Mandate(
        id=mandate_id,
        principal=Principal(id=body.principal.id, display_name=body.principal.display_name),
        allowed_merchant_ids=frozenset(body.allowed_merchant_ids),
        allowed_categories=frozenset(body.allowed_categories),
        limit=body.limit.to_money(),
        ceiling=None if body.ceiling is None else body.ceiling.to_money(),
        usage_limit=(
            None
            if body.usage_limit is None
            else UsageLimit(body.usage_limit.max_uses, body.usage_limit.window_seconds)
        ),
        instrument=instrument,
        expires_at=body.expires_at,
        policy_version=1,
        revocation_metadata={"revocation_id": revocation_id, "epoch": 0},
        authorities=tuple(
            # The row id is minted here: two mandates may name the same holder key, and
            # a caller-supplied id would collide on the second one.
            RevocationAuthority(
                id=f"ath_{uuid4().hex}",
                kid=authority.kid,
                role=role,
                public_jwk=dict(authority.public_jwk),
                # The instrument scope is added here rather than asked for, because the
                # token is minted a few lines above and the caller could not have named
                # it. A holder who authorized a card is by construction allowed to
                # cancel that card; anything narrower would be authority nobody holds.
                allowed_scopes=frozenset(authority.allowed_scopes)
                | (
                    {f"instrument:{instrument.token}"}
                    if instrument is not None and role is RevocationRole.HOLDER
                    else set()
                ),
            )
            for authority, role in zip(body.authorities, roles, strict=True)
        ),
    )
    try:
        runtime.core.register_mandate(mandate, creation_proof=body.creation_jws)
    except ApprovalError as error:
        raise ApiError(error.status_code, error.reason_code, error.human_summary) from error
    return CreateMandateResponse(
        mandate_id=mandate_id,
        policy_version=1,
        revocation_id=revocation_id,
        instrument_revocation_scope=(
            None if instrument is None else f"instrument:{instrument.token}"
        ),
    )


@router.post("/principals/{principal_id}/revocations")
def revoke_everything(request: Request, principal_id: str, body: RevocationRequest) -> dict:
    """The panic button: one signature ends every mandate that key is an authority on.

    The URL principal must match the signed one. Without that check a token could be
    walked from the principal it names onto another, which is the same class of bug the
    single-mandate route guards against by comparing `mandate_id`.

    An empty result is a refusal, not a no-op: a signature that revoked nothing either
    did not verify or names mandates this key holds no authority over, and answering
    200 would tell a frightened person their agent had been stopped when it had not.
    """
    runtime = runtime_of(request)
    if unverified_claims(body.token).get("principal_id") != principal_id:
        raise ApiError(
            400,
            "revocation_principal_mismatch",
            "A revogação não corresponde a este titular.",
        )
    try:
        revoked = runtime.core.submit_principal_revocation(body.token)
    except ValueError as error:
        reason = REVOCATION_REASONS.get(str(error), "revocation_invalid")
        raise ApiError(400, reason, "Revogação inválida.") from error
    if not revoked:
        raise ApiError(
            403,
            "revocation_authority_unknown",
            "Nenhum mandato deste titular aceita esta assinatura.",
        )
    return {"principal_id": principal_id, "revoked_mandate_ids": revoked}


@router.patch("/mandates/{mandate_id}/limit", response_model=ReplaceLimitResponse)
def replace_limit(request: Request, mandate_id: str, body: ReplaceLimitRequest) -> ReplaceLimitResponse:
    runtime = runtime_of(request)
    if not body.authorization_jws:
        raise ApiError(
            403,
            "limit_change_unsigned",
            "A mudança de limite exige autorização assinada pelo titular.",
        )
    try:
        runtime.core.replace_live_limit(
            mandate_id, body.limit.to_money(), authorization_jws=body.authorization_jws
        )
    except ApprovalError as error:
        raise ApiError(error.status_code, error.reason_code, error.human_summary) from error
    except ValueError as error:
        raise ApiError(404, "mandate_not_found", "Mandato não encontrado.") from error
    mandate = runtime.core.mandate(mandate_id)
    assert mandate is not None
    return ReplaceLimitResponse(
        policy_version=mandate.policy_version,
        epoch=int(mandate.revocation_metadata.get("epoch", 0)),
    )


@router.post("/mandates/{mandate_id}/revocation", response_model=RevocationResponse)
def revoke(request: Request, mandate_id: str, body: RevocationRequest) -> RevocationResponse:
    runtime = runtime_of(request)
    if runtime.core.mandate(mandate_id) is None:
        raise ApiError(404, "mandate_not_found", "Mandato não encontrado.")
    # A token is authority over the mandate it names, never over the one in the URL.
    # Without this the same signed token could be walked onto a neighbouring mandate.
    if unverified_claims(body.token).get("mandate_id") != mandate_id:
        raise ApiError(
            400,
            "revocation_mandate_mismatch",
            "A revogação não corresponde a este mandato.",
        )
    try:
        runtime.core.submit_signed_revocation(body.token)
    except ValueError as error:
        reason = REVOCATION_REASONS.get(str(error), "revocation_invalid")
        raise ApiError(400, reason, "Revogação inválida.") from error
    mandate = runtime.core.mandate(mandate_id)
    assert mandate is not None
    return RevocationResponse(revoked=True, epoch=int(mandate.revocation_metadata.get("epoch", 0)))
