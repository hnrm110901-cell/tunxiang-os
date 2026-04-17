"""D5 跨店权限边界 — 单元测试

覆盖权限矩阵：
  - admin / boss：全放行
  - store_manager：自店 read/write/finance(read) 允许，finance_write 拒绝；跨店默认拒绝
  - head_chef：自店 read 允许，write/finance 拒绝
  - regional_manager(CUSTOMER_MANAGER)：无 scope 拒绝，有 scope 按 level/finance_access
  - UserStoreScope 过期：拒绝
  - get_accessible_stores：正确返回
"""

import sys
import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

sys.modules.setdefault("src.core.config", MagicMock(settings=MagicMock()))

import pytest

from src.models.user import UserRole
from src.models.user_store_scope import UserStoreScope
from src.services.store_access_service import StoreAccessService


def _u(role, store_id="S001", uid=None):
    return SimpleNamespace(id=uid or uuid.uuid4(), role=role, store_id=store_id, brand_id="B1")


def _mock_session(scope=None):
    """返回一个 AsyncSession 桩：execute().scalar_one_or_none() → scope"""
    session = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = scope
    # 对于 get_accessible_stores 返回 scalars().all()
    scalars = MagicMock()
    scalars.all.return_value = [scope] if scope else []
    result.scalars.return_value = scalars
    session.execute = AsyncMock(return_value=result)
    return session


# ───────────────────── 全局角色 ─────────────────────


@pytest.mark.asyncio
async def test_admin_all_pass():
    session = _mock_session()
    user = _u(UserRole.ADMIN, store_id=None)
    for r in ("read", "write", "finance", "finance_write"):
        assert await StoreAccessService.check_store_access(session, user, "S999", r) is True


# ───────────────────── 店长 ─────────────────────


@pytest.mark.asyncio
async def test_store_manager_own_store():
    session = _mock_session(scope=None)
    user = _u(UserRole.STORE_MANAGER, store_id="S001")
    assert await StoreAccessService.check_store_access(session, user, "S001", "read") is True
    assert await StoreAccessService.check_store_access(session, user, "S001", "write") is True
    assert await StoreAccessService.check_store_access(session, user, "S001", "finance") is True
    # 关键：店长不能修改财务
    assert await StoreAccessService.check_store_access(session, user, "S001", "finance_write") is False


@pytest.mark.asyncio
async def test_store_manager_cross_store_denied():
    session = _mock_session(scope=None)
    user = _u(UserRole.STORE_MANAGER, store_id="S001")
    assert await StoreAccessService.check_store_access(session, user, "S002", "read") is False


@pytest.mark.asyncio
async def test_store_manager_cross_store_with_scope():
    scope = UserStoreScope(
        user_id=uuid.uuid4(), store_id="S002",
        access_level="write", finance_access=False,
    )
    session = _mock_session(scope=scope)
    user = _u(UserRole.STORE_MANAGER, store_id="S001")
    assert await StoreAccessService.check_store_access(session, user, "S002", "read") is True
    assert await StoreAccessService.check_store_access(session, user, "S002", "write") is True
    assert await StoreAccessService.check_store_access(session, user, "S002", "finance") is False


# ───────────────────── 厨师长 ─────────────────────


@pytest.mark.asyncio
async def test_head_chef_own_store_read_only():
    session = _mock_session()
    user = _u(UserRole.HEAD_CHEF, store_id="S001")
    assert await StoreAccessService.check_store_access(session, user, "S001", "read") is True
    assert await StoreAccessService.check_store_access(session, user, "S001", "write") is False
    assert await StoreAccessService.check_store_access(session, user, "S001", "finance") is False


@pytest.mark.asyncio
async def test_head_chef_cross_store_denied():
    session = _mock_session(scope=None)
    user = _u(UserRole.HEAD_CHEF, store_id="S001")
    assert await StoreAccessService.check_store_access(session, user, "S002", "read") is False


# ───────────────────── 区域经理（CUSTOMER_MANAGER） ─────────────────────


@pytest.mark.asyncio
async def test_regional_manager_needs_scope():
    session = _mock_session(scope=None)
    user = _u(UserRole.CUSTOMER_MANAGER, store_id=None)
    assert await StoreAccessService.check_store_access(session, user, "S003", "read") is False


@pytest.mark.asyncio
async def test_regional_manager_admin_scope_finance():
    scope = UserStoreScope(
        user_id=uuid.uuid4(), store_id="S003",
        access_level="admin", finance_access=True,
    )
    session = _mock_session(scope=scope)
    user = _u(UserRole.CUSTOMER_MANAGER, store_id=None)
    assert await StoreAccessService.check_store_access(session, user, "S003", "read") is True
    assert await StoreAccessService.check_store_access(session, user, "S003", "write") is True
    assert await StoreAccessService.check_store_access(session, user, "S003", "finance") is True
    assert await StoreAccessService.check_store_access(session, user, "S003", "finance_write") is True


# ───────────────────── 过期授权 ─────────────────────


@pytest.mark.asyncio
async def test_expired_scope_denied():
    scope = UserStoreScope(
        user_id=uuid.uuid4(), store_id="S004",
        access_level="write", finance_access=True,
        expires_at=datetime.utcnow() - timedelta(days=1),
    )
    session = _mock_session(scope=scope)
    user = _u(UserRole.CUSTOMER_MANAGER, store_id=None)
    assert await StoreAccessService.check_store_access(session, user, "S004", "read") is False


# ───────────────────── 可访问门店列表 ─────────────────────


@pytest.mark.asyncio
async def test_accessible_stores_admin():
    session = _mock_session()
    user = _u(UserRole.ADMIN, store_id=None)
    assert await StoreAccessService.get_accessible_stores(session, user) == ["*"]


@pytest.mark.asyncio
async def test_accessible_stores_manager_with_scope():
    scope = UserStoreScope(user_id=uuid.uuid4(), store_id="S010", access_level="read")
    session = _mock_session(scope=scope)
    user = _u(UserRole.STORE_MANAGER, store_id="S001")
    stores = await StoreAccessService.get_accessible_stores(session, user)
    assert "S001" in stores
    assert "S010" in stores
