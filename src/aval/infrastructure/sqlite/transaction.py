from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from sqlalchemy import Engine
from sqlalchemy.engine import Connection


Result = TypeVar("Result")


def run_in_write_transaction(engine: Engine, operation: Callable[[Connection], Result]) -> Result:
    """Run one SQLite write operation under the demo's immediate writer lock."""
    with engine.connect() as connection:
        connection.exec_driver_sql("BEGIN IMMEDIATE")
        try:
            result = operation(connection)
        except Exception:
            connection.rollback()
            raise
        connection.commit()
        return result
