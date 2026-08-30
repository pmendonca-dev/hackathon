from __future__ import annotations

from collections.abc import Mapping

from aval.application.services.checkout import CheckoutSession


def project_ucp_checkout(session: CheckoutSession) -> Mapping[str, object]:
    """Return the immutable UCP response projection held by the canonical checkout service."""
    return session.payload
