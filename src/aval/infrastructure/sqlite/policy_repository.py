from __future__ import annotations

import json
from uuid import uuid4

from sqlalchemy import Connection, select, update

from aval.domain.money import Money
from aval.infrastructure.sqlite.models import policy_rules


class SqlitePolicyRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def active_limit_for(self, mandate_id: str, fallback: Money) -> tuple[Money, int]:
        row = self._connection.execute(
            select(policy_rules).where(policy_rules.c.mandate_id == mandate_id, policy_rules.c.active == 1)
            .order_by(policy_rules.c.version.desc()).limit(1)
        ).mappings().one_or_none()
        if row is None:
            return fallback, 1
        rule = json.loads(row["rule_json"])
        return Money(rule["limit_minor_units"], rule["currency"], rule["scale"]), row["version"]

    def latest_version(self, mandate_id: str) -> int | None:
        return self._connection.execute(
            select(policy_rules.c.version).where(policy_rules.c.mandate_id == mandate_id)
            .order_by(policy_rules.c.version.desc()).limit(1)
        ).scalar()

    def record(self, mandate_id: str, limit: Money, version: int) -> int:
        """Write one version and retire the previous ones. Versions only ever go up, so
        a proof issued before a change can never carry the version issued after it."""
        self._connection.execute(update(policy_rules).where(policy_rules.c.mandate_id == mandate_id).values(active=0))
        self._connection.execute(policy_rules.insert().values(
            id=f"pol_{uuid4().hex}", mandate_id=mandate_id, version=version, active=1,
            rule_json=json.dumps({"limit_minor_units": limit.minor_units, "currency": limit.currency, "scale": limit.scale}),
        ))
        return version

    def replace_limit(self, mandate_id: str, limit: Money) -> int:
        return self.record(mandate_id, limit, (self.latest_version(mandate_id) or 0) + 1)
