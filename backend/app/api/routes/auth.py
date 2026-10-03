from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.security import create_access_token, create_refresh_token, decode_access_claims, hash_password, hash_refresh_token, verify_password
from app.models.auth import AuthSession, LoginSecurity
from app.models.domain import Role, RoleCode, User, UserRole
from app.services.access import ensure_development_user, ensure_role_catalog


router = APIRouter(prefix="/auth", tags=["auth"])
REFRESH_COOKIE = "zhiyan_refresh_token"
MANAGEMENT_ROLES = {RoleCode.SYSTEM_ADMIN, RoleCode.EXERCISE_DESIGNER, RoleCode.DRILL_DIRECTOR, RoleCode.ASSESSOR}
ROLE_PRIORITY = (RoleCode.SYSTEM_ADMIN, RoleCode.DRILL_DIRECTOR, RoleCode.EXERCISE_DESIGNER, RoleCode.ASSESSOR)


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_.-]+$")
    password: str = Field(min_length=8, max_length=128)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    username: str
    role: str
    role_code: str


class SessionSummary(BaseModel):
    id: str
    current: bool
    status: str
    created_at: datetime
    last_used_at: datetime
    expires_at: datetime


@dataclass(frozen=True)
class AuthenticatedIdentity:
    username: str
    role: str
    role_codes: tuple[str, ...]
    user_id: str
    session_id: str | None = None


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _roles(session: Session, user: User) -> list[Role]:
    return list(session.scalars(select(Role).join(UserRole, UserRole.role_id == Role.id).where(UserRole.user_id == user.id)))


def _management_identity(user: User, roles: list[Role], session_id: str | None = None) -> AuthenticatedIdentity:
    by_code = {role.code: role for role in roles}
    allowed = [code for code in ROLE_PRIORITY if code in by_code and code in MANAGEMENT_ROLES]
    if not allowed:
        raise HTTPException(status_code=403, detail="该账号没有演练管理端权限，请使用手机参演入口。")
    primary = by_code[allowed[0]]
    return AuthenticatedIdentity(user.username, primary.name, tuple(code.value for code in allowed), user.id, session_id)


def _set_refresh_cookie(response: Response, token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        REFRESH_COOKIE, token,
        max_age=settings.refresh_token_expire_days * 86400,
        httponly=True, secure=settings.app_env != "development", samesite="lax",
        path=f"{settings.api_prefix}/auth",
    )


def _clear_refresh_cookie(response: Response) -> None:
    settings = get_settings()
    response.delete_cookie(REFRESH_COOKIE, path=f"{settings.api_prefix}/auth", samesite="lax")


def _issue_session(session: Session, user: User, roles: list[Role], response: Response) -> LoginResponse:
    settings = get_settings()
    identity = _management_identity(user, roles)
    auth_session = AuthSession(user_id=user.id, refresh_token_hash="pending", expires_at=datetime.now(UTC) + timedelta(days=settings.refresh_token_expire_days))
    session.add(auth_session)
    session.flush()
    refresh_token = create_refresh_token(auth_session.id)
    auth_session.refresh_token_hash = hash_refresh_token(refresh_token)
    session.commit()
    _set_refresh_cookie(response, refresh_token)
    return LoginResponse(
        access_token=create_access_token(user.username, auth_session.id, identity.role_codes),
        expires_in=settings.access_token_expire_minutes * 60,
        username=user.username, role=identity.role, role_code=identity.role_codes[0],
    )


def _record_failed_login(session: Session, username: str) -> None:
    now = datetime.now(UTC)
    record = session.get(LoginSecurity, username)
    if record is None:
        record = LoginSecurity(username=username, failed_attempts=0, updated_at=now)
        session.add(record)
    record.failed_attempts += 1
    record.updated_at = now
    if record.failed_attempts >= 5:
        record.locked_until = now + timedelta(minutes=5)
        record.failed_attempts = 0
    session.commit()


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest, response: Response, session: Session = Depends(get_db)) -> LoginResponse:
    """Authenticate the management endpoint; participant devices use drill invite codes."""
    settings = get_settings()
    username = payload.username.strip()
    security = session.get(LoginSecurity, username)
    if security and security.locked_until and _aware(security.locked_until) > datetime.now(UTC):
        raise HTTPException(status_code=429, detail="登录尝试过多，请五分钟后重试。")
    user = session.scalar(select(User).where(User.username == username))
    user_count = session.scalar(select(func.count()).select_from(User)) or 0
    bootstrap_allowed = username == settings.bootstrap_admin_username and (
        settings.app_env == "development" or user_count == 0 or (user is not None and not user.password_hash)
    )
    if user is None and bootstrap_allowed and payload.password == settings.bootstrap_admin_password:
        user = ensure_development_user(session, username)
        user.display_name = "系统管理员"
        user.password_hash = hash_password(payload.password)
        user.is_active = True
        session.commit()
    elif user is not None and not user.password_hash and bootstrap_allowed and payload.password == settings.bootstrap_admin_password:
        user = ensure_development_user(session, username)
        user.password_hash = hash_password(payload.password)
        user.is_active = True
        session.commit()
    if user is None or not user.is_active or not verify_password(payload.password, user.password_hash):
        _record_failed_login(session, username)
        raise HTTPException(status_code=401, detail="账号或密码错误。")
    if security:
        security.failed_attempts = 0
        security.locked_until = None
        security.updated_at = datetime.now(UTC)
    return _issue_session(session, user, _roles(session, user), response)


