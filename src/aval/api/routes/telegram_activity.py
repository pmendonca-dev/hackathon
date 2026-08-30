"""What the bot has been doing, as a room of judges may watch it.

The demo happens in two places at once: a person types into Telegram on their own
phone, and the decision they provoked has to become visible on the screen everybody
else is looking at. Nothing carried that across. `/mandates` is scoped by the holder
key on purpose, and the browser does not hold a chat's key, so the site could show
every mandate *it* created and none of the ones that matter on stage.

This route answers the trail and nothing else. It is deliberately not
`/admin/telegram/chats`, which lists who exists and which mandate is theirs, and is
operator-gated because a directory of buyers is an oracle. The feed below carries no
identifier at all — no chat id, no principal, no mandate id — so there is nothing in
it to look anyone up with, and no way to turn a line of it into a read of somebody's
limits. What is published is what the auditor view already publishes to anyone: the
chained record of decisions the core made.

What it does publish, and the trade that was made knowingly: the first name each
person gave Telegram, next to what the core decided for them. That is the point on
stage — a judge has to recognise their own purchase — and it is the reason this is a
demonstration surface rather than something to leave running over real buyers.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel

from aval.api.dependencies import runtime_of
from aval.api.routes.telegram_chats import identity_path

router = APIRouter(tags=["demo"])

#: Enough to hold a whole demo, small enough that a long-running instance cannot turn
#: one request into an unbounded read of every chat's history.
DEFAULT_LIMIT = 60
MAX_LIMIT = 200


class ActivityEvent(BaseModel):
    """One decision, named by the person who provoked it and nothing else.

    There is no `mandate_id` here, and its absence is the design rather than an
    omission: it is what keeps this feed from being a way to read a stranger's record.
    """

    at: str
    who: str
    event_type: str
    summary: str
    #: The event's own digest from the hash chain. Publishing it lets the screen say
    #: the trail is chained without handing over anything to look a buyer up with — a
    #: digest names its contents, not its subject.
    digest: str | None = None


class ActivityFeed(BaseModel):
    events: list[ActivityEvent]
    #: How many chats contributed, so a screen can say "nobody has started yet"
    #: differently from "the wiring broke".
    chats: int


def _first_name(display_name: str) -> str:
    """`Matheus Fondello` becomes `Matheus`.

    A first name is what a person recognises themselves by on a screen across the
    room. Carrying the full one would publish more of a stranger than the demo needs.
    """
    cleaned = " ".join(display_name.split())
    return cleaned.split(" ")[0] if cleaned else "someone"


def _chats() -> list[tuple[str, str]]:
    """(display name, mandate id) for every chat that has a mandate.

    The identity file also holds each chat's **private key**. Only these two fields
    are ever read out of a record, and neither the key nor the ids travel further
    than this function.
    """
    try:
        raw = json.loads(identity_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        # No bot has ever run here, or the file is mid-write. Both mean the same
        # thing to a screen: nothing to show yet.
        return []
    records = raw.get("identities", []) if isinstance(raw, dict) else []
    found: list[tuple[str, str]] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        mandate_id = record.get("mandate_id")
        if not isinstance(mandate_id, str) or not mandate_id:
            continue
        display_name = record.get("display_name")
        found.append(
            (_first_name(display_name if isinstance(display_name, str) else ""), mandate_id)
        )
    return found


@router.get("/telegram/activity", response_model=ActivityFeed)
def read_telegram_activity(
    request: Request,
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
) -> ActivityFeed:
    """The newest decisions first, across every chat, with nobody's id in them."""
    core = runtime_of(request).core
    chats = _chats()
    collected: list[tuple[Any, ActivityEvent]] = []
    for who, mandate_id in chats:
        for entry in core.timeline_for(mandate_id):
            collected.append(
                (
                    entry.occurred_at,
                    ActivityEvent(
                        at=entry.occurred_at.isoformat(),
                        who=who,
                        event_type=entry.event_type,
                        summary=entry.human_summary,
                        digest=entry.sha256,
                    ),
                )
            )
    # Newest first: a screen nobody is scrolling has to lead with what just happened.
    collected.sort(key=lambda pair: pair[0], reverse=True)
    return ActivityFeed(
        events=[event for _, event in collected[:limit]], chats=len(chats)
    )
