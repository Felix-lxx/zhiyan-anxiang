"""Small idempotent migration runner for the current deployable monolith."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import inspect, text, select, update
from sqlalchemy.engine import Engine


def run_schema_migrations(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "version VARCHAR(64) PRIMARY KEY, applied_at TIMESTAMP NOT NULL)"
        ))
        applied = {row[0] for row in connection.execute(text("SELECT version FROM schema_migrations"))}
        if '20261030_01_demo_kitchen_floor' not in applied:
            inspector = inspect(connection)
            if all(inspector.has_table(name) for name in ('communities', 'community_versions', 'map_objects')):
                from app.models.domain import Community, CommunityVersion, MapObject, MapObjectType
                from app.services.demo_community import DEMO_COMMUNITY_NAME, DEMO_KITCHEN_PROPERTIES
                houses = connection.execute(select(MapObject.id, MapObject.properties).join(
                    CommunityVersion, MapObject.community_version_id == CommunityVersion.id
                ).join(Community, CommunityVersion.community_id == Community.id).where(
                    Community.name == DEMO_COMMUNITY_NAME, MapObject.object_type == MapObjectType.BUILDING,
                    MapObject.name == '1 号楼'))
                for house_id, properties in houses:
                    if not ({'width', 'depth'} & properties.keys()):
                        connection.execute(update(MapObject).where(MapObject.id == house_id).values(
                            properties={**properties, **DEMO_KITCHEN_PROPERTIES}))
                connection.execute(text('INSERT INTO schema_migrations(version, applied_at) VALUES (:version, :applied_at)'),
                    {'version': '20261030_01_demo_kitchen_floor', 'applied_at': datetime.now(UTC).isoformat()})
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
            inspector = inspect(connection)
            # A migration may be invoked by an upgrade probe against a legacy,
            # intentionally partial database.  Never create an index before its
            # owning table exists, and leave this version pending so normal
            # application startup can apply it after ``create_all``.
            all_tables_present = True
            for table in (DrillEvent.__table__, DrillStateSnapshot.__table__):
                if not inspector.has_table(table.name):
                    all_tables_present = False
                    continue
                for index in table.indexes:
                    if index.name in {"ix_drill_events_session_sequence", "ix_drill_snapshots_session_time"}:
                        index.create(bind=connection, checkfirst=True)
            if all_tables_present:
                connection.execute(text("INSERT INTO schema_migrations(version, applied_at) VALUES (:version, :applied_at)"),
                    {"version":"20261018_01_runtime_lookup_indexes", "applied_at":datetime.now(UTC).isoformat()})
