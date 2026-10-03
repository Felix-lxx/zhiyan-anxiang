from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.routes.auth import AuthenticatedIdentity, get_current_identity
from app.core.database import get_db
from app.models.account import AccountPreferences
from app.models.domain import Community, Scene, User
from app.models.operations import DrillScore, DrillSession
from app.services.access import ensure_development_user

router = APIRouter(prefix="/account", tags=["account"])


class ProfileUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    display_name: str = Field(min_length=1, max_length=64)
    organization: str = Field(default="", max_length=100)
    default_community_id: str | None = Field(default=None, max_length=36)
    text_size: Literal["comfortable", "large"] = "comfortable"
    reduced_motion: bool = False
    revision: int = Field(ge=0)


def serialize_profile(identity, user, stored):
    preferences = stored.preferences if stored else {}
    return {
        "username": identity.username, "role": identity.role,
        "display_name": user.display_name if user else identity.username,
        "organization": stored.organization if stored else "",
        "default_community_id": preferences.get("default_community_id"),
        "text_size": preferences.get("text_size", "comfortable"),
        "reduced_motion": preferences.get("reduced_motion", False),
        "revision": stored.revision if stored else 0,
        "updated_at": stored.updated_at if stored else None,
        "authentication_mode": "account_session" if identity.session_id else "development_legacy",
    }


@router.get("/profile")
def get_profile(identity: AuthenticatedIdentity = Depends(get_current_identity), session: Session = Depends(get_db)):
    user = session.scalar(select(User).where(User.username == identity.username))
    stored = session.get(AccountPreferences, user.id) if user else None
    return serialize_profile(identity, user, stored)


@router.patch("/profile")
def update_profile(payload: ProfileUpdate, identity: AuthenticatedIdentity = Depends(get_current_identity), session: Session = Depends(get_db)):
    if payload.default_community_id:
        community = session.scalar(select(Community).join(User, Community.owner_id == User.id).where(
            Community.id == payload.default_community_id, User.username == identity.username))
        if community is None:
            raise HTTPException(422, "默认社区不存在或不属于当前账号，请重新选择。")
    try:
        user = session.scalar(select(User).where(User.username == identity.username))
        if user is None:
            user = ensure_development_user(session, identity.username)
        stored = session.get(AccountPreferences, user.id)
        preferences = payload.model_dump(include={"default_community_id", "text_size", "reduced_motion"})
        if stored:
            result = session.execute(update(AccountPreferences).where(
                AccountPreferences.user_id == user.id, AccountPreferences.revision == payload.revision
            ).values(organization=payload.organization, preferences=preferences, revision=payload.revision + 1))
            if result.rowcount != 1:
                raise HTTPException(409, "资料已在另一页面更新。请重新载入最新资料后再保存。")
        else:
            if payload.revision != 0:
                raise HTTPException(409, "资料版本已变化，请重新载入。")
            stored = AccountPreferences(user_id=user.id, organization=payload.organization, preferences=preferences, revision=1)
            session.add(stored)
        user.display_name = payload.display_name
        session.commit()
        session.refresh(stored)
        return serialize_profile(identity, user, stored)
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(409, "资料正在被更新，请重新载入后再保存。") from exc
    except Exception:
        session.rollback()
        raise


@router.get("/activity")
def get_activity(identity: AuthenticatedIdentity = Depends(get_current_identity), session: Session = Depends(get_db)):
    """Counts and recent records are owner-scoped DB reads, never simulation ticks."""
    owned = select(Community.id).join(User, Community.owner_id == User.id).where(User.username == identity.username)
    scenes = select(Scene.id).where(Scene.community_id.in_(owned))
    counts = dict(session.execute(select(DrillSession.status, func.count()).where(DrillSession.scene_id.in_(scenes)).group_by(DrillSession.status)).all())
    recent = session.execute(select(DrillSession, Scene.community_id, Community.name, DrillScore.total_score)
        .join(Scene, DrillSession.scene_id == Scene.id).join(Community, Scene.community_id == Community.id)
        .outerjoin(DrillScore, DrillScore.drill_session_id == DrillSession.id)
        .where(Community.id.in_(owned)).order_by(DrillSession.created_at.desc(), DrillSession.id).limit(6)).all()
    return {
        "community_count": session.scalar(select(func.count()).select_from(Community).where(Community.id.in_(owned))),
        "drill_count": sum(counts.values()), "completed_count": counts.get("ended", 0),
        "unfinished_count": sum(v for k, v in counts.items() if k != "ended"),
        "recent": [{"id": drill.id, "name": drill.name, "status": drill.status,
                    "scene_id": drill.scene_id, "community_id": community_id, "community_name": name,
                    "created_at": drill.created_at, "score": score} for drill, community_id, name, score in recent],
    }
