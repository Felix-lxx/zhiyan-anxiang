from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.routes.auth import AuthenticatedIdentity, get_current_identity
from app.core.database import get_db
from app.schemas.role import RoleRead
from app.services.access import ensure_role_catalog


router = APIRouter(prefix="/roles", tags=["roles"])


@router.get("", response_model=list[RoleRead])
def get_roles(
    _: AuthenticatedIdentity = Depends(get_current_identity),
    session: Session = Depends(get_db),
) -> list[RoleRead]:
    try:
        roles = ensure_role_catalog(session)
        session.commit()
        return [RoleRead.model_validate(role) for role in roles]
    except SQLAlchemyError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="角色数据服务暂不可用，请检查 PostgreSQL 连接。",
        ) from exc
