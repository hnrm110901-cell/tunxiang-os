"""tx-devforge 数据库层 — async engine + session 工厂 + 租户 RLS 注入。"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from typing import AsyncGenerator, AsyncIterator

import structlog
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from .config import get_settings

logger = structlog.get_logger(__name__)


class TenantIDMissing(Exception):
    """X-Tenant-ID header 缺失或为空。"""


class TenantIDInvalid(Exception):
    """X-Tenant-ID 不是合法 UUID。"""


_settings = get_settings()

engine: AsyncEngine = create_async_engine(
    _settings.database_url,
    echo=False,
    pool_size=_settings.db_pool_size,
    max_overflow=_settings.db_max_overflow,
    pool_pre_ping=True,
    pool_recycle=_settings.db_pool_recycle_seconds,
)

async_session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


def validate_tenant_id(tenant_id: str | None) -> str:
    """校验 tenant_id 非空且为合法 UUID，防止 RLS NULL 绕过。"""

    if tenant_id is None or not tenant_id.strip():
        raise TenantIDMissing("X-Tenant-ID header is required")
    candidate = tenant_id.strip()
    try:
        uuid.UUID(candidate)
    except ValueError as exc:
        raise TenantIDInvalid(
            f"X-Tenant-ID is not a valid UUID: {candidate!r}"
        ) from exc
    return candidate


async def _set_tenant_on_session(session: AsyncSession, tenant_id: str) -> None:
    await session.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


async def get_db_with_tenant(tenant_id: str) -> AsyncGenerator[AsyncSession, None]:
    """带 RLS 的 session 依赖。在同一连接上注入 app.tenant_id 后才进入业务。"""

    validated = validate_tenant_id(tenant_id)
    async with async_session_factory() as session:
        try:
            await _set_tenant_on_session(session, validated)
            yield session
            await session.commit()
        except Exception:  # noqa: BLE001 — 兜底回滚后必须重新抛出
            await session.rollback()
            raise


@asynccontextmanager
async def session_scope(tenant_id: str) -> AsyncIterator[AsyncSession]:
    """非依赖注入场景下的 session 上下文（worker / 启动检查等）。"""

    validated = validate_tenant_id(tenant_id)
    session = async_session_factory()
    try:
        await _set_tenant_on_session(session, validated)
        yield session
        await session.commit()
    except Exception:  # noqa: BLE001 — 兜底回滚后必须重新抛出
        await session.rollback()
        raise
    finally:
        await session.close()


async def check_db_connectivity() -> bool:
    """readiness 探针：连一次 DB 跑 SELECT 1。

    捕获三类异常：
    - OSError / RuntimeError：网络层 / asyncio 层失败
    - SQLAlchemyError 子类（OperationalError/InterfaceError/DBAPIError）：
      DB 不可达 / 鉴权失败 / pool 取连接超时等
    任一返回 False，让 /readiness 返回 503 而非 500。
    """

    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except (OSError, RuntimeError, SQLAlchemyError) as exc:
        logger.warning("devforge_db_unreachable", error=str(exc))
        return False
