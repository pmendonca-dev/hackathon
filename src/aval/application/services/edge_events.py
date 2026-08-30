"""What Computer B is willing to tell Computer A.

This module is a filter, and that is its entire reason to exist. A watch outcome on B is
a rich object: the offer, its signature, the authorization proof, the evaluation ladder,
the instrument the mandate names. A needs almost none of it — A needs enough to write a
sentence in a chat.

So the shape below is an allowlist, written out field by field, and never a `dict(run)`
with a few keys popped. The difference matters: a denylist silently forwards whatever
gets added upstream next month, and what is downstream here is the computer holding the
OpenAI key, one hop from a screen. Anything that leaks does so into a chat message.

Specifically never crossing:

- **the instrument token.** `pm_...` is not a card number, but it is the means of
  payment, and A has no use for it whatsoever.
- **any compact JWS.** `merchant_authorization` and `authorization_proof` are what the
  merchant and the auditor verify; A verifies nothing and would only be carrying them
  past a boundary for no reason.
- **the evaluation trace.** It names the limit, the ceiling and the spend — the mandate's
  private numbers, which the merchant view already hides on purpose.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Connection

from aval.agent.purchasing_agent import AgentRun
from aval.domain.entities import Watch
from aval.infrastructure.sqlite.edge_event_repository import SqliteEdgeEventRepository

WATCH_CLOSED = "watch_closed"


def watch_closed_payload(watch: Watch, run: AgentRun | None, *, principal_id: str) -> dict[str, Any]:
    """The sentence A will write, as data.

    `run` is None when the watch expired: nothing was ever put to the core, so there is
    no offer, no outcome from the mandate and no settlement — and saying so is different
    from saying it was refused.
    """
    item = (run.offer or {}).get("item", {}) if run is not None else {}
    total = (run.offer or {}).get("total", {}) if run is not None else {}
    return {
        "principal_id": principal_id,
        "watch_id": watch.id,
        # The reason code, which is already written to be read by a person.
        "outcome": watch.outcome,
        "human_summary": None if run is None else run.human_summary,
        # Where it was found. The link is the whole point of a real-offer watch: it is
        # what lets the person check the claim instead of believing it.
        "title": item.get("title"),
        "source_merchant": item.get("source_merchant"),
        "source_url": item.get("source_url"),
        "evidence": item.get("evidence"),
        "amount_minor_units": total.get("minor_units"),
        "currency": total.get("currency"),
        "scale": total.get("scale"),
        # The processor's own reference, so a person can find the charge on their
        # statement. It names a payment; it cannot make one.
        "settlement_reference": watch.settlement_reference,
    }


def append_watch_closed(
    connection: Connection,
    *,
    watch: Watch,
    run: AgentRun | None,
    principal_id: str,
    created_at: datetime,
) -> None:
    """Write the event on the connection that is closing the watch.

    Same transaction, deliberately. A separate write could fail after the watch closed,
    and the result would be a purchase that happened and that nobody is ever told about
    — the one failure mode this outbox exists to remove.
    """
    SqliteEdgeEventRepository(connection).append(
        principal_id=principal_id,
        event_type=WATCH_CLOSED,
        payload=watch_closed_payload(watch, run, principal_id=principal_id),
        created_at=created_at,
    )
