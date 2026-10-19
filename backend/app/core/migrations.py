"""Small idempotent migration runner for the current deployable monolith."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine


def run_schema_migrations(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "version VARCHAR(64) PRIMARY KEY, applied_at TIMESTAMP NOT NULL)"
        ))
        applied = {row[0] for row in connection.execute(text("SELECT version FROM schema_migrations"))}
        if "20261002_01_user_credentials" not in applied:
            inspector = inspect(connection)
            columns = {column["name"] for column in inspector.get_columns("users")} if inspector.has_table("users") else set()
            if "password_hash" not in columns:
                connection.execute(text("ALTER TABLE users ADD COLUMN password_hash VARCHAR(255)"))
            if "is_active" not in columns:
                connection.execute(text("ALTER TABLE users ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT TRUE"))
            connection.execute(
                text("INSERT INTO schema_migrations(version, applied_at) VALUES (:version, :applied_at)"),
                {"version": "20261002_01_user_credentials", "applied_at": datetime.now(UTC).isoformat()},
            )
        if "20261018_01_runtime_lookup_indexes" not in applied:
            from app.models.operations import DrillEvent, DrillStateSnapshot
            for table in (DrillEvent.__table__, DrillStateSnapshot.__table__):
                for index in table.indexes:
                    if index.name in {"ix_drill_events_session_sequence", "ix_drill_snapshots_session_time"}:
                        index.create(bind=connection, checkfirst=True)
            connection.execute(text("INSERT INTO schema_migrations(version, applied_at) VALUES (:version, :applied_at)"),
                {"version":"20261018_01_runtime_lookup_indexes", "applied_at":datetime.now(UTC).isoformat()})
