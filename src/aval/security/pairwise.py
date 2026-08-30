"""Pairwise subject identifiers: one buyer, a different name at every seller.

The idea is not new and that is the point — OpenID Connect has had pairwise subject
identifiers for a decade, and this is that, applied to a mandate instead of a login.

The merchant wants one true thing: to recognise a returning customer. It does not need
to be able to compare that customer with another shop's customers, and a payment layer
that sits in front of every agentic purchase is the single worst place to hand out an
identifier that makes such comparison possible.

`HMAC(secret, mandate_id | merchant_id)` gives both at once: stable for one pair, and
unlinkable across pairs to anyone without the secret. Truncation to 128 bits is well
past collision relevance for this population and keeps the handle readable.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets

_SECRET_ENV = "AVAL_PAIRWISE_SECRET"


def resolve_pairwise_secret() -> bytes:
    """The HMAC key, from the environment or freshly drawn.

    Drawn fresh, the handles are stable for the life of the process and meaningless
    afterwards — which is the right default for a demo instance, and the wrong one for
    production, where this key belongs in a KMS beside the signing keys. Setting the
    variable is what makes a handle survive a restart.
    """
    configured = os.environ.get(_SECRET_ENV)
    if configured:
        return configured.encode("utf-8")
    return secrets.token_bytes(32)


def pairwise_id(secret: bytes, *, mandate_id: str, merchant_id: str) -> str:
    """The name this buyer has at this seller, and nowhere else.

    The separator is not decorative: without it `("ab", "c")` and `("a", "bc")` would
    hash to the same handle, which is a collision an attacker gets to choose.
    """
    digest = hmac.new(
        secret, f"{mandate_id}|{merchant_id}".encode(), hashlib.sha256
    ).digest()
    return f"pw_{digest[:16].hex()}"
