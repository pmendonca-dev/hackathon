"""Falar por um mandato — para lê-lo, ou para contestá-lo.

A prova é sempre a mesma: um JWS ES256 de uma autoridade *holder* daquele mandato sobre
`{principal_id}`, verificado contra a chave que o próprio mandato registrou. É a mesma
regra que a listagem por titular sempre aplicou, extraída aqui porque passou a valer em
mais de uma superfície — e uma regra de autoridade copiada em dois lugares diverge sob
pressão, que é exatamente o que este sistema existe para não fazer.

Os códigos de recusa são parâmetros porque o que está sendo pedido muda: *ler* o registro
e *abrir uma disputa* são pedidos diferentes, e uma pessoa que recebe o código errado não
sabe o que fazer a seguir. O que é verificado nunca muda.
"""

from __future__ import annotations

from fastapi import Request

from aval.api.dependencies import runtime_of
from aval.api.errors import ApiError


def require_holder_authority(
    request: Request,
    mandate_id: str,
    authorization_jws: str | None,
    *,
    unsigned_code: str = "read_authorization_required",
    unsigned_message: str = "This read requires an authority signed by the holder.",
    forbidden_code: str = "read_forbidden",
    forbidden_message: str = "This key is not an authority over this mandate.",
) -> str:
    """The kid whose signature was verified, or a refusal.

    Returning the kid rather than a boolean is deliberate: the trail records *who* acted,
    and an actor written from anything other than a verified signature is a claim wearing
    the clothes of evidence.
    """
    core = runtime_of(request).core
    snapshot = core.snapshot(mandate_id)
    if snapshot is None:
        raise ApiError(404, "mandate_not_found", "Mandate not found.")
    if not authorization_jws:
        raise ApiError(403, unsigned_code, unsigned_message)
    try:
        readable = set(core.mandates_readable_by(authorization_jws, snapshot.mandate.principal.id))
    except ValueError as error:
        raise ApiError(
            422, "read_authorization_malformed", "Malformed read authority."
        ) from error
    if mandate_id not in readable:
        raise ApiError(403, forbidden_code, forbidden_message)
    return core.signing_kid(authorization_jws)


#: Where a read signature travels. A query string is the wrong place for a credential:
#: URLs are written to access logs, kept in browser history, and handed to third parties
#: in `Referer`. A holder JWS is a bearer proof of authority over a mandate — anyone who
#: reads one out of a log can read that person's record for as long as it is valid. The
#: body is not available on a GET, so it travels in a header, which none of those keep.
AUTHORIZATION_HEADER = "X-Aval-Authorization"


def read_authorization(request: Request) -> str | None:
    """The holder signature presented for a read, or None."""
    return request.headers.get(AUTHORIZATION_HEADER) or None
