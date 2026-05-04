"""conftest.py — tx-forge 测试套件公共 fixtures

提供：
- app fixture：可独立注入的 FastAPI 测试实例
- client fixture：httpx.AsyncClient + ASGITransport
- mock_db fixture：AsyncMock 数据库会话
- 标准 X-Tenant-ID header 常量

约定：
- TENANT_ID 固定为 "00000000-0000-0000-0000-000000000001"，方便追查日志
- 所有 DB 路由通过 app.dependency_overrides[get_db] 注入 mock_db
"""
import os
import sys
import types

_TESTS_DIR = os.path.dirname(__file__)
_SRC_DIR = os.path.join(_TESTS_DIR, "..")
_ROOT_DIR = os.path.abspath(os.path.join(_TESTS_DIR, "..", "..", ".."))

for _p in [_ROOT_DIR]:
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _ensure_pkg(name, path):
    if name not in sys.modules:
        mod = types.ModuleType(name)
        mod.__path__ = [path]
        mod.__package__ = name
        sys.modules[name] = mod


_ensure_pkg("src", _SRC_DIR)
_ensure_pkg("src.api", os.path.join(_SRC_DIR, "api"))
_ensure_pkg("src.services", os.path.join(_SRC_DIR, "services"))
_ensure_pkg("src.schemas", os.path.join(_SRC_DIR, "schemas"))
_ensure_pkg("src.models", os.path.join(_SRC_DIR, "models"))

from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.api.app_routes import router as app_router
from src.api.developer_routes import router as developer_router
from src.api.trust_routes import router as trust_router

# ─── 常量 ────────────────────────────────────────────────────────────────────

TENANT_ID = "00000000-0000-0000-0000-000000000001"
TENANT_HEADERS = {"X-Tenant-ID": TENANT_ID}


# ─── 工具函数 ─────────────────────────────────────────────────────────────────


def make_mock_result(one=None, first=None, all_=None, scalar=None):
    """创建模拟 SQLAlchemy execute() 返回值。"""
    result = MagicMock()
    mappings = MagicMock()
    mappings.one.return_value = one
    mappings.first.return_value = first
    mappings.all.return_value = all_ if all_ is not None else []
    mappings.one_or_none.return_value = one
    result.mappings.return_value = mappings
    result.scalar_one_or_none.return_value = scalar
    return result


def make_mock_db():
    """返回一个模拟 AsyncSession。"""
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.close = AsyncMock()
    return db


# ─── 构建测试专用 app ──────────────────────────────────────────────────────────


def build_test_app():
    """构建仅注册目标路由的轻量 FastAPI 实例。"""
    test_app = FastAPI(title="tx-forge-test")
    test_app.include_router(app_router)
    test_app.include_router(developer_router)
    test_app.include_router(trust_router)
    return test_app


# ─── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(scope="function")
def app():
    """每个测试函数获得一个独立的 FastAPI 实例。"""
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


@pytest.fixture
def tenant_headers():
    """标准 X-Tenant-ID header。"""
    return TENANT_HEADERS
