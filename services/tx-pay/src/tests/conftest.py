"""conftest.py — tx-pay 测试套件公共 fixtures

提供：
- app / callback_app / agent_app fixture：带指定路由的 FastAPI 测试实例
- async_client fixture：httpx.AsyncClient + ASGITransport
- 标准 X-Tenant-ID header 常量
- mock_payment_service：通用的 PaymentNexusService mock 工厂
- mock_get_payment_service：async 函数，返回 mock_payment_service
- mock_db：AsyncSession mock（saga/idempotency 单元测试用）
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

# ─── 常量 ────────────────────────────────────────────────────────────────────

TENANT_ID = "00000000-0000-0000-0000-000000000001"
TENANT_HEADERS = {"X-Tenant-ID": TENANT_ID}


# ─── App 工厂 ─────────────────────────────────────────────────────────────────


def build_payment_app() -> FastAPI:
    """仅含支付核心路由的测试 app"""
    from src.api.payment_routes import router as payment_router

    app = FastAPI(title="tx-pay-test")
    app.include_router(payment_router)
    return app


def build_callback_app() -> FastAPI:
    """仅含支付回调路由的测试 app"""
    from src.api.callback_routes import router as callback_router

    app = FastAPI(title="tx-pay-callback-test")
    app.include_router(callback_router)
    return app


def build_agent_app() -> FastAPI:
    """仅含 Agent 支付路由的测试 app"""
    from src.api.agent_routes import router as agent_router

    app = FastAPI(title="tx-pay-agent-test")
    app.include_router(agent_router)
    return app


# ─── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def app():
    return build_payment_app()


@pytest.fixture(scope="session")
def callback_app():
    return build_callback_app()


@pytest.fixture(scope="session")
def agent_app():
    return build_agent_app()


@pytest_asyncio.fixture
async def client(app):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


@pytest_asyncio.fixture
async def callback_client(callback_app):
    async with AsyncClient(
        transport=ASGITransport(app=callback_app), base_url="http://test"
    ) as ac:
        yield ac


@pytest_asyncio.fixture
async def agent_client(agent_app):
    async with AsyncClient(
        transport=ASGITransport(app=agent_app), base_url="http://test"
    ) as ac:
        yield ac


@pytest.fixture
def mock_payment_service():
    """返回一个完整的 PaymentNexusService mock，所有方法预设为 AsyncMock。"""
    svc = AsyncMock()
    svc.create_payment = AsyncMock()
    svc.query_payment = AsyncMock()
    svc.refund = AsyncMock()
    svc.close_payment = AsyncMock(return_value=True)
    svc.split_payment = AsyncMock()
    svc.daily_summary = AsyncMock()
    return svc


@pytest.fixture
def mock_get_payment_service(mock_payment_service):
    """返回 async 函数，await 后返回 mock_payment_service。

    在测试中使用:
        with patch("src.deps.get_payment_service", mock_get_payment_service):
            resp = await client.post(...)
    """

    async def _get():
        return mock_payment_service

    return _get


@pytest.fixture
def mock_db():
    """返回模拟 AsyncSession，execute 为 async 函数返回 MagicMock 结果。

    测试可以设置 mock_db._fetchone_result / mock_db._fetchall_result
    来控制 execute 的返回值。
    """
    db = AsyncMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db._fetchone_result = None
    db._fetchall_result = []

    async def execute_side_effect(query, params=None):
        result = MagicMock()
        result.fetchone = MagicMock(return_value=db._fetchone_result)
        result.fetchall = MagicMock(return_value=db._fetchall_result)
        return result

    db.execute = AsyncMock(side_effect=execute_side_effect)
    return db
