"""Versioned SQLite migrations for the mission store.

Replaces SQLAlchemy `create_all` as the schema path. Existing create_all-era
databases are treated as version 0 and upgraded in place with CREATE TABLE /
CREATE INDEX IF NOT EXISTS so rows are not dropped.

Future column changes belong in a new Migration(version=N+1, ...) that uses
`add_column_if_missing`. A failed upgrade does not stamp `schema_migrations`
and leaves existing rows intact. SQLite may still keep an ADD COLUMN from
that attempt; retries must use `add_column_if_missing` so they stay
idempotent. A database newer than this build fails closed.
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

SCHEMA_TABLE = "schema_migrations"
CURRENT_SCHEMA_VERSION = 1


class MigrationError(RuntimeError):
    """Schema is ahead of this build, or the migration list is invalid."""


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    upgrade: Callable[[Connection], None]


def _table_names(conn: Connection) -> set[str]:
    rows = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()
    return {row[0] for row in rows}


def _columns(conn: Connection, table: str) -> set[str]:
    rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
    return {row[1] for row in rows}


def add_column_if_missing(conn: Connection, table: str, column: str, ddl: str) -> bool:
    """ADD COLUMN when absent. `ddl` is the SQL type/constraints after the name."""
    if column in _columns(conn, table):
        return False
    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
    return True


def _upgrade_001_initial(conn: Connection) -> None:
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS missions (
            id VARCHAR(36) PRIMARY KEY,
            payload TEXT NOT NULL,
            updated_at DATETIME NOT NULL
        )
    """))
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS mission_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mission_id VARCHAR(36),
            event_type VARCHAR(100),
            actor_id VARCHAR(36),
            payload TEXT,
            created_at DATETIME
        )
    """))
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS agents (
            id VARCHAR(36) PRIMARY KEY,
            mission_id VARCHAR(36) NOT NULL,
            payload TEXT NOT NULL,
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL
        )
    """))
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS tasks (
            id VARCHAR(36) PRIMARY KEY,
            mission_id VARCHAR(36) NOT NULL,
            payload TEXT NOT NULL,
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL
        )
    """))
    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_mission_events_mission_id ON mission_events (mission_id)"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_mission_events_event_type ON mission_events (event_type)"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_agents_mission_id ON agents (mission_id)"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_tasks_mission_id ON tasks (mission_id)"))


MIGRATIONS: tuple[Migration, ...] = (
    Migration(1, "initial_schema", _upgrade_001_initial),
)


def _ensure_schema_table(conn: Connection) -> None:
    conn.execute(text(f"""
        CREATE TABLE IF NOT EXISTS {SCHEMA_TABLE} (
            version INTEGER PRIMARY KEY,
            name VARCHAR(200) NOT NULL,
            applied_at DATETIME NOT NULL
        )
    """))


def current_version(conn: Connection) -> int:
    if SCHEMA_TABLE not in _table_names(conn):
        return 0
    row = conn.execute(text(f"SELECT COALESCE(MAX(version), 0) FROM {SCHEMA_TABLE}")).scalar()
    return int(row or 0)


def _validate(migrations: Sequence[Migration]) -> tuple[Migration, ...]:
    ordered = tuple(sorted(migrations, key=lambda item: item.version))
    seen: set[int] = set()
    expected = 1
    for item in ordered:
        if item.version in seen:
            raise MigrationError(f"duplicate migration version {item.version}")
        if item.version != expected:
            raise MigrationError(f"migration versions must be consecutive from 1; missing {expected}")
        seen.add(item.version)
        expected += 1
    return ordered


def apply_migrations(engine: Engine, migrations: Sequence[Migration] | None = None) -> int:
    """Apply pending migrations. Returns the resulting schema version."""
    specs = _validate(MIGRATIONS if migrations is None else migrations)
    supported = specs[-1].version if specs else 0
    with engine.begin() as conn:
        _ensure_schema_table(conn)
        version = current_version(conn)
        if version > supported:
            raise MigrationError(
                f"database schema version {version} is newer than this build ({supported})"
            )
        for item in specs:
            if item.version <= version:
                continue
            if item.version != version + 1:
                raise MigrationError(f"cannot apply version {item.version} after {version}")
            item.upgrade(conn)
            conn.execute(
                text(f"INSERT INTO {SCHEMA_TABLE} (version, name, applied_at) VALUES (:v, :n, :t)"),
                {"v": item.version, "n": item.name, "t": datetime.now(timezone.utc)},
            )
            version = item.version
        return version
