"""integration/conftest.py — 集成测试公共 fixtures

提供连接到真实 PostgreSQL 的测试基础设施。

用法：
  1. 启动测试数据库：docker compose -f infra/docker/docker-compose.integration-test.yml up -d
  2. 设置环境变量：export INTEGRATION_DATABASE_URL="postgresql+asyncpg://tunxiang:changeme_test@localhost:15432/tunxiang_os_test"
  3. 运行测试：pytest tests/integration/ -v

每个测试函数获得一个独立的数据库事务（测试结束时回滚）。
"""

from __future__ import annotations

import os
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

# 从环境变量或默认值读取数据库连接串
DATABASE_URL = os.environ.get(
    "INTEGRATION_DATABASE_URL",
    "postgresql+asyncpg://tunxiang:changeme_test@localhost:15432/tunxiang_os_test",
)

# 禁用 SQL 回显（测试中不需要）
_engine: AsyncEngine | None = None


def get_engine() -> AsyncEngine:
    """懒加载测试引擎（模块级单例）。"""
    global _engine
    if _engine is None:
        _engine = create_async_engine(DATABASE_URL, echo=False, pool_size=2, max_overflow=4)
    return _engine


@pytest_asyncio.fixture(scope="session")
async def engine() -> AsyncGenerator[AsyncEngine, None]:
    """会话级别的 AsyncEngine。"""
    eng = get_engine()
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture(autouse=True)
async def transaction(engine: AsyncEngine) -> AsyncGenerator[AsyncConnection, None]:
    """每个测试函数获得一个独立的事务，测试结束时 ROLLBACK。

    这是集成测试的核心 fixture —— 保证测试间互不干扰。
    """
    async with engine.connect() as conn:
        # 启动事务
        async with conn.begin() as tx:
            # 设置租户上下文（RLS 需要）
            await conn.exec_driver_sql("SET LOCAL app.tenant_id TO '00000000-0000-0000-0000-000000000001'")
            yield conn
            # 测试结束时 ROLLBACK（通过 async with conn.begin() 的自动回滚）


@pytest.fixture
def tenant_id() -> str:
    """默认测试租户 ID。"""
    return "00000000-0000-0000-0000-000000000001"


@pytest.fixture
def tenant_uuid(tenant_id: str):
    """UUID 格式的租户 ID。"""
    from uuid import UUID
    return UUID(tenant_id)
