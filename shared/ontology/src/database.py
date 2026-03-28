"""共享数据库连接层 — 所有域微服务复用

使用方式：
    from shared.ontology.src.database import get_db, init_db

    # FastAPI 依赖注入
    @router.get("/items")
    async def list_items(db: AsyncSession = Depends(get_db)):
        ...
"""
import os
from typing import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://tunxiang:changeme_dev@localhost/tunxiang_os",
)

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    pool_size=20,
    max_overflow=30,
    pool_pre_ping=True,
    pool_recycle=300,
)
async_session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

# 预编译 RLS 设置语句（避免每次重新解析）
_SET_TENANT_SQL = text("SELECT set_config('app.tenant_id', :tid, true)")


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI 依赖注入：获取 DB session，自动提交/回滚"""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:  # DB session 兜底回滚：必须捕获所有异常以保证回滚后再抛出
            await session.rollback()
            raise


async def get_db_with_tenant(tenant_id: str) -> AsyncGenerator[AsyncSession, None]:
    """带租户隔离的 DB session — set_config 与首次业务查询在同一连接上执行"""
    async with async_session_factory() as session:
        try:
            await session.execute(_SET_TENANT_SQL, {"tid": tenant_id})
            yield session
            await session.commit()
        except Exception:  # DB session 兜底回滚：必须捕获所有异常以保证回滚后再抛出
            await session.rollback()
            raise


async def init_db():
    """初始化数据库（创建表，开发环境用）"""
    from .base import TenantBase
    async with engine.begin() as conn:
        await conn.run_sync(TenantBase.metadata.create_all)
