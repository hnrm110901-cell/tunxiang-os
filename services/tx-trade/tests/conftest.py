"""conftest.py — tx-trade 测试套件公共 fixtures

提供：
- app fixture：带 lifespan 跳过的 FastAPI 测试实例
- async_client fixture：httpx.AsyncClient + ASGITransport
- mock_db fixture：AsyncMock 数据库会话（用于需要 DB 的路由测试）
- 标准 X-Tenant-ID header 常量

约定：
- TENANT_ID 固定为 "00000000-0000-0000-0000-000000000001"，方便追查日志
- 所有 DB 路由通过 app.dependency_overrides[get_db] 注入 mock_db
"""
import os
import sys

# 确保项目根（shared/ 所在位置）和 src 在 Python path 中
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
for p in [ROOT, SRC]:
    if p not in sys.path:
        sys.path.insert(0, p)

from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

# ─── 常量 ────────────────────────────────────────────────────────────────────

TENANT_ID = "00000000-0000-0000-0000-000000000001"
TENANT_HEADERS = {"X-Tenant-ID": TENANT_ID}


# ─── 构建测试专用 app（跳过 lifespan 中的 DB/scheduler 初始化） ──────────────


def build_test_app() -> FastAPI:
    """
    构建一个仅注册目标路由的轻量 FastAPI 实例，
    不执行 lifespan 中的 init_db / scheduler，避免测试依赖真实数据库连接。
    """
    from fastapi.middleware.cors import CORSMiddleware
    from src.api.discount_engine_routes import router as discount_engine_router
    from src.api.scan_pay_routes import router as scan_pay_router
    from src.api.stored_value_routes import router as stored_value_router

    test_app = FastAPI(title="tx-trade-test")
    test_app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    test_app.include_router(scan_pay_router)
    test_app.include_router(stored_value_router)
    test_app.include_router(discount_engine_router)
    return test_app


# ─── 生成 mock DB session ─────────────────────────────────────────────────────


def make_mock_db() -> AsyncMock:
    """返回一个模拟 AsyncSession，所有异步方法预设为 AsyncMock。"""
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.close = AsyncMock()
    return db


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
def mock_db():
    """返回一个干净的 mock AsyncSession。"""
    return make_mock_db()
