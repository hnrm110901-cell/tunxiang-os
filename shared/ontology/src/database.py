"""共享数据库连接层 — 所有域微服务复用

使用方式：
    from shared.ontology.src.database import get_db, init_db

    # FastAPI 依赖注入
    @router.get("/items")
    async def list_items(db: AsyncSession = Depends(get_db)):
        ...
"""
import os
import uuid
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

_SET_TENANT_SQL = text("SELECT set_config('app.tenant_id', :tid, true)")


def _validate_tenant_id(tenant_id: str) -> str:
    """校验 tenant_id 非空且为合法 UUID，防止 RLS 绕过。"""
    if not tenant_id or not tenant_id.strip():
        raise ValueError("tenant_id must not be empty — RLS requires a valid tenant context")
    try:
        uuid.UUID(tenant_id)
    except ValueError as e:
        raise ValueError(f"tenant_id must be a valid UUID, got: {tenant_id!r}") from e
    return tenant_id


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
    """带租户隔离的 DB session — set_config 与首次业务查询在同一连接上执行。

    安全保障：拒绝 None/空/非 UUID 的 tenant_id，防止 RLS NULL 绕过。
    """
    _validate_tenant_id(tenant_id)
    async with async_session_factory() as session:
        try:
            await session.execute(_SET_TENANT_SQL, {"tid": tenant_id})
            yield session
            await session.commit()
        except Exception:  # DB session 兜底回滚：必须捕获所有异常以保证回滚后再抛出
            await session.rollback()
            raise


async def get_db_no_rls() -> AsyncGenerator[AsyncSession, None]:
    """跳过 RLS 的 DB session，仅限系统级操作（微信回调跨租户查询等）。

    要求：DB 用户须持有 BYPASSRLS 权限（或 SUPERUSER）。
    生产部署：GRANT BYPASSRLS ON ROLE tunxiang TO tunxiang;
    """
    async with async_session_factory() as session:
        try:
            await session.execute(text("SET LOCAL row_security = off"))
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
