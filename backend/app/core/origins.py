"""Shared browser-origin policy for CORS and cookie-changing authentication."""
import re
from fastapi import Header, HTTPException
from app.core.config import get_settings

DEVELOPMENT_ORIGIN_PATTERN = r"^https?://(localhost|127\.0\.0\.1|10(?:\.\d{1,3}){3}|192\.168(?:\.\d{1,3}){2}|172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2}):5173$"


def verify_browser_origin(origin: str | None = Header(default=None)) -> None:
    # CLI/API clients do not send Origin; browsers cannot forge it. Reject
    # unsolicited browser requests before rotating or setting a refresh cookie.
    if origin is None:
        return
    settings = get_settings()
    allowed = origin in settings.cors_origin_list or (
        settings.app_env == 'development' and re.fullmatch(DEVELOPMENT_ORIGIN_PATTERN, origin))
    if not allowed:
        raise HTTPException(403, '请求来源未授权，请从配置的工作台地址登录。')
