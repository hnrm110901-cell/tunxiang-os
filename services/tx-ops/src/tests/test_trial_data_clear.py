"""试营业数据清除 — 单元测试

覆盖 4 个核心安全约束：
  1. test_confirm_name_mismatch_rejected  — 门店名不匹配时拒绝执行
  2. test_cooldown_prevents_double_clear  — 30天内第二次清除被拦截
  3. test_clear_scope_preserves_master_data — 清除后档案数据（菜品/员工）不受影响
  4. test_super_admin_required            — 非超级管理员调用返回403

技术约束：
  - sys.modules 存根注入，隔离 shared.ontology / structlog
  - TestClient + app.dependency_overrides[get_db_with_tenant] + AsyncMock
  - 全部 mock，不需要真实 DB
"""
from __future__ import annotations

import sys
import types
import uuid
from datetime import datetime, timedelta, timezone
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  sys.modules 存根注入（必须在导入路由前完成）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _ensure_stub(module_path: str, attrs: dict | None = None) -> types.ModuleType:
    """确保 module_path 在 sys.modules 中存在，返回模块对象。"""
    if module_path not in sys.modules:
        mod = types.ModuleType(module_path)
        if attrs:
            for k, v in attrs.items():
                setattr(mod, k, v)
        sys.modules[module_path] = mod
    return sys.modules[module_path]


# shared.ontology 层
_ensure_stub("shared")
_ensure_stub("shared.ontology")
_ensure_stub("shared.ontology.src")
_db_mod = _ensure_stub("shared.ontology.src.database")

if not hasattr(_db_mod, "get_db_with_tenant"):
    async def _placeholder_get_db_with_tenant():  # pragma: no cover
        yield None
    _db_mod.get_db_with_tenant = _placeholder_get_db_with_tenant

# shared.events 存根
_ensure_stub("shared.events")
_ensure_stub("shared.events.src")
_emitter_mod = _ensure_stub("shared.events.src.emitter")
_emitter_mod.emit_event = AsyncMock()  # type: ignore[attr-defined]

# structlog 存根
if "structlog" not in sys.modules:
    _sl = types.ModuleType("structlog")
    _sl.get_logger = MagicMock(return_value=MagicMock())  # type: ignore[attr-defined]
    sys.modules["structlog"] = _sl

# ── 导入路由 ────────────────────────────────────────────────────────────────────
from ..api.trial_data_routes import router as trial_data_router  # noqa: E402
from shared.ontology.src.database import get_db_with_tenant  # noqa: E402

# ── FastAPI 应用 ─────────────────────────────────────────────────────────────────
app = FastAPI()
app.include_router(trial_data_router)

# ── 常量 ──────────────────────────────────────────────────────────────────────────
TENANT_ID = str(uuid.uuid4())
STORE_ID = str(uuid.uuid4())
STORE_NAME = "尝在一起·河西万达店"
SUPER_ADMIN_ID = str(uuid.uuid4())
REGULAR_STAFF_ID = str(uuid.uuid4())
REQUEST_ID = str(uuid.uuid4())

ADMIN_HEADERS = {
    "X-Tenant-ID": TENANT_ID,
    "X-Operator-ID": SUPER_ADMIN_ID,
}
STAFF_HEADERS = {
    "X-Tenant-ID": TENANT_ID,
    "X-Operator-ID": REGULAR_STAFF_ID,
}


# ── 辅助 ─────────────────────────────────────────────────────────────────────────

def _override(db_mock: AsyncMock):
    """构造 FastAPI 依赖覆盖函数。"""
    async def _dep() -> AsyncGenerator:
        yield db_mock
    return _dep


def _make_db() -> AsyncMock:
    """构建通用 AsyncSession Mock。"""
    db = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock(fetchone=MagicMock(return_value=None)))
    return db


