"""conftest.py — tx-devforge 测试套件公共 fixtures

提供：
- app fixture：跳过 lifespan 的 FastAPI 测试实例（含 TenantMiddleware）
- client fixture：httpx.AsyncClient + ASGITransport
- mock_db_session fixture：mock AsyncSession 用于需要 DB 的路由
- auto_override fixture：自动覆盖 _tenant_session 依赖 + patch emit_event
- make_app 工厂函数：创建内存 Application 实例
- 标准 X-Tenant-ID header 常量

约定：
- TENANT_ID 固定为 "00000000-0000-0000-0000-000000000001"
- 所有有 X-Tenant-ID 需求的路径通过 TENANT_HEADERS 传入
"""

from __future__ import annotations

import os
import sys

# 确保项目根（shared/）和 src 在 Python path 中
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
for p in [ROOT, SRC]:
    if p not in sys.path:
        sys.path.insert(0, p)

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.middlewares import TenantMiddleware
from src.models.application import Application

# ─── 常量 ────────────────────────────────────────────────────────────────────

TENANT_ID = "00000000-0000-0000-0000-000000000001"
TENANT_HEADERS = {"X-Tenant-ID": TENANT_ID}


# ─── 工厂函数 ─────────────────────────────────────────────────────────────────


def make_app(**overrides: object) -> Application:
    """创建一个内存中的 Application 实例，所有字段已填充，可直接用于 mock。"""
    now = datetime.now(timezone.utc)
    data: dict[str, object] = {
        "id": uuid4(),
        "tenant_id": UUID(TENANT_ID),
        "code": "test-app",
        "name": "Test App",
        "resource_type": "backend_service",
        "owner": "dev-team",
        "repo_path": "org/test-app",
        "tech_stack": "python",
        "description": "A test application",
        "metadata_json": {},
        "created_at": now,
        "updated_at": now,
        "is_deleted": False,
    }
    data.update(overrides)
    return Application(**data)  # type: ignore[arg-type]


# ─── 构建测试专用 app（跳过 lifespan 中的 DB 初始化） ──────────────────────────


def build_test_app() -> FastAPI:
    """构建仅注册目标路由的轻量 FastAPI 实例，不执行 lifespan。"""
    from src.api import application_router, health_router

    test_app = FastAPI(title="tx-devforge-test")
    test_app.add_middleware(TenantMiddleware)
    test_app.include_router(health_router)
    test_app.include_router(application_router)
    return test_app


# ─── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def app():
    """会话级别的测试 FastAPI 实例（仅构建一次）。"""
    return build_test_app()


@pytest_asyncio.fixture
async def client(app):
    """每个测试函数获得一个独立的 AsyncClient。"""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


@pytest.fixture
def mock_db_session():
    """返回一个干净的 mock AsyncSession。

    execute() 的默认返回值适配 SQLAlchemy ORM 调用链：
    - (await session.execute(stmt)).scalar_one_or_none()  -> None
    - (await session.execute(stmt)).scalars().all()        -> []
    - (await session.execute(stmt)).scalar_one()           -> 0
    各测试可按需覆盖 session.execute.return_value。
    """
    session = AsyncMock()
    session.execute = AsyncMock()
    session.execute.return_value = MagicMock(
        scalar_one_or_none=MagicMock(return_value=None),
        scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[]))),
        scalar_one=MagicMock(return_value=0),
    )
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.close = AsyncMock()
    session.add = MagicMock()
    return session


@pytest_asyncio.fixture(autouse=True)
async def auto_override(app, mock_db_session):
    """自动覆盖 _tenant_session 依赖 + 静默 emit_event。

    确保：
    1. 所有使用 Depends(_tenant_session) 的路由拿到 mock_db_session
    2. emit_event 是 no-op，避免 fire-and-forget 任务尝试连接真实 PG/Redis
      导致超时或 warning
    """
    from src.api import app_routes as app_routes_mod
    from src.api.app_routes import _tenant_session

    async def _mock_tenant_session(x_tenant_id: str):  # type: ignore[misc]
        yield mock_db_session

    app.dependency_overrides[_tenant_session] = _mock_tenant_session

    patcher = patch.object(app_routes_mod, "emit_event", new=AsyncMock())
    patcher.start()

    yield

    patcher.stop()
    app.dependency_overrides.clear()
