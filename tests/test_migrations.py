from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, inspect, text

from app.migrations import (
    CURRENT_SCHEMA_VERSION, MIGRATIONS, Migration, MigrationError,
    add_column_if_missing, apply_migrations, current_version,
)
from app.models import AgentSpec, AgentStatus, Mission, MissionEvent, MissionStatus
from app.store import Store


def _engine(path):
    return create_engine(f"sqlite:///{path}")


def _version(engine) -> int:
    with engine.connect() as conn:
        return current_version(conn)


def _legacy_missions_and_events(engine, mission: Mission):
    now = datetime.now(timezone.utc)
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE missions (
                id VARCHAR(36) PRIMARY KEY,
                payload TEXT NOT NULL,
                updated_at DATETIME NOT NULL
            )
        """))
        conn.execute(text("""
            CREATE TABLE mission_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                mission_id VARCHAR(36),
                event_type VARCHAR(100),
                actor_id VARCHAR(36),
                payload TEXT,
                created_at DATETIME
            )
        """))
        conn.execute(
            text("INSERT INTO missions (id, payload, updated_at) VALUES (:id, :payload, :updated_at)"),
            {"id": str(mission.id), "payload": mission.model_dump_json(), "updated_at": now},
        )
        conn.execute(text(
            "INSERT INTO mission_events (mission_id, event_type, actor_id, payload, created_at) "
            "VALUES (:mission_id, :event_type, NULL, :payload, :created_at)"
        ), {"mission_id": str(mission.id), "event_type": "mission.completed",
            "payload": '{"summary": "already done"}', "created_at": now})


def test_fresh_database_reaches_current_schema(tmp_path):
    store = Store(str(tmp_path / "fresh.db"))
    names = set(inspect(store.engine).get_table_names())
    assert {"missions", "mission_events", "agents", "tasks", "schema_migrations",
            "worker_leases", "idempotency_keys", "work_items", "memory_notes",
            "provider_outcomes"} <= names
    assert _version(store.engine) == CURRENT_SCHEMA_VERSION
    assert CURRENT_SCHEMA_VERSION == 5
    mission = Mission(goal="fresh schema", status=MissionStatus.COMPLETED)
    store.save_mission(mission)
    store.append(MissionEvent(mission_id=mission.id, event_type="mission.completed",
                              payload={"summary": "ok"}))
    loaded = store.get_mission(mission.id)
    assert loaded is not None
    assert loaded.goal == "fresh schema"
    assert [event.event_type for event in store.events(mission.id)] == ["mission.completed"]


def test_store_open_is_idempotent(tmp_path):
    path = str(tmp_path / "again.db")
    first = Store(path)
    mission = Mission(goal="keep me")
    first.save_mission(mission)
    second = Store(path)
    assert _version(second.engine) == CURRENT_SCHEMA_VERSION
    assert second.get_mission(mission.id).goal == "keep me"


def test_legacy_create_all_database_upgrades_without_losing_rows(tmp_path):
    path = tmp_path / "legacy.db"
    engine = _engine(path)
    mission = Mission(goal="Keep this mission", status=MissionStatus.COMPLETED,
                      result={"summary": "already done"})
    _legacy_missions_and_events(engine, mission)
    assert "schema_migrations" not in inspect(engine).get_table_names()
    assert "agents" not in inspect(engine).get_table_names()

    store = Store(str(path))
    loaded = store.get_mission(mission.id)
    assert loaded is not None
    assert loaded.goal == "Keep this mission"
    assert loaded.status == "completed"
    assert loaded.result == {"summary": "already done"}
    events = store.events(mission.id)
    assert len(events) == 1
    assert events[0].event_type == "mission.completed"
    names = set(inspect(store.engine).get_table_names())
    assert {"missions", "mission_events", "agents", "tasks", "schema_migrations",
            "worker_leases", "idempotency_keys", "work_items", "memory_notes",
            "provider_outcomes"} <= names
    assert _version(store.engine) == CURRENT_SCHEMA_VERSION
    assert store.load_agents(mission.id) == []
    assert store.load_tasks(mission.id) == []

    agent = AgentSpec(
        mission_id=mission.id, role="mission_controller",
        purpose="Recovered after upgrade", capabilities=["coordinate"],
        status=AgentStatus.COMPLETED,
    )
    store.save_agent(agent)
    assert store.load_agents(mission.id)[0].id == agent.id


def test_full_create_all_era_db_is_stamped_without_rewriting_payloads(tmp_path):
    path = tmp_path / "create_all.db"
    engine = _engine(path)
    mission = Mission(goal="stamped in place", status=MissionStatus.RUNNING)
    now = datetime.now(timezone.utc)
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE missions (
                id VARCHAR(36) PRIMARY KEY,
                payload TEXT NOT NULL,
                updated_at DATETIME NOT NULL
            )
        """))
        conn.execute(text("""
            CREATE TABLE mission_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                mission_id VARCHAR(36),
                event_type VARCHAR(100),
                actor_id VARCHAR(36),
                payload TEXT,
                created_at DATETIME
            )
        """))
        conn.execute(text("""
            CREATE TABLE agents (
                id VARCHAR(36) PRIMARY KEY,
                mission_id VARCHAR(36) NOT NULL,
                payload TEXT NOT NULL,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL
            )
        """))
        conn.execute(text("""
            CREATE TABLE tasks (
                id VARCHAR(36) PRIMARY KEY,
                mission_id VARCHAR(36) NOT NULL,
                payload TEXT NOT NULL,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL
            )
        """))
        conn.execute(
            text("INSERT INTO missions (id, payload, updated_at) VALUES (:id, :payload, :updated_at)"),
            {"id": str(mission.id), "payload": mission.model_dump_json(), "updated_at": now},
        )
        conn.execute(text(
            "INSERT INTO mission_events (mission_id, event_type, actor_id, payload, created_at) "
            "VALUES (:mission_id, :event_type, NULL, :payload, :created_at)"
        ), {"mission_id": str(mission.id), "event_type": "mission.started",
            "payload": '{"goal": "stamped in place"}', "created_at": now})

    original = mission.model_dump_json()
    store = Store(str(path))
    assert store.get_mission(mission.id).goal == "stamped in place"
    with store.engine.connect() as conn:
        payload = conn.execute(text("SELECT payload FROM missions WHERE id = :id"),
                               {"id": str(mission.id)}).scalar()
    assert payload == original
    assert _version(store.engine) == CURRENT_SCHEMA_VERSION


