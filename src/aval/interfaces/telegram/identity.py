"""Who each Telegram chat is, and the key it signs with.

The case answers "I never authorized this" with a signature, so the tap has to be
signed by the holder — not by the server on the holder's behalf. The bot is the
holder's device: it custodies one P-256 key per chat and signs approvals,
revocations and limit changes with it.

Keys are written to disk on purpose. A mandate is revocable only by the key that
created it, so a bot restart that forgot its keys would leave every judge holding
a mandate nobody can revoke — and revocation is the strongest moment of the demo.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any
import json
import os
import tempfile
import threading

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from aval.security.jws import sign_compact_jws
from aval.security.key_custody import KeyCustodyService


class BotCustody(KeyCustodyService):
    """Custody that can be reloaded from disk.

    The base service deliberately never lets a key out. A subclass is the honest
    way to add that: the bot is the device that owns these keys, so it — and only
    it — may write them down and read them back.
    """

    def adopt(self, kid: str, private_key: ec.EllipticCurvePrivateKey) -> None:
        self._keys[kid] = private_key

    def export_pem(self, kid: str) -> str:
        return self._keys[kid].private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode("ascii")


@dataclass(frozen=True)
class ChatIdentity:
    chat_id: int
    kid: str
    principal_id: str
    display_name: str
    mandate_id: str | None = None
    # The revocation scope that cancels this mandate's card, handed back once at
    # creation. The API never serves the instrument token — a client that could read it
    # could present it — so the only way to hold it is to have been told it.
    instrument_scope: str | None = None
    # Reservations this chat actually bought. A dispute carries no signature, so the
    # core cannot tell a forged reservation id from one the person really holds —
    # this is the only place that knows, which is why it survives a restart.
    reservations: tuple[str, ...] = ()

    @property
    def actor(self) -> str:
        return f"telegram:{self.chat_id}"


class IdentityStore:
    """One holder key per chat, kept across restarts.

    ponytail: private keys sit in a plain file, readable by whoever can read the
    demo directory. Fine for test keys that authorize test money; a real
    deployment keeps them in the phone's secure element, which is also where the
    signature would honestly belong.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._custody = BotCustody()
        self._identities: dict[int, ChatIdentity] = {}
        # One person per chat, but several chats at once: the bot answers each in its
        # own thread, and they all write to this one file. The lock is what keeps a
        # save from serialising a dict another chat is mutating.
        self._lock = threading.Lock()
        self._load()

    @property
    def custody(self) -> BotCustody:
        return self._custody

    def get(self, chat_id: int) -> ChatIdentity | None:
        return self._identities.get(chat_id)

    def known_chats(self) -> tuple[int, ...]:
        with self._lock:
            return tuple(self._identities)

    def for_mandate(self, mandate_id: str) -> ChatIdentity | None:
        """The chat whose key holds this mandate, if this bot holds it at all.

        Reading a mandate is now proved by a holder signature, and this is how the bot
        knows which of its keys to sign with. A mandate no chat here holds gets no
        signature — and the runtime answers that with a refusal, which is the honest
        outcome: the bot cannot show a record it has no authority over.
        """
        for identity in self._identities.values():
            if identity.mandate_id == mandate_id:
                return identity
        return None

    def for_principal(self, principal_id: str) -> ChatIdentity | None:
        """Which chat a core event belongs to.

        The other computer knows a buyer only as a principal id — it has never heard of
        a chat id, and it must not, because a Telegram id is the one identifier here
        that points at a person outside this system. So the mapping back lives on this
        side, in the file this bot already keeps, and an event naming a principal no
        chat here holds is simply not deliverable.
        """
        if not principal_id:
            return None
        for identity in self._identities.values():
            if identity.principal_id == principal_id:
                return identity
        return None

    def enrol(self, chat_id: int, display_name: str) -> ChatIdentity:
        """Mint a holder key for a chat that has never spoken before."""
        with self._lock:
            existing = self._identities.get(chat_id)
        if existing is not None:
            return existing
        kid = f"tg_{chat_id}"
        if not self._custody.has(kid):
            self._custody.generate_es256(kid)
        identity = ChatIdentity(
            chat_id=chat_id,
            kid=kid,
            principal_id=f"usr_tg_{chat_id}",
            display_name=display_name or f"Titular {chat_id}",
        )
        with self._lock:
            self._identities[chat_id] = identity
            self._save()
        return identity

    def bind_mandate(
        self, chat_id: int, mandate_id: str, *, instrument_scope: str | None = None
    ) -> ChatIdentity:
        with self._lock:
            identity = replace(
                self._identities[chat_id],
                mandate_id=mandate_id,
                instrument_scope=instrument_scope,
            )
            self._identities[chat_id] = identity
            self._save()
        return identity

    def record_reservation(self, chat_id: int, reservation_id: str) -> None:
        """Remember that this chat bought this. Written through, because the button
        that denies a purchase is worthless if a restart forgets the purchase."""
        with self._lock:
            identity = self._identities.get(chat_id)
            if identity is None or reservation_id in identity.reservations:
                return
            self._identities[chat_id] = replace(
                identity, reservations=identity.reservations + (reservation_id,)
            )
            self._save()

    def owns_reservation(self, chat_id: int, reservation_id: str) -> bool:
        identity = self._identities.get(chat_id)
        return identity is not None and reservation_id in identity.reservations

    def public_jwk(self, identity: ChatIdentity) -> dict[str, str]:
        return self._custody.public_jwk(identity.kid)

    def sign(self, identity: ChatIdentity, payload: dict[str, Any]) -> str:
        """The holder's signature over one decision. Never a server signature."""
        return sign_compact_jws(payload, self._custody, identity.kid)

    # ── persistence ────────────────────────────────────────────────────────
    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            # A corrupt store must not take the bot down; it re-enrols instead.
            return
        for entry in raw.get("identities", []):
            try:
                private_key = serialization.load_pem_private_key(
                    entry["private_key_pem"].encode("ascii"), password=None
                )
            except (KeyError, ValueError, TypeError):
                continue
            if not isinstance(private_key, ec.EllipticCurvePrivateKey):
                continue
            identity = ChatIdentity(
                chat_id=int(entry["chat_id"]),
                kid=str(entry["kid"]),
                principal_id=str(entry["principal_id"]),
                display_name=str(entry["display_name"]),
                mandate_id=entry.get("mandate_id"),
                instrument_scope=entry.get("instrument_scope"),
                reservations=tuple(entry.get("reservations") or ()),
            )
            self._custody.adopt(identity.kid, private_key)
            self._identities[identity.chat_id] = identity

    def _save(self) -> None:
        payload = {
            "identities": [
                {
                    "chat_id": identity.chat_id,
                    "kid": identity.kid,
                    "principal_id": identity.principal_id,
                    "display_name": identity.display_name,
                    "mandate_id": identity.mandate_id,
                    "instrument_scope": identity.instrument_scope,
                    "reservations": list(identity.reservations),
                    "private_key_pem": self._custody.export_pem(identity.kid),
                }
                for identity in self._identities.values()
            ]
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        # Write-then-rename: a crash mid-write must not leave a half file that
        # loses every key the bot has.
        handle, temporary = tempfile.mkstemp(dir=self._path.parent, suffix=".tmp")
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as file:
                json.dump(payload, file, indent=2)
            os.replace(temporary, self._path)
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise
