from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.api.routes.auth import AuthenticatedIdentity,get_current_identity
from app.api.routes.scenes import owned_community
from app.core.database import get_db
from app.models.domain import DecisionOption,DecisionPoint,Scene
from app.models.tasks import DecisionTask
router=APIRouter(tags=['tasks'])
def point_for_user(session:Session,point_id:str,user:str):
 p=session.get(DecisionPoint,point_id)
 if not p:raise HTTPException(404,'未找到决策点。')
 # 查找场景版本归属，确保权限
 scene=session.scalar(select(Scene).join(Scene.versions).where(Scene.versions.any(id=p.scene_version_id)))
 if not scene:raise HTTPException(404,'未找到场景。')
 owned_community(session,scene.community_id,user);return p
@router.post('/decision-options/{option_id}/execute',status_code=status.HTTP_201_CREATED)
def execute(option_id:str,identity:AuthenticatedIdentity=Depends(get_current_identity),session:Session=Depends(get_db)):
 opt=session.get(DecisionOption,option_id)
 if not opt:raise HTTPException(404,'未找到决策选项。')
 p=point_for_user(session,opt.decision_point_id,identity.username)
 task=DecisionTask(decision_point_id=p.id,scene_version_id=p.scene_version_id,title=f'处置：{opt.label}',target=opt.consequence,deadline_seconds=p.time_limit_seconds)
 session.add(task);session.commit();return {'id':task.id,'title':task.title,'target':task.target,'deadline_seconds':task.deadline_seconds,'status':task.status}
@router.get('/scenes/{scene_id}/tasks')
def list_tasks(scene_id:str,identity:AuthenticatedIdentity=Depends(get_current_identity),session:Session=Depends(get_db)):
 scene=session.get(Scene,scene_id)
 if not scene:raise HTTPException(404,'未找到场景。')
 owned_community(session,scene.community_id,identity.username);v=scene.versions[-1]
 return list(session.scalars(select(DecisionTask).where(DecisionTask.scene_version_id==v.id)))