def test_column_upgrade_preserves_existing_rows(tmp_path):
    engine = _engine(tmp_path / "upgrade.db")
    assert apply_migrations(engine) == CURRENT_SCHEMA_VERSION

    mission = Mission(goal="survive alter", status=MissionStatus.COMPLETED)
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO missions (id, payload, updated_at) VALUES (:id, :payload, :updated_at)"),
            {"id": str(mission.id), "payload": mission.model_dump_json(),
             "updated_at": datetime.now(timezone.utc)},
        )

    def add_notes(conn):
        added = add_column_if_missing(conn, "missions", "notes", "TEXT")
        assert added

    extra = MIGRATIONS + (Migration(CURRENT_SCHEMA_VERSION + 1, "add_mission_notes", add_notes),)
    assert apply_migrations(engine, extra) == CURRENT_SCHEMA_VERSION + 1
    with engine.connect() as conn:
        columns = {col["name"] for col in inspect(conn).get_columns("missions")}
        assert "notes" in columns
        row = conn.execute(
            text("SELECT payload, notes FROM missions WHERE id = :id"),
            {"id": str(mission.id)},
        ).one()
        assert Mission.model_validate_json(row[0]).goal == "survive alter"
        assert row[1] is None
        assert current_version(conn) == CURRENT_SCHEMA_VERSION + 1

    assert apply_migrations(engine, extra) == CURRENT_SCHEMA_VERSION + 1


def test_failed_migration_rolls_back_and_keeps_data(tmp_path):
    engine = _engine(tmp_path / "rollback.db")
    apply_migrations(engine)
    mission = Mission(goal="do not drop me")
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO missions (id, payload, updated_at) VALUES (:id, :payload, :updated_at)"),
            {"id": str(mission.id), "payload": mission.model_dump_json(),
             "updated_at": datetime.now(timezone.utc)},
        )

    def boom(conn):
        add_column_if_missing(conn, "missions", "boom", "TEXT")
        raise RuntimeError("upgrade failed")

    with pytest.raises(RuntimeError, match="upgrade failed"):
        apply_migrations(engine, MIGRATIONS + (Migration(CURRENT_SCHEMA_VERSION + 1, "boom", boom),))

    assert _version(engine) == CURRENT_SCHEMA_VERSION
    with engine.connect() as conn:
        payload = conn.execute(text("SELECT payload FROM missions WHERE id = :id"),
                               {"id": str(mission.id)}).scalar()
    assert Mission.model_validate_json(payload).goal == "do not drop me"

    # SQLite may keep ADD COLUMN even when the version row rolls back.
    # The stamp is the fail-closed record; retry must be idempotent.
    def add_boom(conn):
        add_column_if_missing(conn, "missions", "boom", "TEXT")

    assert apply_migrations(engine, MIGRATIONS + (Migration(CURRENT_SCHEMA_VERSION + 1, "boom", add_boom),)) == CURRENT_SCHEMA_VERSION + 1
    with engine.connect() as conn:
        columns = {col["name"] for col in inspect(conn).get_columns("missions")}
        assert "boom" in columns
        assert current_version(conn) == CURRENT_SCHEMA_VERSION + 1


