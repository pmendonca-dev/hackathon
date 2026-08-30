"""Bot configuration. Privileged surfaces are fail-closed unless opened on purpose."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path


class ConfigError(Exception):
    """The environment cannot produce a usable bot."""


@dataclass(frozen=True)
class MandateDefaults:
    """What a fresh mandate authorizes when someone says /start.

    These are the numbers the demo script tells: a live budget, a ceiling nobody
    crosses, travel at VuelaYa. They are configurable because a judge moving them
    mid-demo is the point, not an accident.
    """

    merchants: tuple[str, ...]
    categories: tuple[str, ...]
    currency: str
    scale: int
    limit_minor_units: int
    ceiling_minor_units: int | None
    valid_for: timedelta
    # A test card, because a demo that asks a judge to type a real PAN into a chat
    # deserves the answer it would get. It is tokenized at the edge either way.
    card_number: str


@dataclass(frozen=True)
class BotConfig:
    token: str
    api_base_url: str
    allowed_chat_ids: frozenset[int]
    open_mode: bool
    identity_path: Path
    mandate_defaults: MandateDefaults
    poll_timeout_seconds: int
    request_timeout_seconds: int
    escalation_poll_seconds: int

    def may_act(self, chat_id: int) -> bool:
        """Open mode is safe here: each chat holds its own key and its own mandate,
        so a stranger can only ever move their own authority."""
        return self.open_mode or chat_id in self.allowed_chat_ids

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "BotConfig":
        token = env.get("TELEGRAM_BOT_TOKEN", "").strip()
        if not token:
            raise ConfigError("TELEGRAM_BOT_TOKEN é obrigatório")
        base_url = env.get("AVAL_API_BASE_URL", "http://127.0.0.1:8099").strip().rstrip("/")
        if not base_url:
            raise ConfigError("AVAL_API_BASE_URL não pode ser vazio")
        currency = env.get("AVAL_MANDATE_CURRENCY", "USD").strip().upper()
        if len(currency) != 3:
            raise ConfigError("AVAL_MANDATE_CURRENCY deve ser um código ISO de três letras")
        return cls(
            token=token,
            api_base_url=base_url,
            allowed_chat_ids=_chat_ids(env.get("TELEGRAM_ALLOWED_CHAT_IDS", "")),
            open_mode=env.get("TELEGRAM_OPEN_MODE", "").strip().lower() in {"1", "true", "yes"},
            identity_path=Path(
                env.get("TELEGRAM_IDENTITY_PATH", "").strip() or "var/telegram-identities.json"
            ),
            mandate_defaults=MandateDefaults(
                merchants=_csv(env.get("AVAL_MANDATE_MERCHANTS", "vuelaya")),
                categories=_csv(env.get("AVAL_MANDATE_CATEGORIES", "travel")),
                currency=currency,
                scale=_positive_int(env, "AVAL_MANDATE_SCALE", 2, allow_zero=True),
                limit_minor_units=_positive_int(env, "AVAL_MANDATE_LIMIT_MINOR_UNITS", 20_000),
                ceiling_minor_units=_optional_int(env, "AVAL_MANDATE_CEILING_MINOR_UNITS", 50_000),
                valid_for=timedelta(days=_positive_int(env, "AVAL_MANDATE_VALID_DAYS", 30)),
                card_number=env.get("AVAL_MANDATE_CARD", "4242424242424242").strip(),
            ),
            poll_timeout_seconds=_positive_int(env, "TELEGRAM_POLL_TIMEOUT_SECONDS", 30),
            request_timeout_seconds=_positive_int(env, "AVAL_REQUEST_TIMEOUT_SECONDS", 15),
            escalation_poll_seconds=_positive_int(env, "AVAL_ESCALATION_POLL_SECONDS", 8),
        )


def _csv(raw: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in raw.split(",") if item.strip())


def _chat_ids(raw: str) -> frozenset[int]:
    ids: set[int] = set()
    for item in raw.replace(";", ",").split(","):
        candidate = item.strip()
        if not candidate:
            continue
        try:
            ids.add(int(candidate))
        except ValueError as error:
            raise ConfigError(
                f"TELEGRAM_ALLOWED_CHAT_IDS tem um id não numérico: {candidate!r}"
            ) from error
    return frozenset(ids)


def _positive_int(
    env: Mapping[str, str], name: str, default: int, *, allow_zero: bool = False
) -> int:
    raw = env.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as error:
        raise ConfigError(f"{name} deve ser inteiro") from error
    if value < 0 or (value == 0 and not allow_zero):
        raise ConfigError(f"{name} deve ser positivo")
    return value


def _optional_int(env: Mapping[str, str], name: str, default: int) -> int | None:
    raw = env.get(name, "").strip()
    if raw.lower() in {"none", "off"}:
        return None
    return _positive_int(env, name, default)
