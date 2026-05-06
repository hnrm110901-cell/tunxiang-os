"""conftest.py — tx-civic 测试套件公共 fixtures

提供：
- app fixture：带 lifespan 跳过的 FastAPI 测试实例
- client fixture：httpx.AsyncClient + ASGITransport
- mock_db fixture：AsyncMock 数据库会话（用于需要 DB 的路由测试）
- 标准 X-Tenant-ID header 常量
- _DBOverride 上下文管理器：app.dependency_overrides[get_db] 注入 mock_db

约定：
- TENANT_ID 固定为 "00000000-0000-0000-0000-000000000001"
- 所有 DB 路由通过 app.dependency_overrides[get_db] 注入 mock_db
"""
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
SVC_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
for p in [ROOT, SVC_DIR, SRC]:
    if p not in sys.path:
        sys.path.insert(0, p)

from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from shared.ontology.src.database import get_db

# ─── 常量 ────────────────────────────────────────────────────────────────────

TENANT_ID = "00000000-0000-0000-0000-000000000001"
TENANT_HEADERS = {"X-Tenant-ID": TENANT_ID}


# ─── Mock DB 工厂 ────────────────────────────────────────────────────────────


def make_mock_db() -> AsyncMock:
    """返回一个模拟 AsyncSession，所有异步方法预设为 AsyncMock。"""
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.close = AsyncMock()
    return db


def make_mock_result(
    rows: list[dict] | None = None,
    scalar_value: int | None = None,
    rowcount: int | None = None,
) -> MagicMock:
    """模拟 SQLAlchemy Result 对象。

    支持：
      result.scalar()           → 返回单个值
      result.fetchone()         → 返回 dict-like 行或 None
      result.rowcount           → 返回 int
      for r in result: r._mapping → 迭代
      result.mappings().first() → 返回单行
      result.mappings().all()   → 返回多行
    """
    result = MagicMock()
    _rows = rows or []

    # scalar
    result.scalar = MagicMock(return_value=scalar_value if scalar_value is not None else (len(_rows) if _rows else 0))

    # fetchone
    if _rows:
        mock_row = MagicMock()
        for k, v in _rows[0].items():
            setattr(mock_row, k, v)
        mock_row._mapping = _rows[0]
        result.fetchone = MagicMock(return_value=mock_row)
    else:
        result.fetchone = MagicMock(return_value=None)

    # iteration — for `[dict(r._mapping) for r in rows]`
    class _IterRow:
        def __init__(self, d: dict):
            self._d = d

        @property
        def _mapping(self) -> dict:
            return self._d

    iter_rows = [_IterRow(r) for r in _rows]
    result.__iter__ = MagicMock(return_value=iter(iter_rows))

    # rowcount
    if rowcount is not None:
        result.rowcount = rowcount
    else:
        result.rowcount = len(_rows)

    # mappings — for service functions using `.mappings().first()` / `.all()`
    mapping_mock = MagicMock()
    mapping_mock.first = MagicMock(return_value=_rows[0] if _rows else None)
    mapping_mock.all = MagicMock(return_value=[dict(r) for r in _rows])
    result.mappings = MagicMock(return_value=mapping_mock)

    return result


# ─── DB override 上下文 ──────────────────────────────────────────────────────


class _DBOverride:
    """上下文管理器：临时将 get_db 替换为返回指定 mock_db 的生成器。

    用法:
        with _DBOverride(app, mock_db):
            resp = await client.get(...)
    """

    def __init__(self, app: FastAPI, mock_db: AsyncMock):
        self._app = app
        self._mock_db = mock_db

    def __enter__(self):
        async def _override():
            yield self._mock_db

        self._app.dependency_overrides[get_db] = _override
        return self._mock_db

    def __exit__(self, *args):
        self._app.dependency_overrides.pop(get_db, None)


# ─── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_db() -> AsyncMock:
    """返回一个干净的 mock AsyncSession。"""
    return make_mock_db()


@pytest_asyncio.fixture
async def client(app) -> AsyncClient:
    """每个测试函数获得一个独立的 AsyncClient。"""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac
