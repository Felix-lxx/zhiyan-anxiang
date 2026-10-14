from fastapi import APIRouter, Depends, HTTPException, Query, status
from datetime import datetime
from typing import Literal
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.routes.auth import AuthenticatedIdentity, get_current_identity
from app.core.database import get_db
from app.models.domain import Community
from app.schemas.community import CommunityCreate, CommunityRead, CommunityUpdate
from app.services.communities import create_community, get_community_or_none, list_communities


router = APIRouter(prefix="/communities", tags=["communities"])


@router.get('/{community_id}/drill-history')
def get_drill_history(community_id: str, page: int = Query(1, ge=1),
                      page_size: int = Query(20, ge=1, le=100), search: str = Query('', max_length=160),
                      status: Literal['all', 'ready', 'running', 'paused', 'ended'] = 'all',
                      scene_id: str | None = None, start: datetime | None = None, end: datetime | None = None,
                      sort: Literal['newest', 'oldest', 'score'] = 'newest',
                      identity: AuthenticatedIdentity = Depends(get_current_identity), session: Session = Depends(get_db)):
    if (start and start.tzinfo is None) or (end and end.tzinfo is None):
        raise HTTPException(422, '日期筛选必须包含时区。')
    if start and end and start > end:
        raise HTTPException(422, '截止日期不能早于开始日期。')
    from app.services.drill_history import history_page
    try:
        community = get_community_or_none(session, community_id)
        if community is None or community.owner.username != identity.username:
            raise HTTPException(404, '未找到该社区项目。')
        return history_page(session, community_id, page=page, page_size=page_size, search=search,
                            status=status, scene_id=scene_id, start=start, end=end, sort=sort)
    except SQLAlchemyError as exc:
        raise HTTPException(503, '演练记录暂不可用，请重试。') from exc


def serialize_community(community: Community) -> CommunityRead:
    return CommunityRead(
        id=community.id,
        name=community.name,
        address=community.address,
        description=community.description,
        status=community.status,
        created_at=community.created_at,
        updated_at=community.updated_at,
        owner_username=community.owner.username,
        versions=community.versions,
    )


@router.get("", response_model=list[CommunityRead])
def get_communities(
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    session: Session = Depends(get_db),
) -> list[CommunityRead]:
    try:
        return [serialize_community(community) for community in list_communities(session, identity.username)]
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="社区数据服务暂不可用，请检查 PostgreSQL 连接。",
        ) from exc


@router.post("", response_model=CommunityRead, status_code=status.HTTP_201_CREATED)
def post_community(
    payload: CommunityCreate,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    session: Session = Depends(get_db),
) -> CommunityRead:
    try:
        community = create_community(
            session,
            owner_username=identity.username,
            name=payload.name,
            address=payload.address,
            description=payload.description,
        )
        return serialize_community(community)
    except SQLAlchemyError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="社区数据服务暂不可用，请检查 PostgreSQL 连接。",
        ) from exc


@router.get("/{community_id}", response_model=CommunityRead)
def get_community(
    community_id: str,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    session: Session = Depends(get_db),
) -> CommunityRead:
    try:
        community = get_community_or_none(session, community_id)
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="社区数据服务暂不可用，请检查 PostgreSQL 连接。",
        ) from exc

    if community is None or community.owner.username != identity.username:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="未找到该社区项目。")
    return serialize_community(community)


@router.patch("/{community_id}", response_model=CommunityRead)
def patch_community(community_id: str, payload: CommunityUpdate,
                    identity: AuthenticatedIdentity = Depends(get_current_identity),
                    session: Session = Depends(get_db)):
    from datetime import UTC, datetime
    from sqlalchemy import update
    community = get_community_or_none(session, community_id)
    if community is None or community.owner.username != identity.username:
        raise HTTPException(404, "未找到该社区项目。")
    normalize = lambda value: value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    if normalize(payload.expected_updated_at) != normalize(community.updated_at):
        raise HTTPException(409, "社区资料已在其他页面更新，请载入最新资料后再编辑。当前输入尚未保存。")
    try:
        result = session.execute(update(Community).where(
            Community.id == community.id, Community.updated_at == community.updated_at,
        ).values(name=payload.name, address=payload.address or None,
                 description=payload.description or None, updated_at=datetime.now(UTC))
          .execution_options(synchronize_session=False))
        if result.rowcount != 1:
            session.rollback()
            raise HTTPException(409, "资料刚刚发生变化，请重新载入后编辑。")
        session.commit()
        session.expire_all()
        return serialize_community(get_community_or_none(session, community_id))
    except SQLAlchemyError as exc:
        session.rollback()
        raise HTTPException(503, "社区资料保存失败，请稍后重试；未确认成功前请保留输入。") from exc


@router.get("/{community_id}/readiness")
def get_readiness(community_id: str,
                  identity: AuthenticatedIdentity = Depends(get_current_identity),
                  session: Session = Depends(get_db)):
    community = get_community_or_none(session, community_id)
    if community is None or community.owner.username != identity.username:
        raise HTTPException(404, "未找到该社区项目。")
    from app.services.community_readiness import inspect_community
    return inspect_community(session, community)
