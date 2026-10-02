import logging
from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings


settings = get_settings()
engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    """所有业务实体共享的 ORM 基类。"""


def get_db() -> Generator[Session, None, None]:
    """为一次 API 请求提供独立数据库会话。"""

    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def initialize_schema() -> bool:
    """开发环境初始化表结构；数据库不可用时保留服务降级能力。"""

    # 延迟导入可确保所有模型已注册到 Base.metadata。
    import app.models.domain  # noqa: F401
    import app.models.operations  # noqa: F401
    import app.models.tasks  # noqa: F401
    import app.models.account  # noqa: F401

    try:
        Base.metadata.create_all(bind=engine)
        return True
    except SQLAlchemyError:
        logger.warning("数据库暂不可用，跳过开发环境表结构初始化。")
        return False


def database_health() -> dict[str, str]:
    """检查数据库连通性；服务本身不因数据库暂不可用而无法启动。"""

    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return {"status": "healthy"}
    except SQLAlchemyError:
        return {"status": "degraded"}
