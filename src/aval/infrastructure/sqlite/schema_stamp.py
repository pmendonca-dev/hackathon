"""Tell Alembic about a schema the composition root built itself.

`metadata.create_all` raises the current model's tables in one shot and writes
nothing into `alembic_version`. The database that comes out is shaped like head
and *labelled* like nothing at all, so the next `alembic upgrade head` — the
first step of every production start — replays `0001_initial_core` against
tables that already exist and dies on `table mandates already exists`. The API
then never opens its port, and the Telegram bot, which refuses to start without
it, never reaches a single update.

Stamping closes that gap where it opens. A database whose version table is
missing or empty was never under migration control: `create_all` had just built
it from the same metadata the migrations converge on, so head is the honest
label. A database that already carries a revision is left alone — it may be
genuinely behind, and only a real `upgrade` may move it.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine, inspect, text


def _script_location() -> Path | None:
    """Find the migration tree, which lives beside the source rather than in it."""
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "alembic"
        if (candidate / "versions").is_dir():
            return candidate
    return None


def stamp_head_if_unmanaged(engine: Engine) -> str | None:
    """Label an unmanaged schema as head. Returns the revision written, if any."""
    inspector = inspect(engine)
    if "alembic_version" in inspector.get_table_names():
        with engine.connect() as connection:
            already = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).first()
        if already is not None:
            return None

    location = _script_location()
    if location is None:
        # An installed wheel carries no migrations. Nothing to reconcile against.
        return None

    from alembic.config import Config
    from alembic.script import ScriptDirectory

    config = Config()
    config.set_main_option("script_location", str(location))
    heads = ScriptDirectory.from_config(config).get_heads()
    if len(heads) != 1:
        # Two heads mean an unmerged branch. Guessing which one this schema
        # matches would be worse than letting `alembic upgrade` say so.
        return None
    head = heads[0]

    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE IF NOT EXISTS alembic_version ("
                "version_num VARCHAR(32) NOT NULL, "
                "CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num))"
            )
        )
        connection.execute(
            text("INSERT INTO alembic_version (version_num) VALUES (:head)"),
            {"head": head},
        )
    return head
