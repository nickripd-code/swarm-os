import json
import sqlite3
from datetime import datetime, timezone

import pytest

from app.store import Store
from scripts.export_swarm_data import ExportError, export_sqlite, main


def _empty_sqlite(path):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE missions (id TEXT)")
    conn.commit()
    conn.close()


def _secret_sqlite(path, secret: str):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE notes (body TEXT)")
    conn.execute("INSERT INTO notes (body) VALUES (?)", (secret,))
    conn.commit()
    conn.close()


def test_missing_source_writes_nothing(tmp_path):
    dest = tmp_path / "out.db"
    with pytest.raises(ExportError) as caught:
        export_sqlite(tmp_path / "missing.db", dest)
    assert caught.value.code == "SOURCE_MISSING"
    assert not dest.exists()
    assert not (tmp_path / "out.db.manifest.json").exists()


def test_empty_file_is_refused(tmp_path):
    source = tmp_path / "empty.db"
    source.write_bytes(b"")
    dest = tmp_path / "out.db"
    with pytest.raises(ExportError) as caught:
        export_sqlite(source, dest)
    assert caught.value.code == "SOURCE_INVALID"
    assert source.read_bytes() == b""
    assert not dest.exists()


def test_non_sqlite_is_refused_without_echoing_contents(tmp_path, capsys):
    source = tmp_path / "notes.db"
    source.write_text("sk-not-a-database-secret", encoding="utf-8")
    dest = tmp_path / "out.db"
    with pytest.raises(ExportError) as caught:
        export_sqlite(source, dest)
    assert caught.value.code == "SOURCE_INVALID"
    assert "sk-not-a-database-secret" not in str(caught.value)
    assert not dest.exists()
    assert capsys.readouterr().out == ""


def test_valid_empty_sqlite_is_copied_and_marked_empty(tmp_path):
    source = tmp_path / "swarm.db"
    _empty_sqlite(source)
    before = source.read_bytes()
    dest = tmp_path / "snap" / "swarm-snapshot.db"
    result = export_sqlite(source, dest)
    assert result["ok"] is True
    assert result["written"] is True
    assert result["empty"] is True
    assert result["row_count"] == 0
    assert result["volumes"]["workspace"]["copied"] is False
    assert ".env" in result["excluded"]
    assert source.read_bytes() == before
    assert dest.is_file() and dest.stat().st_size > 0
    copied = sqlite3.connect(dest)
    try:
        assert copied.execute("SELECT COUNT(*) FROM missions").fetchone()[0] == 0
    finally:
        copied.close()
    manifest = json.loads((tmp_path / "snap" / "swarm-snapshot.db.manifest.json").read_text(encoding="utf-8"))
    assert manifest["destination"] == str(dest.resolve())
    assert manifest["live_database_modified"] is False


def test_store_snapshot_round_trip(tmp_path):
    source = tmp_path / "swarm.db"
    store = Store(str(source))
    store.engine.dispose()
    dest = tmp_path / "copy.db"
    result = export_sqlite(source, dest)
    assert result["schema_version"] == 4
    assert result["empty"] is True
    assert "missions" in result["tables"]
    copied = sqlite3.connect(dest)
    try:
        assert copied.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] == 4
    finally:
        copied.close()


def test_existing_destination_and_live_path_are_refused(tmp_path):
    source = tmp_path / "swarm.db"
    _empty_sqlite(source)
    dest = tmp_path / "taken.db"
    dest.write_bytes(b"keep-me")
    with pytest.raises(ExportError) as caught:
        export_sqlite(source, dest)
    assert caught.value.code == "DEST_EXISTS"
    assert dest.read_bytes() == b"keep-me"
    with pytest.raises(ExportError) as live:
        export_sqlite(source, source)
    assert live.value.code == "DEST_IS_LIVE"
    with pytest.raises(ExportError) as sidecar:
        export_sqlite(source, source.parent / f"{source.name}-wal")
    assert sidecar.value.code == "DEST_IS_LIVE"


def test_dry_run_writes_nothing(tmp_path):
    source = tmp_path / "swarm.db"
    _secret_sqlite(source, "sk-row-secret")
    dest = tmp_path / "out.db"
    env_file = tmp_path / ".env"
    env_file.write_text("OPENAI_API_KEY=sk-env-secret\n", encoding="utf-8")
    result = export_sqlite(source, dest, dry_run=True)
    assert result["dry_run"] is True
    assert result["written"] is False
    assert result["row_count"] == 1
    assert "sk-row-secret" not in json.dumps(result)
    assert "sk-env-secret" not in json.dumps(result)
    assert not dest.exists()
    assert env_file.read_text(encoding="utf-8").startswith("OPENAI_API_KEY=")


def test_export_does_not_print_or_copy_env(tmp_path, monkeypatch, capsys):
    secret = "sk-export-must-not-print"
    source = tmp_path / "swarm.db"
    _secret_sqlite(source, secret)
    (tmp_path / ".env").write_text(f"OPENAI_API_KEY={secret}\n", encoding="utf-8")
    monkeypatch.setenv("OPENAI_API_KEY", secret)
    monkeypatch.setenv("SWARM_DATABASE_PATH", str(source))
    dest_dir = tmp_path / "backups"
    dest = dest_dir / "snap.db"
    code = main(["--dest", str(dest)])
    captured = capsys.readouterr()
    assert code == 0
    assert secret not in captured.out
    assert secret not in captured.err
    assert "OPENAI_API_KEY=" not in captured.out
    payload = json.loads(captured.out)
    assert payload["written"] is True
    names = {path.name for path in dest_dir.iterdir()}
    assert names == {"snap.db", "snap.db.manifest.json"}
    assert secret not in (dest_dir / "snap.db.manifest.json").read_text(encoding="utf-8")
    copied = sqlite3.connect(dest)
    try:
        assert copied.execute("SELECT body FROM notes").fetchone()[0] == secret
    finally:
        copied.close()


def test_cli_missing_database(tmp_path, capsys):
    dest = tmp_path / "out.db"
    code = main(["--source", str(tmp_path / "missing.db"), "--dest", str(dest)])
    captured = capsys.readouterr()
    assert code == 2
    body = json.loads(captured.out)
    assert body["ok"] is False
    assert body["code"] == "SOURCE_MISSING"
    assert "live database" in captured.err.lower() or "Local SQLite" in captured.err
    assert not dest.exists()


def test_default_dest_dry_run_uses_stamp(tmp_path, monkeypatch):
    source = tmp_path / "swarm.db"
    _empty_sqlite(source)
    monkeypatch.chdir(tmp_path)
    when = datetime(2026, 9, 23, 8, 30, tzinfo=timezone.utc)
    result = export_sqlite(source, dry_run=True, now=when)
    assert result["destination"].endswith("swarm-export-20260923T083000Z.db")
    assert list(tmp_path.glob("swarm-export-*")) == []
