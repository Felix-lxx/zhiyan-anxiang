"""Authenticated task explanation with explicit, versioned knowledge retrieval."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.api.routes import operations
from app.api.routes.auth import AuthenticatedIdentity, get_current_identity
from app.core.database import get_db
from app.models.domain import Scene
from app.services.knowledge import retrieve, seed_knowledge
from app.services.knowledge_applicability import situation
from app.services.task_guidance import guidance_view

router = APIRouter(tags=['task guidance'])


class GuidanceRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')


@router.post('/drills/{drill_id}/tasks/{task_id}/guidance')
def explain_task(drill_id: str, task_id: str, payload: GuidanceRequest,
                 identity: AuthenticatedIdentity = Depends(get_current_identity), session: Session = Depends(get_db)):
    drill = operations.require_drill(session, drill_id, identity.username)
    data = operations.snapshot(session, drill)
    task = next((item for item in data['tasks'] if item['id'] == task_id), None)
    if task is None:
        raise HTTPException(404, '未找到本场处置任务。')
    # The direct task entry must also work before the knowledge page is opened.
    seed_knowledge(session)
    scene = session.get(Scene, drill.scene_id)
    result = guidance_view(data, task)
    parameters = data['simulation'].get('world', {}).get('parameters', {})
    result['knowledge'] = retrieve(session, identity.username, result.pop('query'),
        community_id=scene.community_id, drill_id=drill.id,
        scenario='kitchen_fire' if parameters.get('fire_source_type') == 'kitchen' else 'charging_shed',
        semantic=False, situation=situation(data))
    session.commit()  # Persist citation history only; no domain command is issued.
    return result
