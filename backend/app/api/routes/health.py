from fastapi import APIRouter

from app.core.config import get_settings
from app.core.database import database_health


router = APIRouter(tags=["system"])


@router.get("/health")
def health_check() -> dict:
    """提供前端启动提示和部署探活所需的基础状态。"""

    settings = get_settings()
    database = database_health()
    overall_status = "healthy" if database["status"] == "healthy" else "degraded"
    return {
        "status": overall_status,
        "service": settings.app_name,
        "environment": settings.app_env,
        "database": database,
    }
