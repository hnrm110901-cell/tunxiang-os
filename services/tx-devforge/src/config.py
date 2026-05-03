"""tx-devforge 配置 — 环境变量驱动 (Pydantic Settings)。"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """运行期可调参数。所有敏感项必须从环境变量注入，禁止硬编码。"""

    model_config = SettingsConfigDict(
        env_prefix="DEVFORGE_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # 服务标识
    service_name: str = "tx-devforge"
    service_version: str = "0.1.0"
    # 端口分配：8015=tx-expense / 8016=tx-pay / 8017=tx-devforge
    port: int = 8017

    # 数据库
    database_url: str = Field(
        default="",
        description="async SQLAlchemy URL（需 asyncpg driver）；必须通过环境变量 DATABASE_URL 注入",
    )
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_recycle_seconds: int = 300

    # 安全
    jwt_secret: str = Field(
        default="please-override-in-prod",
        description="JWT 签名密钥；生产环境必须由环境变量覆盖",
    )

    # CORS
    cors_allow_origins: str = "*"

    @field_validator("database_url")
    @classmethod
    def database_url_required(cls, v: str) -> str:
        if not v:
            raise ValueError("DATABASE_URL env var is required")
        return v

    # 日志
    log_level: str = "INFO"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """单例配置访问入口。"""

    return Settings()
