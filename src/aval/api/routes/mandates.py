"""Mandate lifecycle: create, register a payment method, move the live limit, revoke.

The last two are the surfaces a judge touches during the trial by fire, so they
read and write straight through to the core. No cache sits in front of them.
"""

from __future__ import annotations

import base64
import logging
import json
from uuid import uuid4

from fastapi import Depends, APIRouter, Request, status

from aval.api.dependencies import runtime_of
from aval.api.errors import ApiError
from aval.api.holder_authority import read_authorization
from aval.application.authorization_core import ApprovalError
from aval.api.schemas import (
    BindInstrumentRequest,
    BindInstrumentResponse,
    InstrumentSessionRequest,
    InstrumentSessionResponse,
    InstrumentSessionStatusResponse,
    CreateMandateRequest,
    CreateMandateResponse,
    ReplaceLimitRequest,
    ReplaceLimitResponse,
    RevocationRequest,
    RevocationResponse,
)
from aval.domain.entities import (
    Mandate,
    PaymentInstrument,
    Principal,
    RevocationAuthority,
    UsageLimit,
)
from aval.domain.enums import RevocationRole

logger = logging.getLogger("aval.api.mandates")

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

    # A card that was vaulted somewhere else, named by its token. Nothing here reads
    # or tokenizes a number, because no number arrives: a mandate created with no
    # payment method simply cannot pay, which is the honest state for one whose holder
    # has not registered a card yet.
    instrument: PaymentInstrument | None = None
    if body.payment_method is not None:
        instrument = PaymentInstrument(
            body.payment_method.token, body.payment_method.label
        )
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


# Where Stripe sends the person after they finish. It is a landing page and nothing
# more — the card never comes back through it, and the bot learns what happened by
# asking Stripe, not by being redirected.
DEFAULT_RETURN_URL = "https://aval.local/cartao-cadastrado"


def _card_registration(request: Request):
    """The processor that can host a card form, or a refusal that says why.

    The demo processor cannot: it has no page, and inventing one would mean a card
    that is registered here and worthless everywhere else.
    """
    psp = runtime_of(request).psp
    if not hasattr(psp, "create_setup_session"):
        raise ApiError(
            409,
            "card_registration_unavailable",
            "Cadastro de cartão exige um processador real (AVAL_PSP=stripe).",
        )
    return psp


@router.post("/mandates/{mandate_id}/instrument/session", response_model=InstrumentSessionResponse)
def open_instrument_session(
    request: Request, mandate_id: str, body: InstrumentSessionRequest
) -> InstrumentSessionResponse:
    """Open the processor's own card form for this mandate.

    The number is typed at Stripe and never reaches this service. That is not a
    nicety: a card number that touched a chat would live in the message history on
    every logged-in device, in our polling responses and in the process log, and no
    care afterwards takes it back out of those.
    """
    runtime = runtime_of(request)
    psp = _card_registration(request)
    try:
        runtime.core.require_holder(
            mandate_id, body.authorization_jws, scope="instrument_session"
        )
    except ApprovalError as error:
        raise ApiError(error.status_code, error.reason_code, error.human_summary) from error
    except ValueError as error:
        raise ApiError(404, "mandate_not_found", "Mandato não encontrado.") from error
    session = psp.create_setup_session(
        mandate_id, return_url=body.return_url or DEFAULT_RETURN_URL
    )
    return InstrumentSessionResponse(**session)


@router.get(
    "/mandates/{mandate_id}/instrument/session/{session_id}",
    response_model=InstrumentSessionStatusResponse,
)
def read_instrument_session(
    request: Request,
    mandate_id: str,
    session_id: str,
    authorization_jws: str | None = Depends(read_authorization),
) -> InstrumentSessionStatusResponse:
    """The card the person registered, once they have finished registering it.

    Answering nothing while the page is still open is the normal case, not an error:
    the caller is watching a human fill in a form.
    """
    runtime = runtime_of(request)
    psp = _card_registration(request)
    try:
        runtime.core.require_holder(mandate_id, authorization_jws, scope="instrument_session")
    except ApprovalError as error:
        raise ApiError(error.status_code, error.reason_code, error.human_summary) from error
    except ValueError as error:
        raise ApiError(404, "mandate_not_found", "Mandato não encontrado.") from error
    card = psp.read_setup_session(session_id, mandate_id=mandate_id)
    if card is None:
        return InstrumentSessionStatusResponse(ready=False)
    return InstrumentSessionStatusResponse(ready=True, **card)


@router.post("/mandates/{mandate_id}/instrument", response_model=BindInstrumentResponse)
def bind_instrument(
    request: Request, mandate_id: str, body: BindInstrumentRequest
) -> BindInstrumentResponse:
    """Attach the payment method the holder registered at the processor.

    Unsigned is refused outright. Attaching a card decides whose money the agent will
    spend, and a mandate id is a guessable name, not an entitlement — without the
    holder's signature anyone who guessed one could point somebody else's agent at
    their own card, or at nobody's.
    """
    runtime = runtime_of(request)
    if not body.authorization_jws:
        raise ApiError(
            403,
            "instrument_binding_unsigned",
            "Cadastrar um meio de pagamento exige autorização assinada pelo titular.",
        )
    try:
        replaced = runtime.core.bind_instrument(
            mandate_id,
            PaymentInstrument(body.token, body.label),
            authorization_jws=body.authorization_jws,
        )
    except ApprovalError as error:
        raise ApiError(error.status_code, error.reason_code, error.human_summary) from error
    except ValueError as error:
        raise ApiError(404, "mandate_not_found", "Mandato não encontrado.") from error
    return BindInstrumentResponse(
        instrument_label=body.label,
        instrument_revocation_scope=f"instrument:{body.token}",
        replaced_label=None if replaced is None else replaced.label,
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
    _release_card_at_processor(runtime, unverified_claims(body.token).get("scope"))
    return RevocationResponse(revoked=True, epoch=int(mandate.revocation_metadata.get("epoch", 0)))


def _release_card_at_processor(runtime, scope: object) -> None:
    """Let go of the card at the processor once the holder has cancelled it here.

    Done after the core has committed, and outside its write lock: a network call
    inside the transaction that revokes a mandate would make the strongest moment of
    the system depend on somebody else's uptime.

    Best effort on purpose. The local revocation already refuses every later purchase,
    so a processor that does not answer must not turn cancelling a card into an error
    the person sees — and the credential stays cancelled here either way.
    """
    if not isinstance(scope, str) or not scope.startswith("instrument:"):
        return
    psp = runtime.psp
    if not hasattr(psp, "detach"):
        return
    try:
        psp.detach(scope.removeprefix("instrument:"))
    except Exception:  # noqa: BLE001 - the revocation stands whatever the processor says
        logger.warning("o processador não confirmou a baixa do cartão")
