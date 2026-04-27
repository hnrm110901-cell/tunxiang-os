"""本地 PostgreSQL 连接 — mac-station 离线 API 专用

Mac mini 本地跑一份 PostgreSQL 副本，由 sync-engine 定期从云端增量同步。
此模块提供异步 session factory，供离线路由使用。

环境变量：
  LOCAL_DB_URL  本地 PG 连接串（默认 postgresql+asyncpg://tunxiang:tunxiang@localhost:5432/tunxiang_local）

注意：此连接不设 app.tenant_id，离线路由直接用 WHERE store_id 过滤（门店机知道自己的 store_id）。
"""

import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

_LOCAL_DB_URL = os.getenv(
    "LOCAL_DB_URL",
    "postgresql+asyncpg://tunxiang:tunxiang@localhost:5432/tunxiang_local",
)

_engine = create_async_engine(
    _LOCAL_DB_URL,
    pool_size=3,
    max_overflow=5,
    pool_pre_ping=True,
    echo=False,
)

_SessionFactory = async_sessionmaker(
    _engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autobegin=True,
)


@asynccontextmanager
async def get_local_db() -> AsyncGenerator[AsyncSession, None]:
    """异步上下文管理器，供离线路由直接调用"""
    async with _SessionFactory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def local_db_dependency() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI Depends 兼容版本"""
    async with get_local_db() as session:
        yield session
