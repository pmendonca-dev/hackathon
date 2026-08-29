from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine, create_engine, event


def create_sqlite_engine(database_path: Path) -> Engine:
    """Create the demo database with SQLite safety settings enabled."""
    database_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        f"sqlite+pysqlite:///{database_path.resolve().as_posix()}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def configure_connection(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys = ON")
        cursor.execute("PRAGMA journal_mode = WAL")
        cursor.execute("PRAGMA busy_timeout = 5000")
        cursor.close()

    return engine