def _row(value):
    """构建返回单行的 execute Mock 结果。"""
    result = MagicMock()
    result.fetchone = MagicMock(return_value=value)
    return result


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  测试 1：门店名不匹配时拒绝执行
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestConfirmNameMismatchRejected:
    """confirm_store_name 与实际门店名不一致，execute 端点必须返回 422。"""

    def test_confirm_name_mismatch_rejected(self):
        db = _make_db()

        call_count = 0

        async def _multi_execute(sql, params=None):
            nonlocal call_count
            call_count += 1
            sql_str = str(sql)
            if "employees" in sql_str:
                # 权限检查：返回 super_admin
                return _row(("super_admin",))
            if "stores" in sql_str:
                # 返回真实门店名
                return _row((STORE_NAME,))
            if "trial_data_clear_requests" in sql_str and "WHERE id" in sql_str:
                # 审批状态查询：已审批
                return _row(("approved", STORE_ID))
            if "trial_data_clear_logs" in sql_str:
                # 冷却期检查：无记录（未满）
                return _row(None)
            return _row(None)

        db.execute = AsyncMock(side_effect=_multi_execute)

        app.dependency_overrides[get_db_with_tenant] = _override(db)
        client = TestClient(app)

        resp = client.post(
            "/api/v1/ops/trial-data/execute",
            json={
                "store_id": STORE_ID,
                "confirm_store_name": "错误的门店名称",  # 故意填错
                "approved_request_id": REQUEST_ID,
            },
            headers=ADMIN_HEADERS,
        )

        app.dependency_overrides.clear()
        assert resp.status_code == 422
        assert "不匹配" in resp.json().get("detail", "")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  测试 2：30天冷却期防止重复清除
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestCooldownPreventsDoubleClear:
    """30天内已有清除记录时，request 端点必须返回 429。"""

    def test_cooldown_prevents_double_clear(self):
        db = _make_db()

        async def _multi_execute(sql, params=None):
            sql_str = str(sql)
            if "employees" in sql_str:
                return _row(("super_admin",))
            if "trial_data_clear_logs" in sql_str:
                # 模拟 30 天内有清除记录
                return _row((str(uuid.uuid4()),))
            return _row(None)

        db.execute = AsyncMock(side_effect=_multi_execute)

        app.dependency_overrides[get_db_with_tenant] = _override(db)
        client = TestClient(app)

        resp = client.post(
            "/api/v1/ops/trial-data/request",
            json={
                "store_id": STORE_ID,
                "reason": "试营业阶段结束准备正式开业",
            },
            headers=ADMIN_HEADERS,
        )

        app.dependency_overrides.clear()
        assert resp.status_code == 429
        assert "冷却期" in resp.json().get("detail", "")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  测试 3：清除范围说明不包含档案数据（菜品/员工）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestClearScopePreservesMasterData:
    """GET /scope 返回的清除范围中，菜品档案和员工档案必须在 will_keep 列表中，
    且 will_clear 不包含 dishes / employees / employees 相关字段。"""

    def test_clear_scope_preserves_master_data(self):
        client = TestClient(app)
        resp = client.get("/api/v1/ops/trial-data/scope")

        assert resp.status_code == 200
        data = resp.json()["data"]

        will_clear_str = " ".join(data["will_clear"]).lower()
        will_keep_str = " ".join(data["will_keep"]).lower()

        # 档案数据不应在清除列表中
        assert "员工" not in will_clear_str
        assert "菜品" not in will_clear_str
        assert "桌位" not in will_clear_str

        # 档案数据应在保留列表中
        assert "菜品" in will_keep_str
        assert "员工" in will_keep_str
        assert "桌位" in will_keep_str

        # 交易数据应在清除列表中
        assert "orders" in will_clear_str or "订单" in will_clear_str
        assert "payments" in will_clear_str or "支付" in will_clear_str


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  测试 4：非超级管理员调用返回 403
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestSuperAdminRequired:
    """非 super_admin 角色调用 /request 和 /execute 端点必须返回 403。"""

    def _make_non_admin_db(self) -> AsyncMock:
        db = _make_db()

        async def _execute(sql, params=None):
            sql_str = str(sql)
            if "employees" in sql_str:
                # 普通员工角色
                return _row(("cashier",))
            return _row(None)

        db.execute = AsyncMock(side_effect=_execute)
        return db

    def test_super_admin_required_for_request(self):
        db = self._make_non_admin_db()
        app.dependency_overrides[get_db_with_tenant] = _override(db)
        client = TestClient(app)

        resp = client.post(
            "/api/v1/ops/trial-data/request",
            json={
                "store_id": STORE_ID,
                "reason": "想清除数据看看",
            },
            headers=STAFF_HEADERS,
        )

        app.dependency_overrides.clear()
        assert resp.status_code == 403
        assert "超级管理员" in resp.json().get("detail", "")

    def test_super_admin_required_for_execute(self):
        db = self._make_non_admin_db()
        app.dependency_overrides[get_db_with_tenant] = _override(db)
        client = TestClient(app)

        resp = client.post(
            "/api/v1/ops/trial-data/execute",
            json={
                "store_id": STORE_ID,
                "confirm_store_name": STORE_NAME,
                "approved_request_id": REQUEST_ID,
            },
            headers=STAFF_HEADERS,
        )

        app.dependency_overrides.clear()
        assert resp.status_code == 403
        assert "超级管理员" in resp.json().get("detail", "")

    def test_super_admin_required_for_status(self):
        db = self._make_non_admin_db()
        app.dependency_overrides[get_db_with_tenant] = _override(db)
        client = TestClient(app)

        resp = client.get(
            f"/api/v1/ops/trial-data/status?store_id={STORE_ID}",
            headers=STAFF_HEADERS,
        )

        app.dependency_overrides.clear()
        assert resp.status_code == 403
