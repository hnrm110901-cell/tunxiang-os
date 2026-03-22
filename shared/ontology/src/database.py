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

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://tunxiang:changeme_dev@localhost/tunxiang_os",
)

engine = create_async_engine(DATABASE_URL, echo=False, pool_size=10, max_overflow=20)
async_session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI 依赖注入：获取 DB session，自动提交/回滚"""
    async with async_session_factory() as session:
        try:
            # 设置 RLS tenant_id（从 request.state 注入，此处用默认值）
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_db_with_tenant(tenant_id: str) -> AsyncGenerator[AsyncSession, None]:
    """带租户隔离的 DB session"""
    async with async_session_factory() as session:
        try:
            await session.execute(
                __import__("sqlalchemy").text(f"SELECT set_config('app.tenant_id', :tid, true)"),
                {"tid": tenant_id},
            )
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db():
    """初始化数据库（创建表，开发环境用）"""
    from .base import TenantBase
    async with engine.begin() as conn:
        await conn.run_sync(TenantBase.metadata.create_all)
