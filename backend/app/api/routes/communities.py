from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.routes.auth import AuthenticatedIdentity, get_current_identity
from app.core.database import get_db
from app.models.domain import Community
from app.schemas.community import CommunityCreate, CommunityRead
from app.services.communities import create_community, get_community_or_none, list_communities


router = APIRouter(prefix="/communities", tags=["communities"])


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
