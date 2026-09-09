from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.routes.auth import AuthenticatedIdentity, get_current_identity
from app.core.database import get_db
from app.models.domain import MapObject
from app.schemas.map_object import MapObjectCreate, MapObjectRead, MapObjectUpdate
from app.services.communities import get_community_or_none
from app.services.map_objects import (
    create_map_object,
    current_version,
    delete_map_object,
    get_map_object_or_none,
    list_map_objects,
    update_map_object,
)


router = APIRouter(prefix="/communities/{community_id}/map-objects", tags=["map objects"])


def serialize_map_object(map_object: MapObject) -> MapObjectRead:
    return MapObjectRead(
        id=map_object.id,
        community_version_id=map_object.community_version_id,
        object_type=map_object.object_type,
        name=map_object.name,
        geometry=map_object.geometry,
        properties=map_object.properties,
        created_at=map_object.created_at,
        updated_at=map_object.updated_at,
    )


def require_current_version(session: Session, community_id: str, username: str):
    community = get_community_or_none(session, community_id)
    if community is None or community.owner.username != username:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="未找到该社区项目。")
    version = current_version(community)
    if version is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="该社区尚未生成可编辑版本。")
    return version


@router.get("", response_model=list[MapObjectRead])
def get_map_objects(
    community_id: str,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    session: Session = Depends(get_db),
) -> list[MapObjectRead]:
    try:
        version = require_current_version(session, community_id, identity.username)
        return [serialize_map_object(item) for item in list_map_objects(session, version.id)]
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="地图数据服务暂不可用，请检查 PostgreSQL 连接。",
        ) from exc


@router.post("", response_model=MapObjectRead, status_code=status.HTTP_201_CREATED)
def post_map_object(
    community_id: str,
    payload: MapObjectCreate,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    session: Session = Depends(get_db),
) -> MapObjectRead:
    try:
        version = require_current_version(session, community_id, identity.username)
        map_object = create_map_object(
            session,
            community_version_id=version.id,
            object_type=payload.object_type,
            name=payload.name,
            geometry=payload.geometry.model_dump(),
            properties=payload.properties,
        )
        return serialize_map_object(map_object)
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="地图数据服务暂不可用，请检查 PostgreSQL 连接。",
        ) from exc


@router.patch("/{object_id}", response_model=MapObjectRead)
def patch_map_object(
    community_id: str,
    object_id: str,
    payload: MapObjectUpdate,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    session: Session = Depends(get_db),
) -> MapObjectRead:
    try:
        version = require_current_version(session, community_id, identity.username)
        map_object = get_map_object_or_none(session, object_id=object_id, community_version_id=version.id)
        if map_object is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="未找到该地图对象。")
        updated = update_map_object(
            session,
            map_object,
            object_type=payload.object_type,
            name=payload.name,
            geometry=payload.geometry.model_dump() if payload.geometry else None,
            properties=payload.properties,
        )
        return serialize_map_object(updated)
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="地图数据服务暂不可用，请检查 PostgreSQL 连接。",
        ) from exc


@router.delete("/{object_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_map_object(
    community_id: str,
    object_id: str,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    session: Session = Depends(get_db),
) -> Response:
    try:
        version = require_current_version(session, community_id, identity.username)
        map_object = get_map_object_or_none(session, object_id=object_id, community_version_id=version.id)
        if map_object is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="未找到该地图对象。")
        delete_map_object(session, map_object)
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="地图数据服务暂不可用，请检查 PostgreSQL 连接。",
        ) from exc
