"""Fail-closed local SQLite snapshot for Swarm OS operators.

Copies the SQLite database to a new file. Does not replace the live database,
does not copy ``.env``, and does not print environment secrets or row contents.

``SWARM_WORKSPACE_ROOT`` (default ``{tempdir}/swarm-workspaces``) is recorded
in the manifest only. Workspace files are not copied.

Usage:
  python scripts/export_swarm_data.py --dry-run
  python scripts/export_swarm_data.py --dest ./backups/swarm-snapshot.db
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

from app.workspace import DEFAULT_ROOT_NAME, default_workspace_root

WARNING = (
    "Local SQLite snapshot only. The live database is not modified or replaced. "
    ".env files and process environment secrets are not exported. "
    "Workspace files under SWARM_WORKSPACE_ROOT are documented, not copied. "
    "Do not commit the snapshot."
)

_TABLE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SECRET_NAME = re.compile(r"(KEY|SECRET|TOKEN|PASSWORD|CREDENTIAL)", re.IGNORECASE)


class ExportError(Exception):
    """Refused export. ``message`` must not contain secrets or file contents."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def default_database_path() -> Path:
    """Same default as ``app.main``: ``SWARM_DATABASE_PATH`` or repo ``swarm.db``."""
    env = os.environ.get("SWARM_DATABASE_PATH")
    if env is None:
        return (Path(__file__).resolve().parent.parent / "swarm.db").resolve()
    return Path(env).expanduser().resolve()


def _resolved(path: Path) -> Path:
    return path.expanduser().resolve()


def _live_paths(source: Path) -> set[Path]:
    source = _resolved(source)
    return {
        source,
        Path(str(source) + "-wal"),
        Path(str(source) + "-shm"),
        Path(str(source) + "-journal"),
    }


def _refuse_destination(source: Path, dest: Path) -> None:
    if dest.name == ".env" or dest.name.startswith(".env."):
        raise ExportError("DEST_FORBIDDEN", "Refusing to write an env file")
    live = _live_paths(source)
    if dest in live or _resolved(dest) in live:
        raise ExportError("DEST_IS_LIVE", "Refusing to overwrite the live database")
    if dest.exists() or dest.is_symlink():
        raise ExportError("DEST_EXISTS", "Destination already exists; choose a new path")
    parent = dest.parent
    if parent.exists() and not parent.is_dir():
        raise ExportError("DEST_INVALID", "Destination parent is not a directory")


def _open_source(source: Path) -> sqlite3.Connection:
    if not source.is_file():
        raise ExportError("SOURCE_MISSING", "Source database is missing")
    if source.stat().st_size == 0:
        raise ExportError("SOURCE_INVALID", "Source database is empty")
    try:
        with source.open("rb") as handle:
            header = handle.read(16)
    except OSError as exc:
        raise ExportError("SOURCE_INVALID", "Source database is not readable") from exc
    if not header.startswith(b"SQLite format 3\x00"):
        raise ExportError("SOURCE_INVALID", "Source is not a SQLite database")
    try:
        conn = sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)
    except sqlite3.Error as exc:
        raise ExportError("SOURCE_INVALID", "Source database cannot be opened read-only") from exc
    try:
        conn.execute("PRAGMA query_only=ON")
        check = conn.execute("PRAGMA quick_check").fetchone()
    except sqlite3.Error as exc:
        conn.close()
        raise ExportError("SOURCE_INVALID", "Source database failed integrity check") from exc
    if not check or check[0] != "ok":
        conn.close()
        raise ExportError("SOURCE_INVALID", "Source database failed integrity check")
    return conn


def _schema_version(conn: sqlite3.Connection) -> int | None:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
    ).fetchone()
    if row is None:
        return None
    value = conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
    return int(value) if value is not None else 0


def _inventory(conn: sqlite3.Connection) -> tuple[list[str], int, bool]:
    names = [
        name
        for (name,) in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
        if isinstance(name, str) and _TABLE_NAME.fullmatch(name)
    ]
    total = 0
    for name in names:
        count = conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
        total += int(count)
    return names, total, total == 0


def _volume_note() -> dict:
    root = default_workspace_root()
    return {
        "env": "SWARM_WORKSPACE_ROOT",
        "default": "{tempdir}/" + DEFAULT_ROOT_NAME,
        "path": str(root),
        "exists": root.is_dir(),
        "copied": False,
    }