def test_v1_database_upgrades_to_lease_tables_without_losing_rows(tmp_path):
    path = tmp_path / "v1.db"
    engine = _engine(path)
    assert apply_migrations(engine, MIGRATIONS[:1]) == 1
    mission = Mission(goal="keep through v2", status=MissionStatus.COMPLETED)
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO missions (id, payload, updated_at) VALUES (:id, :payload, :updated_at)"),
            {"id": str(mission.id), "payload": mission.model_dump_json(),
             "updated_at": datetime.now(timezone.utc)},
        )
        names = {row[0] for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
    assert "worker_leases" not in names
    assert "idempotency_keys" not in names

    store = Store(str(path))
    assert _version(store.engine) == CURRENT_SCHEMA_VERSION
    names = set(inspect(store.engine).get_table_names())
    assert {"worker_leases", "idempotency_keys", "work_items", "memory_notes",
            "provider_outcomes"} <= names
    loaded = store.get_mission(mission.id)
    assert loaded is not None
    assert loaded.goal == "keep through v2"


def test_v2_database_upgrades_to_work_items_without_losing_rows(tmp_path):
    path = tmp_path / "v2.db"
    engine = _engine(path)
    assert apply_migrations(engine, MIGRATIONS[:2]) == 2
    mission = Mission(goal="keep through v3", status=MissionStatus.COMPLETED)
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO missions (id, payload, updated_at) VALUES (:id, :payload, :updated_at)"),
            {"id": str(mission.id), "payload": mission.model_dump_json(),
             "updated_at": datetime.now(timezone.utc)},
        )
        names = {row[0] for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
    assert "work_items" not in names
    assert "worker_leases" in names

    store = Store(str(path))
    assert _version(store.engine) == CURRENT_SCHEMA_VERSION
    names = set(inspect(store.engine).get_table_names())
    assert "work_items" in names
    assert "memory_notes" in names
    assert "provider_outcomes" in names
    loaded = store.get_mission(mission.id)
    assert loaded is not None
    assert loaded.goal == "keep through v3"


def test_v3_database_upgrades_to_memory_notes_without_losing_rows(tmp_path):
    path = tmp_path / "v3.db"
    engine = _engine(path)
    assert apply_migrations(engine, MIGRATIONS[:3]) == 3
    mission = Mission(goal="keep through v4", status=MissionStatus.COMPLETED)
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO missions (id, payload, updated_at) VALUES (:id, :payload, :updated_at)"),
            {"id": str(mission.id), "payload": mission.model_dump_json(),
             "updated_at": datetime.now(timezone.utc)},
        )
        names = {row[0] for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
    assert "memory_notes" not in names
    assert "work_items" in names

    store = Store(str(path))
    assert _version(store.engine) == CURRENT_SCHEMA_VERSION
    names = set(inspect(store.engine).get_table_names())
    assert "memory_notes" in names
    assert "provider_outcomes" in names
    loaded = store.get_mission(mission.id)
    assert loaded is not None
    assert loaded.goal == "keep through v4"


def test_v4_database_upgrades_to_provider_outcomes_without_losing_rows(tmp_path):
    path = tmp_path / "v4.db"
    engine = _engine(path)
    assert apply_migrations(engine, MIGRATIONS[:4]) == 4
    mission = Mission(goal="keep through v5", status=MissionStatus.COMPLETED)
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO missions (id, payload, updated_at) VALUES (:id, :payload, :updated_at)"),
            {"id": str(mission.id), "payload": mission.model_dump_json(),
             "updated_at": datetime.now(timezone.utc)},
        )
        names = {row[0] for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
    assert "provider_outcomes" not in names
    assert "memory_notes" in names

    store = Store(str(path))
    assert _version(store.engine) == CURRENT_SCHEMA_VERSION
    names = set(inspect(store.engine).get_table_names())
    assert "provider_outcomes" in names
    loaded = store.get_mission(mission.id)
    assert loaded is not None
    assert loaded.goal == "keep through v5"


def test_newer_database_fails_closed(tmp_path):
    engine = _engine(tmp_path / "future.db")
    apply_migrations(engine)
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO schema_migrations (version, name, applied_at) VALUES (99, 'future', :t)"),
            {"t": datetime.now(timezone.utc)},
        )
    with pytest.raises(MigrationError, match="newer than this build"):
        apply_migrations(engine)
    assert _version(engine) == 99


def test_duplicate_versions_fail_closed():
    engine = create_engine("sqlite://")
    with pytest.raises(MigrationError, match="duplicate"):
        apply_migrations(engine, MIGRATIONS + (Migration(1, "again", lambda _conn: None),))
