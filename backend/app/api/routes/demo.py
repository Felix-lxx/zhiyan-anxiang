from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.routes.auth import AuthenticatedIdentity, get_current_identity
from app.api.routes.communities import serialize_community
from app.core.database import get_db
from app.schemas.community import CommunityRead
from app.services.demo_community import get_or_create_demo_community
from app.services.demo_experience import ensure_demo_experience


router = APIRouter(prefix="/communities", tags=["demo community"])


@router.post("/demo", response_model=CommunityRead, status_code=status.HTTP_201_CREATED)
def post_demo_community(
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    session: Session = Depends(get_db),
) -> CommunityRead:
    try:
        community, _ = get_or_create_demo_community(session, identity.username)
        return serialize_community(community)
    except SQLAlchemyError as exc:
        session.rollback()
        raise HTTPException(status_code=503, detail="主案例数据生成失败，请检查数据库连接。") from exc


@router.post("/demo-ready", status_code=status.HTTP_201_CREATED)
def post_demo_ready(
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    session: Session = Depends(get_db),
):
    try:
        community, scene, drill = ensure_demo_experience(session, identity.username)
        return {
            "community": serialize_community(community),
            "scene_id": scene.id,
            "drill_id": drill.id,
            "message": "三维数字孪生演练已准备完成。",
        }
    except (SQLAlchemyError, RuntimeError) as exc:
        session.rollback()
        raise HTTPException(status_code=503, detail="三维演示初始化失败，请检查数据库连接和主案例数据。") from exc
