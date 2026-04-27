"""config.py -- 屯象OS 边缘同步引擎统一配置

从环境变量或 .env 文件读取，集中管理所有同步参数。
"""

from __future__ import annotations

import os
from typing import List

# ─── 同步节奏 ──────────────────────────────────────────────────────────────

SYNC_INTERVAL_SECONDS: int = int(os.getenv("SYNC_INTERVAL_SECONDS", "300"))
"""同步间隔（秒），默认 5 分钟"""

# ─── 批量参数 ──────────────────────────────────────────────────────────────

BATCH_SIZE: int = int(os.getenv("SYNC_BATCH_SIZE", "500"))
"""每批次最大记录数"""

# ─── 冲突策略 ──────────────────────────────────────────────────────────────

CONFLICT_STRATEGY: str = os.getenv("SYNC_CONFLICT_STRATEGY", "cloud_wins")
"""冲突解决策略: cloud_wins / local_wins / manual"""

# ─── 同步表清单 ────────────────────────────────────────────────────────────

SYNC_TABLES: List[str] = [
    "orders",
    "order_items",
    "customers",
    "dishes",
    "dish_categories",
    "ingredients",
    "inventory",
    "employees",
    "shifts",
    "tables",
    "reservations",
    "payments",
    "coupons",
    "customer_coupons",
]

# ─── 数据库连接 ────────────────────────────────────────────────────────────

LOCAL_PG_DSN: str = os.getenv(
    "LOCAL_DATABASE_URL",
    "postgresql+asyncpg://tunxiang:local@localhost/tunxiang_local",
)
"""本地 PostgreSQL DSN（Mac mini）"""

CLOUD_PG_DSN: str = os.getenv("CLOUD_PG_DSN", "")
"""云端 PostgreSQL DSN（腾讯云）"""

CLOUD_API_URL: str = os.getenv("CLOUD_API_URL", "")
"""云端 API 基础 URL"""

# ─── 租户/门店 ─────────────────────────────────────────────────────────────

TENANT_ID: str = os.getenv("TENANT_ID", "")
STORE_ID: str = os.getenv("STORE_ID", "")

# ─── 超时与重试 ────────────────────────────────────────────────────────────

SYNC_TIMEOUT_SECONDS: int = int(os.getenv("SYNC_TIMEOUT_SECONDS", "60"))
"""单轮同步超时（秒）"""

HTTP_TIMEOUT: float = float(os.getenv("SYNC_HTTP_TIMEOUT", "30"))
"""HTTP 请求超时（秒）"""

MAX_RETRY_BACKOFF: int = int(os.getenv("MAX_RETRY_BACKOFF", "3600"))
"""指数退避最大等待时间（秒）"""

# ─── 日志 ──────────────────────────────────────────────────────────────────

LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
