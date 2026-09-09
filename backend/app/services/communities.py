from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.domain import Community, CommunityStatus, CommunityVersion, CommunityVersionStatus
from app.services.access import ensure_development_user


def create_community(
    session: Session,
    *,
    owner_username: str,
    name: str,
    address: str | None,
    description: str | None,
) -> Community:
    owner = ensure_development_user(session, owner_username)
    community = Community(
        name=name,
        address=address,
        description=description,
        status=CommunityStatus.DRAFT,
        owner_id=owner.id,
    )
    session.add(community)
    session.flush()
    session.add(
        CommunityVersion(
            community_id=community.id,
            version_number=1,
            name="初始社区版本",
            status=CommunityVersionStatus.DRAFT,
            map_snapshot={"objects": [], "schema_version": 1},
        )
    )
    session.commit()
    return get_community_or_none(session, community.id)  # type: ignore[return-value]


def list_communities(session: Session, owner_username: str) -> list[Community]:
    statement = (
        select(Community)
        .join(Community.owner)
        .where(Community.owner.has(username=owner_username))
        .options(selectinload(Community.owner), selectinload(Community.versions))
        .order_by(Community.updated_at.desc())
    )
    return list(session.scalars(statement))


def get_community_or_none(session: Session, community_id: str) -> Community | None:
    statement = (
        select(Community)
        .where(Community.id == community_id)
        .options(selectinload(Community.owner), selectinload(Community.versions))
    )
    return session.scalar(statement)
