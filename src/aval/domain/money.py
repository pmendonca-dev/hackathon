from __future__ import annotations

from dataclasses import dataclass

from aval.domain.errors import DomainError


@dataclass(frozen=True)
class Money:
    minor_units: int
    currency: str
    scale: int

    def __post_init__(self) -> None:
        if isinstance(self.minor_units, bool) or not isinstance(self.minor_units, int):
            raise DomainError("money minor_units must be an integer")
        if len(self.currency) != 3 or self.currency != self.currency.upper():
            raise DomainError("money currency must be a three-letter uppercase ISO code")
        if not isinstance(self.scale, int) or not 0 <= self.scale <= 18:
            raise DomainError("money scale must be an integer from 0 to 18")

    def add(self, other: "Money") -> "Money":
        self._require_same_unit(other)
        return Money(self.minor_units + other.minor_units, self.currency, self.scale)

    def subtract(self, other: "Money") -> "Money":
        self._require_same_unit(other)
        return Money(self.minor_units - other.minor_units, self.currency, self.scale)

    def _require_same_unit(self, other: "Money") -> None:
        if (self.currency, self.scale) != (other.currency, other.scale):
            raise DomainError("money values must have matching currency and scale")
