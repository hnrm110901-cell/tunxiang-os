"""共享数据库连接层 — 所有域微服务复用"""
import os
import uuid
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import structlog
from typing import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

logger = structlog.get_logger()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://tunxiang:changeme_dev@localhost/tunxiang_os")
engine = create_async_engine(DATABASE_URL, echo=False, pool_size=10, max_overflow=20)
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


class TenantIDMissing(Exception):
    pass

class TenantIDInvalid(Exception):
    pass


def _validate_tenant_id(tenant_id: str) -> str:
    if not tenant_id or not tenant_id.strip():
        raise TenantIDMissing("tenant_id is required but was empty or None")
    tid = tenant_id.strip()
    try:
        uuid.UUID(tid)
    except ValueError as exc:
        raise TenantIDInvalid(f"tenant_id is not a valid UUID: {tid!r}") from exc
    return tid


async def _set_tenant_on_session(session: AsyncSession, tenant_id: str) -> None:
    await session.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": tenant_id})


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:  # DB session 兜底回滚：必须捕获所有异常以保证回滚后再抛出
            await session.rollback()
            raise


async def get_db_with_tenant(tenant_id: str) -> AsyncGenerator[AsyncSession, None]:
    validated_tid = _validate_tenant_id(tenant_id)
    async with async_session_factory() as session:
        try:
            await _set_tenant_on_session(session, validated_tid)
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
        finally:
            try:
                await session.execute(text("SELECT set_config('app.tenant_id', '', true)"))
            except Exception:  # noqa: BLE001
                logger.warning("failed_to_clear_tenant_id", tenant_id=validated_tid)


class TenantSession:
    def __init__(self, tenant_id: str) -> None:
        self._tenant_id = _validate_tenant_id(tenant_id)
        self._session: AsyncSession | None = None

    async def __aenter__(self) -> AsyncSession:
        self._session = async_session_factory()
        await _set_tenant_on_session(self._session, self._tenant_id)
        return self._session

    async def __aexit__(self, exc_type: type | None, exc_val: BaseException | None, exc_tb: object) -> None:
        session = self._session
        if session is None:
            return
        try:
            if exc_type is not None:
                await session.rollback()
            else:
                await session.commit()
        finally:
            try:
                await session.execute(text("SELECT set_config('app.tenant_id', '', true)"))
            except Exception:  # noqa: BLE001
                logger.warning("failed_to_clear_tenant_id", tenant_id=self._tenant_id)
            await session.close()
            self._session = None


async def init_db() -> None:
    from .base import TenantBase
    async with engine.begin() as conn:
        await conn.run_sync(TenantBase.metadata.create_all)
