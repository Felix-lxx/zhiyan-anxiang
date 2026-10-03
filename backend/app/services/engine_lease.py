"""Database-backed ownership lease for multi-worker drill scheduling."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import os
import socket
from uuid import uuid4

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.operations import DrillEngineLease


PROCESS_OWNER_ID = f"{socket.gethostname()}:{os.getpid()}:{uuid4().hex[:12]}"


def acquire_engine_lease(
    session: Session,
    drill_id: str,
    *,
    owner_id: str = PROCESS_OWNER_ID,
    now: datetime | None = None,
    ttl_seconds: int = 4,
) -> bool:
    now = now or datetime.now(UTC)
    expires = now + timedelta(seconds=ttl_seconds)
    updated = session.execute(
        update(DrillEngineLease)
        .where(
            DrillEngineLease.drill_session_id == drill_id,
            or_(DrillEngineLease.owner_id == owner_id, DrillEngineLease.lease_expires_at <= now),
        )
        .values(owner_id=owner_id, lease_expires_at=expires, updated_at=now)
    )
    if updated.rowcount:
        return True
    if session.scalar(select(DrillEngineLease.drill_session_id).where(DrillEngineLease.drill_session_id == drill_id)):
        return False
    try:
        with session.begin_nested():
            session.add(DrillEngineLease(
                drill_session_id=drill_id,
                owner_id=owner_id,
                lease_expires_at=expires,
                updated_at=now,
            ))
            session.flush()
        return True
    except IntegrityError:
        return False