def authenticate_access_token(token: str, session: Session) -> AuthenticatedIdentity:
    settings = get_settings()
    try:
        claims = decode_access_claims(token)
    except Exception as exc:
        raise HTTPException(status_code=401, detail="访问凭证无效或已过期。") from exc
    username = str(claims["sub"])
    user = session.scalar(select(User).where(User.username == username))
    session_id = claims.get("sid")
    if user is None and settings.app_env == "development" and session_id is None:
        user = ensure_development_user(session, username)
        session.commit()
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="账号不存在或已停用。")
    if session_id:
        auth_session = session.get(AuthSession, session_id)
        if auth_session is None or auth_session.user_id != user.id or auth_session.revoked_at is not None or _aware(auth_session.expires_at) <= datetime.now(UTC):
            raise HTTPException(status_code=401, detail="登录会话已失效，请重新登录。")
    elif settings.app_env != "development":
        raise HTTPException(status_code=401, detail="旧版登录凭证已失效，请重新登录。")
    return _management_identity(user, _roles(session, user), str(session_id) if session_id else None)


def get_current_identity(authorization: str | None = Header(default=None), session: Session = Depends(get_db)) -> AuthenticatedIdentity:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="缺少访问凭证。")
    return authenticate_access_token(authorization.removeprefix("Bearer ").strip(), session)


@router.post("/refresh", response_model=LoginResponse)
def refresh_session(response: Response, refresh_token: str | None = Cookie(default=None, alias=REFRESH_COOKIE), session: Session = Depends(get_db)) -> LoginResponse:
    if not refresh_token or "." not in refresh_token:
        raise HTTPException(status_code=401, detail="刷新凭证缺失，请重新登录。")
    session_id = refresh_token.split(".", 1)[0]
    auth_session = session.get(AuthSession, session_id)
    if auth_session is None or auth_session.revoked_at is not None or _aware(auth_session.expires_at) <= datetime.now(UTC) or auth_session.refresh_token_hash != hash_refresh_token(refresh_token):
        _clear_refresh_cookie(response)
        raise HTTPException(status_code=401, detail="刷新凭证无效或已过期，请重新登录。")
    user = session.get(User, auth_session.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="账号不存在或已停用。")
    roles = _roles(session, user)
    identity = _management_identity(user, roles, auth_session.id)
    rotated = create_refresh_token(auth_session.id)
    auth_session.refresh_token_hash = hash_refresh_token(rotated)
    auth_session.last_used_at = datetime.now(UTC)
    session.commit()
    _set_refresh_cookie(response, rotated)
    settings = get_settings()
    return LoginResponse(
        access_token=create_access_token(user.username, auth_session.id, identity.role_codes),
        expires_in=settings.access_token_expire_minutes * 60,
        username=user.username, role=identity.role, role_code=identity.role_codes[0],
    )


@router.post("/logout", status_code=204)
def logout(response: Response, identity: AuthenticatedIdentity = Depends(get_current_identity), session: Session = Depends(get_db)) -> Response:
    if identity.session_id:
        auth_session = session.get(AuthSession, identity.session_id)
        if auth_session and auth_session.revoked_at is None:
            auth_session.revoked_at = datetime.now(UTC)
            session.commit()
    _clear_refresh_cookie(response)
    response.status_code = 204
    return response


@router.get("/sessions", response_model=list[SessionSummary])
def list_sessions(
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    session: Session = Depends(get_db),
) -> list[SessionSummary]:
    """Return the user's durable login sessions without exposing refresh credentials."""
    now = datetime.now(UTC)
    records = session.scalars(
        select(AuthSession)
        .where(AuthSession.user_id == identity.user_id)
        .order_by(AuthSession.last_used_at.desc(), AuthSession.created_at.desc())
        .limit(8)
    )
    return [
        SessionSummary(
            id=record.id,
            current=record.id == identity.session_id,
            status=(
                "revoked"
                if record.revoked_at is not None
                else "expired"
                if _aware(record.expires_at) <= now
                else "active"
            ),
            created_at=record.created_at,
            last_used_at=record.last_used_at,
            expires_at=record.expires_at,
        )
        for record in records
    ]


@router.delete("/sessions/{session_id}", status_code=204)
def revoke_session(
    session_id: str,
    response: Response,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    session: Session = Depends(get_db),
) -> Response:
    """Revoke another session owned by the current account."""
    if session_id == identity.session_id:
        raise HTTPException(status_code=409, detail="当前会话请使用“退出当前会话”结束。")
    auth_session = session.get(AuthSession, session_id)
    if auth_session is None or auth_session.user_id != identity.user_id:
        raise HTTPException(status_code=404, detail="登录会话不存在。")
    if auth_session.revoked_at is None:
        auth_session.revoked_at = datetime.now(UTC)
        session.commit()
    response.status_code = 204
    return response


@router.get("/me")
def current_user(identity: AuthenticatedIdentity = Depends(get_current_identity)) -> dict:
    return {
        "username": identity.username, "role": identity.role,
        "role_code": identity.role_codes[0], "roles": list(identity.role_codes),
        "authentication_mode": "account_session" if identity.session_id else "development_legacy",
    }
