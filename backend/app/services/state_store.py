"""Durable materialized snapshots for fast reconnect and process restart recovery."""

from __future__ import annotations

from copy import deepcopy

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.operations import DrillSession, DrillStateSnapshot


SNAPSHOT_INTERVAL_SECONDS = 5
MAX_SNAPSHOTS_PER_DRILL = 120


def persist_snapshot(
    session: Session,
    drill: DrillSession,
    payload: dict,
    *,
    force: bool = False,
) -> DrillStateSnapshot | None:
    version = payload.get("state_version")
    if not version:
        return None
    latest = session.scalar(
        select(DrillStateSnapshot)
        .where(DrillStateSnapshot.drill_session_id == drill.id)
        .order_by(DrillStateSnapshot.elapsed_seconds.desc(), DrillStateSnapshot.created_at.desc())
        .limit(1)
    )
    if latest and latest.state_version == version:
        return latest
    elapsed = int(payload.get("elapsed_seconds", 0))
    if not force and latest and elapsed - latest.elapsed_seconds < SNAPSHOT_INTERVAL_SECONDS:
        return None
    stored_payload = deepcopy(payload)
    world = payload.get("simulation", {}).get("world")
    if world and world.get("schema_version", 0) >= 3:
        from app.services.simulation_checkpoints import recall
        checkpoint = recall(world, elapsed)
        if checkpoint and checkpoint["now"] == elapsed:
            stored_payload["_engine_checkpoint"] = checkpoint
    record = DrillStateSnapshot(
        drill_session_id=drill.id,
        state_version=version,
        event_sequence=int(payload.get("latest_event_sequence", 0)),
        elapsed_seconds=elapsed,
        payload=stored_payload,
    )
    try:
        with session.begin_nested():
            session.add(record)
            session.flush()
    except IntegrityError:
        return session.scalar(select(DrillStateSnapshot).where(
            DrillStateSnapshot.drill_session_id == drill.id,
            DrillStateSnapshot.state_version == version,
        ))
    stale_ids = list(session.scalars(
        select(DrillStateSnapshot.id)
        .where(DrillStateSnapshot.drill_session_id == drill.id)
        .order_by(DrillStateSnapshot.elapsed_seconds.desc(), DrillStateSnapshot.created_at.desc())
        .offset(MAX_SNAPSHOTS_PER_DRILL)
    ))
    if stale_ids:
        session.execute(delete(DrillStateSnapshot).where(DrillStateSnapshot.id.in_(stale_ids)))
    return record


def load_snapshot(session: Session, drill_id: str, version: str | None = None) -> dict | None:
    query = select(DrillStateSnapshot).where(DrillStateSnapshot.drill_session_id == drill_id)
    if version:
        query = query.where(DrillStateSnapshot.state_version == version)
    record = session.scalar(query.order_by(DrillStateSnapshot.elapsed_seconds.desc(), DrillStateSnapshot.created_at.desc()).limit(1))
    if not record:
        return None
    payload = deepcopy(record.payload)
    payload.pop("_engine_checkpoint", None)
    return payload


def restore_engine_checkpoint(session: Session, drill_id: str, world: dict, elapsed: int):
    """GET remains read-only; only existing engine snapshots seed the process cache."""
    from app.services.simulation_checkpoints import recall, remember
    if recall(world, elapsed) is not None:
        return
    record = session.scalar(select(DrillStateSnapshot).where(
        DrillStateSnapshot.drill_session_id == drill_id,
        DrillStateSnapshot.elapsed_seconds <= elapsed,
    ).order_by(DrillStateSnapshot.elapsed_seconds.desc(), DrillStateSnapshot.created_at.desc()).limit(1))
    if record:
        remember(world, record.payload.get("_engine_checkpoint"))
