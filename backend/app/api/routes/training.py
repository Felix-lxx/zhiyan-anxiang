"""Read frozen training archives and explicitly backfill historical runs."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.routes.auth import AuthenticatedIdentity, get_current_identity
from app.api.routes import operations
from app.core.database import get_db
from app.models.training import DrillArchive
from app.models.operations import DrillSession
from app.services.command_lock import serialized_command
from app.services.training_archive import archive_drill, archive_payload

router = APIRouter(tags=['training archives'])


@router.get('/drills/{drill_id}/archive')
def get_archive(drill_id: str, identity: AuthenticatedIdentity = Depends(get_current_identity),
                session: Session = Depends(get_db)):
    operations.require_drill(session, drill_id, identity.username)
    record = session.scalar(select(DrillArchive).where(DrillArchive.drill_session_id == drill_id))
    return {'archive': archive_payload(session, record) if record else None}


@router.post('/drills/{drill_id}/archive')
@serialized_command
def backfill_archive(drill_id: str, identity: AuthenticatedIdentity = Depends(get_current_identity),
                     session: Session = Depends(get_db)):
    drill = operations.require_drill(session, drill_id, identity.username)
    session.execute(select(DrillSession.id).where(DrillSession.id == drill_id).with_for_update())
    if drill.status != 'ended':
        raise HTTPException(409, '仅已结束训练可以补建档案。')
    record = archive_drill(session, drill, operations.snapshot(session, drill), identity.username, backfill=True)
    session.commit()
    return {'archive': archive_payload(session, record)}
