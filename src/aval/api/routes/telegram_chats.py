"""Which Telegram chats exist, so a screen can follow one without holding its key.

The listing in `/mandates` is scoped by the holder key on purpose: a name anyone can
guess must not hand out a buyer's limits. That property is what makes a browser unable
to show a judge's chat — the browser's wallet does not hold that chat's mandate.

This route does not weaken it. It answers only the chat directory the bot already keeps
on disk — who started a chat, and which mandate they were given — and every field it
returns is one an unauthenticated `GET /mandates/{id}` would already answer. The private
key in each record never leaves this function: the response model has no field for it.

It is an operator surface because a directory of buyers is an oracle for which buyers
exist, and that is the operator's to hand out, not a stranger's to enumerate.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from aval.api.operator_auth import require_operator

router = APIRouter(tags=["demo"])


class TelegramChat(BaseModel):
    chat_id: int
    display_name: str
    principal_id: str
    mandate_id: str | None


class TelegramChatList(BaseModel):
    chats: list[TelegramChat]


def identity_path() -> Path:
    """The same default the bot's own config uses, so the two agree without wiring."""
    return Path(
        os.environ.get("TELEGRAM_IDENTITY_PATH", "").strip() or "var/telegram-identities.json"
    )


@router.get(
    "/admin/telegram/chats",
    response_model=TelegramChatList,
    dependencies=[Depends(require_operator)],
)
def list_telegram_chats() -> TelegramChatList:
    """An empty list when the bot has never run — not an error.

    A screen asking this before anybody has typed /start is the normal case on stage,
    and answering 404 would make "nobody has started yet" look like "the wiring broke".
    """
    path = identity_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return TelegramChatList(chats=[])
    return TelegramChatList(
        chats=[
            TelegramChat(
                chat_id=int(entry["chat_id"]),
                display_name=str(entry.get("display_name") or "—"),
                principal_id=str(entry["principal_id"]),
                mandate_id=entry.get("mandate_id") or None,
            )
            for entry in raw.get("identities", [])
            if "chat_id" in entry and "principal_id" in entry
        ]
    )
