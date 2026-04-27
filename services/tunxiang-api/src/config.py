"""统一配置 — 所有模块共享一份配置

MVP阶段只有一个进程，所有配置集中管理。
未来拆微服务时，每个服务带走自己的 section。
"""

import os


class Settings:
    """MVP单体配置"""

    # App
    APP_NAME: str = "TunxiangOS"
    APP_VERSION: str = "7.1.0"
    DEBUG: bool = os.getenv("TX_DEBUG", "false").lower() == "true"

    # Database
    DATABASE_URL: str = os.getenv(
        "TX_DATABASE_URL",
        "postgresql+asyncpg://postgres:postgres@localhost:5432/tunxiang",
    )

    # Redis
    REDIS_URL: str = os.getenv("TX_REDIS_URL", "redis://localhost:6379/0")

    # Auth
    JWT_SECRET: str = os.getenv("TX_JWT_SECRET", "dev-secret-change-in-production")
    TOKEN_EXPIRE_HOURS: int = 24

    # CORS
    CORS_ORIGINS: list[str] = ["*"]

    # AI
    CLAUDE_API_KEY: str = os.getenv("TX_CLAUDE_API_KEY", "")
    COREML_BRIDGE_URL: str = os.getenv("TX_COREML_URL", "http://localhost:8100")

    # POS集成 — 品智
    PINZHI_BASE_URL: str = os.getenv("PINZHI_BASE_URL", "")
    PINZHI_TOKEN: str = os.getenv("PINZHI_TOKEN", "")
    PINZHI_TIMEOUT: int = int(os.getenv("PINZHI_TIMEOUT", "30"))
    PINZHI_RETRY_TIMES: int = int(os.getenv("PINZHI_RETRY_TIMES", "3"))


settings = Settings()
