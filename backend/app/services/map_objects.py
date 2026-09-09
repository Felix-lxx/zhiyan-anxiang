from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.domain import Community, CommunityVersion, MapObject, MapObjectType


def current_version(community: Community) -> CommunityVersion | None:
    """返回当前可编辑的最高版本；版本关系已按版本号升序加载。"""

    return community.versions[-1] if community.versions else None


def list_map_objects(session: Session, community_version_id: str) -> list[MapObject]:
    statement = (
        select(MapObject)
        .where(MapObject.community_version_id == community_version_id)
        .order_by(MapObject.created_at.asc())
    )
    return list(session.scalars(statement))


def create_map_object(
    session: Session,
    *,
    community_version_id: str,
    object_type: MapObjectType,
    name: str,
    geometry: dict[str, float],
    properties: dict,
) -> MapObject:
    map_object = MapObject(
        community_version_id=community_version_id,
        object_type=object_type,
        name=name,
        geometry=geometry,
        properties=properties,
    )
    session.add(map_object)
    session.commit()
    session.refresh(map_object)
    return map_object


def get_map_object_or_none(session: Session, *, object_id: str, community_version_id: str) -> MapObject | None:
    statement = select(MapObject).where(
        MapObject.id == object_id,
        MapObject.community_version_id == community_version_id,
    )
    return session.scalar(statement)


def update_map_object(
    session: Session,
    map_object: MapObject,
    *,
    object_type: MapObjectType | None,
    name: str | None,
    geometry: dict[str, float] | None,
    properties: dict | None,
) -> MapObject:
    if object_type is not None:
        map_object.object_type = object_type
    if name is not None:
        map_object.name = name
    if geometry is not None:
        map_object.geometry = geometry
    if properties is not None:
        map_object.properties = properties
    session.commit()
    session.refresh(map_object)
    return map_object


def delete_map_object(session: Session, map_object: MapObject) -> None:
    session.delete(map_object)
    session.commit()
