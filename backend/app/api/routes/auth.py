from dataclasses import dataclass

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.core.security import create_access_token, decode_access_token


router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str
    role: str = "系统管理员"


@dataclass(frozen=True)
class AuthenticatedIdentity:
    username: str
    role: str = "系统管理员"


def _require_development_mode() -> None:
    if get_settings().app_env != "development":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="开发环境引导账号已关闭，请接入正式账户服务。",
        )


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest) -> LoginResponse:
    """仅供工程骨架使用的开发环境登录入口，正式账户体系将在后续增量替换。"""

    _require_development_mode()
    settings = get_settings()
    if (
        payload.username != settings.bootstrap_admin_username
        or payload.password != settings.bootstrap_admin_password
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="账号或密码错误，请检查开发环境配置。",
        )

    return LoginResponse(
        access_token=create_access_token(payload.username),
        username=payload.username,
    )


def get_current_identity(authorization: str | None = Header(default=None)) -> AuthenticatedIdentity:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="缺少访问凭证。")

    token = authorization.removeprefix("Bearer ").strip()
    try:
        username = decode_access_token(token)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="访问凭证无效。") from exc

    return AuthenticatedIdentity(username=username)


@router.get("/me")
def current_user(identity: AuthenticatedIdentity = Depends(get_current_identity)) -> dict[str, str]:
    return {"username": identity.username, "role": identity.role}
