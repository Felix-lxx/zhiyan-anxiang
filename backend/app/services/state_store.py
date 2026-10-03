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
    record = DrillStateSnapshot(
        drill_session_id=drill.id,
        state_version=version,
        event_sequence=int(payload.get("latest_event_sequence", 0)),
        elapsed_seconds=elapsed,
        payload=deepcopy(payload),
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
    return deepcopy(record.payload) if record else None
