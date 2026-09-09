from functools import lru_cache
from pathlib import Path
from typing import Literal
from pydantic import Field, SecretStr

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """集中管理运行配置，开发环境可使用 .env，部署环境使用系统变量。"""

    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[3] / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "智演安巷 API"
    app_env: str = "development"
    api_prefix: str = "/api/v1"
    database_url: str = "postgresql+psycopg://zhiyan:zhiyan_local_only@localhost:5432/zhiyan_anxiang"
    jwt_secret: str = "replace-this-before-any-non-development-run"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    bootstrap_admin_username: str = "admin"
    bootstrap_admin_password: str = "Zhiyan@2026"
    # 本地开发既支持 localhost，也支持浏览器直接打开的 127.0.0.1。
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    assistant_provider: Literal["offline", "compatible", "ollama"] = "offline"
    assistant_base_url: str = ""
    assistant_model: str = ""
    assistant_api_key: SecretStr = SecretStr("")
    assistant_timeout_seconds: int = Field(default=40, ge=5, le=90)

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
