"""Bot configuration. Every privileged surface is fail-closed by default."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


class ConfigError(Exception):
    """Raised when the environment cannot produce a usable bot."""


@dataclass(frozen=True)
class BotConfig:
    token: str
    api_base_url: str | None
    api_token: str | None
    allowed_chat_ids: frozenset[int]
    poll_timeout_seconds: int
    request_timeout_seconds: int
    escalation_poll_seconds: int

    @property
    def uses_mock_gateway(self) -> bool:
        """No backend URL means the system is still being built; serve fixtures."""
        return self.api_base_url is None

    def may_act(self, chat_id: int) -> bool:
        return chat_id in self.allowed_chat_ids

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "BotConfig":
        token = env.get("TELEGRAM_BOT_TOKEN", "").strip()
        if not token:
            raise ConfigError("TELEGRAM_BOT_TOKEN is required")
        base_url = env.get("AVAL_API_BASE_URL", "").strip().rstrip("/") or None
        return cls(
            token=token,
            api_base_url=base_url,
            api_token=env.get("AVAL_API_TOKEN", "").strip() or None,
            allowed_chat_ids=_chat_ids(env.get("TELEGRAM_ALLOWED_CHAT_IDS", "")),
            poll_timeout_seconds=_positive_int(env, "TELEGRAM_POLL_TIMEOUT_SECONDS", 30),
            request_timeout_seconds=_positive_int(env, "AVAL_REQUEST_TIMEOUT_SECONDS", 10),
            escalation_poll_seconds=_positive_int(env, "AVAL_ESCALATION_POLL_SECONDS", 10),
        )


def _chat_ids(raw: str) -> frozenset[int]:
    ids: set[int] = set()
    for item in raw.replace(";", ",").split(","):
        candidate = item.strip()
        if not candidate:
            continue
        try:
            ids.add(int(candidate))
        except ValueError as error:
            raise ConfigError(f"TELEGRAM_ALLOWED_CHAT_IDS holds a non-numeric id: {candidate!r}") from error
    return frozenset(ids)


def _positive_int(env: Mapping[str, str], name: str, default: int) -> int:
    raw = env.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as error:
        raise ConfigError(f"{name} must be an integer") from error
    if value <= 0:
        raise ConfigError(f"{name} must be positive")
    return value
