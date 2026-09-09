from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload
from app.api.routes.auth import AuthenticatedIdentity, get_current_identity
from app.api.routes.scenes import owned_community
from app.core.database import get_db
from app.models.domain import DecisionOption, DecisionPoint, Scene
from app.schemas.decision import DecisionPointCreate, DecisionPointRead

router=APIRouter(tags=["decisions"])
def scene_for_user(session:Session, scene_id:str, username:str)->Scene:
    scene=session.scalar(select(Scene).where(Scene.id==scene_id).options(selectinload(Scene.versions)))
    if scene is None: raise HTTPException(status_code=404,detail="未找到该场景草稿。")
    owned_community(session,scene.community_id,username); return scene
@router.get('/scenes/{scene_id}/decision-points',response_model=list[DecisionPointRead])
def list_points(scene_id:str,identity:AuthenticatedIdentity=Depends(get_current_identity),session:Session=Depends(get_db)):
    scene=scene_for_user(session,scene_id,identity.username); version=scene.versions[-1]
    return list(session.scalars(select(DecisionPoint).where(DecisionPoint.scene_version_id==version.id).options(selectinload(DecisionPoint.options))))
@router.post('/scenes/{scene_id}/decision-points',response_model=DecisionPointRead,status_code=status.HTTP_201_CREATED)
def create_point(scene_id:str,payload:DecisionPointCreate,identity:AuthenticatedIdentity=Depends(get_current_identity),session:Session=Depends(get_db)):
    scene=scene_for_user(session,scene_id,identity.username); point=DecisionPoint(scene_version_id=scene.versions[-1].id,name=payload.name,trigger_condition=payload.trigger_condition,responsible_role=payload.responsible_role,time_limit_seconds=payload.time_limit_seconds);session.add(point);session.flush()
    for item in payload.options: session.add(DecisionOption(decision_point_id=point.id,label=item.label,consequence=item.consequence))
    session.commit();return session.scalar(select(DecisionPoint).where(DecisionPoint.id==point.id).options(selectinload(DecisionPoint.options)))