def _manifest(
    *,
    source: Path,
    dest: Path,
    dry_run: bool,
    written: bool,
    tables: list[str],
    row_count: int,
    empty: bool,
    schema_version: int | None,
    bytes_written: int | None,
) -> dict:
    return {
        "ok": True,
        "dry_run": dry_run,
        "written": written,
        "warning": WARNING,
        "source": str(source),
        "destination": str(dest),
        "bytes": bytes_written,
        "schema_version": schema_version,
        "tables": tables,
        "row_count": row_count,
        "empty": empty,
        "live_database_modified": False,
        "excluded": [".env", ".env.*"],
        "volumes": {
            "sqlite": {
                "env": "SWARM_DATABASE_PATH",
                "default": "swarm.db",
                "source": str(source),
                "copied": written,
            },
            "workspace": _volume_note(),
        },
    }


def _backup(source_conn: sqlite3.Connection, dest: Path) -> None:
    fd = os.open(dest, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    dest_conn = None
    try:
        dest_conn = sqlite3.connect(dest)
        source_conn.backup(dest_conn)
        check = dest_conn.execute("PRAGMA quick_check").fetchone()
        if not check or check[0] != "ok":
            raise sqlite3.DatabaseError("destination integrity check failed")
    except sqlite3.Error:
        if dest_conn is not None:
            dest_conn.close()
        dest.unlink(missing_ok=True)
        raise ExportError("SOURCE_INVALID", "SQLite backup failed without modifying the live database")
    else:
        dest_conn.close()


def _write_manifest(path: Path, payload: dict) -> None:
    data = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        os.write(fd, data)
    except Exception:
        os.close(fd)
        path.unlink(missing_ok=True)
        raise
    else:
        os.close(fd)


def redact_secrets(text: str) -> str:
    """Remove environment secret values from operator-visible text."""
    redacted = text
    for name, value in os.environ.items():
        if not value or len(value) < 12 or not _SECRET_NAME.search(name):
            continue
        redacted = redacted.replace(value, "[redacted]")
    return redacted


def export_sqlite(
    source: Path | None = None,
    dest: Path | None = None,
    *,
    dry_run: bool = False,
    now: datetime | None = None,
) -> dict:
    """Copy ``source`` to a new SQLite file, or describe the copy when ``dry_run``."""
    source = _resolved(source if source is not None else default_database_path())
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    if dest is None:
        dest = Path.cwd() / f"swarm-export-{stamp}.db"
    dest = _resolved(dest)
    manifest_path = dest.parent / f"{dest.name}.manifest.json"
    _refuse_destination(source, dest)
    _refuse_destination(source, manifest_path)

    conn = _open_source(source)
    try:
        tables, row_count, empty = _inventory(conn)
        schema_version = _schema_version(conn)
        plan = _manifest(
            source=source,
            dest=dest,
            dry_run=dry_run,
            written=False,
            tables=tables,
            row_count=row_count,
            empty=empty,
            schema_version=schema_version,
            bytes_written=None,
        )
        if dry_run:
            return plan
        dest.parent.mkdir(parents=True, exist_ok=True)
        created_dest = False
        try:
            _backup(conn, dest)
            created_dest = True
            written = _manifest(
                source=source,
                dest=dest,
                dry_run=False,
                written=True,
                tables=tables,
                row_count=row_count,
                empty=empty,
                schema_version=schema_version,
                bytes_written=dest.stat().st_size,
            )
            _write_manifest(manifest_path, written)
        except Exception:
            if created_dest:
                dest.unlink(missing_ok=True)
            raise
        return written
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Snapshot the local Swarm SQLite database.")
    parser.add_argument("--source", type=Path, default=None, help="SQLite file (default: SWARM_DATABASE_PATH or ./swarm.db)")
    parser.add_argument("--dest", type=Path, default=None, help="New snapshot path. Refused if it already exists.")
    parser.add_argument("--dry-run", action="store_true", help="Validate and print the plan. Write nothing.")
    args = parser.parse_args(argv)
    print(WARNING, file=sys.stderr)
    try:
        result = export_sqlite(args.source, args.dest, dry_run=args.dry_run)
    except ExportError as exc:
        print(redact_secrets(json.dumps({"ok": False, "code": exc.code, "error": str(exc)}, sort_keys=True)))
        return 2
    print(redact_secrets(json.dumps(result, sort_keys=True)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
