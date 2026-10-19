from functools import lru_cache
from pathlib import Path
from typing import Literal
from pydantic import Field, SecretStr, model_validator

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
    refresh_token_expire_days: int = Field(default=7, ge=1, le=30)
    bootstrap_admin_username: str = "admin"
    bootstrap_admin_password: str = "Zhiyan@2026"
    # 本地开发既支持 localhost，也支持浏览器直接打开的 127.0.0.1。
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    assistant_provider: Literal["offline", "compatible", "ollama"] = "offline"
    assistant_base_url: str = ""
    assistant_model: str = ""
    assistant_api_key: SecretStr = SecretStr("")
    assistant_timeout_seconds: int = Field(default=40, ge=5, le=90)
    participant_invite_hours: int = Field(default=8, ge=1, le=72)

    @model_validator(mode="after")
    def validate_deployment(self):
        self.app_env = self.app_env.strip().lower()
        if self.app_env != "development":
            if len(self.jwt_secret.encode()) < 32 or len(set(self.jwt_secret)) < 12 or self.jwt_secret == "replace-this-before-any-non-development-run":
                raise ValueError("非开发环境必须配置至少 32 字节的独立 JWT_SECRET。")
            if self.bootstrap_admin_password == "Zhiyan@2026" or len(self.bootstrap_admin_password) < 14:
                raise ValueError("非开发环境必须设置至少 14 字符的独立管理员初始密码。")
            if not self.cors_origin_list or any(origin == "*" or not origin.startswith("https://") for origin in self.cors_origin_list):
                raise ValueError("非开发环境 CORS_ORIGINS 必须明确列出 HTTPS 前端地址。")
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
