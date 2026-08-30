"""Computer A's process: the discovery edge, and nothing else.

Separate from `aval.main` on purpose. That entrypoint builds the authorization core, the
database and the settlement adapter; this one builds a single route and a search. A
process that cannot construct the core cannot be talked into using it, whatever arrives
in a request body — which is the property the whole two-machine split rests on.
"""

from __future__ import annotations

import logging
import os
import sys

import uvicorn

from aval.interfaces.discovery.app import create_discovery_app
from aval.security.edge_auth import EdgeAuthError

logger = logging.getLogger("aval.discovery")

# Secrets that belong to the other computer. A holding any of them means the split has
# quietly stopped being a split, and the loudest possible moment to find that out is
# before the process starts listening.
FORBIDDEN_ON_A = (
    "AVAL_STRIPE_SECRET_KEY",
    "AVAL_CUSTODY_SEED",
    "AVAL_OPERATOR_AUTHORITY_SEED",
    "AVAL_OPERATOR_TOKEN",
)


def refuse_other_machines_secrets(env: dict[str, str]) -> None:
    held = [name for name in FORBIDDEN_ON_A if env.get(name, "").strip()]
    if held:
        raise EdgeAuthError(
            "este processo é o computador A e não pode carregar segredos do B: "
            + ", ".join(held)
        )


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    try:
        refuse_other_machines_secrets(dict(os.environ))
    except EdgeAuthError as error:
        logger.error("%s", error)
        sys.exit(2)
    secret = os.environ.get("AVAL_CORE_TO_EDGE_SECRET", "").strip()
    if not secret:
        logger.error("AVAL_CORE_TO_EDGE_SECRET é obrigatório: sem ela a ponta fica aberta")
        sys.exit(2)
    if not os.environ.get("OPENAI_API_KEY", "").strip():
        # Not fatal. Without a key discovery finds nothing, every watch stays open, and
        # that is the honest behaviour for a system that cannot look.
        logger.warning("sem OPENAI_API_KEY: a descoberta não vai achar nada")
    host = os.environ.get("AVAL_DISCOVERY_HOST", "127.0.0.1")
    port = int(os.environ.get("AVAL_DISCOVERY_PORT", "9100"))
    logger.info("ponta de descoberta em %s:%s", host, port)
    uvicorn.run(create_discovery_app(secret=secret), host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
