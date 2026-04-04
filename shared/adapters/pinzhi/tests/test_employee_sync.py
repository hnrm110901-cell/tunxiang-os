"""
品智员工同步测试 (employee_sync.py)

Round 64 Team D — 新增测试：
  - map_to_tunxiang_employee 映射逻辑（角色映射 / 状态 / UUID确定性）
  - fetch_employees + upsert_employees 集成
  - RLS set_config 调用验证
  - 空数据 / DB异常 降级路径
"""
from __future__ import annotations

import sys
import os
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

# 将 pinzhi/src 加入搜索路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from employee_sync import PinzhiEmployeeSync


# ─── 辅助工厂 ───────────────────────────────────────────────────────────────

TENANT_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
STORE_UUID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
STORE_ID = "ognid-999"


def _make_adapter_mock(employees: list[dict] | None = None) -> MagicMock:
    adapter = MagicMock()
    adapter.get_employees = AsyncMock(return_value=employees or [])
    return adapter


def _make_db_mock() -> AsyncMock:
    db = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock())
    db.commit = AsyncMock()
    return db


def _make_pinzhi_employee(**overrides) -> dict:
    base = {
        "userId": "EMP001",
        "employeeNo": "E0001",
        "userName": "张三",
        "phone": "13800138000",
        "roleCode": "waiter",
        "status": 1,
        "ognid": STORE_ID,
    }
    base.update(overrides)
    return base


# ─── 测试：map_to_tunxiang_employee 映射逻辑 ────────────────────────────────

class TestMapToTunxiangEmployee:
    def test_basic_mapping(self):
        """基本字段正确映射"""
        raw = _make_pinzhi_employee()
        result = PinzhiEmployeeSync.map_to_tunxiang_employee(raw, TENANT_ID, STORE_UUID)

        assert result["tenant_id"] == TENANT_ID
        assert result["store_id"] == STORE_UUID
        assert result["employee_no"] == "E0001"
        assert result["name"] == "张三"
        assert result["phone"] == "13800138000"

    def test_role_waiter(self):
        """roleCode=waiter 映射为 waiter"""
        raw = _make_pinzhi_employee(roleCode="waiter")
        result = PinzhiEmployeeSync.map_to_tunxiang_employee(raw, TENANT_ID, STORE_UUID)
        assert result["role"] == "waiter"

    def test_role_manager(self):
        """roleCode=manager 映射为 store_manager"""
        raw = _make_pinzhi_employee(roleCode="manager")
        result = PinzhiEmployeeSync.map_to_tunxiang_employee(raw, TENANT_ID, STORE_UUID)
        assert result["role"] == "store_manager"

    def test_role_cashier(self):
        """roleCode=cashier 映射为 cashier"""
        raw = _make_pinzhi_employee(roleCode="cashier")
        result = PinzhiEmployeeSync.map_to_tunxiang_employee(raw, TENANT_ID, STORE_UUID)
        assert result["role"] == "cashier"

    def test_role_cook(self):
        """roleCode=cook 映射为 kitchen"""
        raw = _make_pinzhi_employee(roleCode="cook")
        result = PinzhiEmployeeSync.map_to_tunxiang_employee(raw, TENANT_ID, STORE_UUID)
        assert result["role"] == "kitchen"

    def test_role_admin(self):
        """roleCode=admin 映射为 admin"""
        raw = _make_pinzhi_employee(roleCode="admin")
        result = PinzhiEmployeeSync.map_to_tunxiang_employee(raw, TENANT_ID, STORE_UUID)
        assert result["role"] == "admin"

    def test_unknown_role_defaults_to_staff(self):
        """未知 roleCode 默认映射为 staff"""
        raw = _make_pinzhi_employee(roleCode="mysterious_role")
        result = PinzhiEmployeeSync.map_to_tunxiang_employee(raw, TENANT_ID, STORE_UUID)
        assert result["role"] == "staff"

    def test_role_case_insensitive(self):
        """roleCode 大小写不敏感（Manager → store_manager）"""
        raw = _make_pinzhi_employee(roleCode="Manager")
        result = PinzhiEmployeeSync.map_to_tunxiang_employee(raw, TENANT_ID, STORE_UUID)
        assert result["role"] == "store_manager"

    def test_status_active(self):
        """status=1 映射为 is_active=True"""
        raw = _make_pinzhi_employee(status=1)
        result = PinzhiEmployeeSync.map_to_tunxiang_employee(raw, TENANT_ID, STORE_UUID)
        assert result["is_active"] is True

    def test_status_inactive(self):
        """status=0（离职）映射为 is_active=False"""
        raw = _make_pinzhi_employee(status=0)
        result = PinzhiEmployeeSync.map_to_tunxiang_employee(raw, TENANT_ID, STORE_UUID)
        assert result["is_active"] is False

    def test_alternate_field_names(self):
        """支持品智 API v2 字段名（employeeId / name / mobile / userStatus / role）"""
        raw = {
            "employeeId": "EMP-ALT",
            "jobNo": "J999",
            "name": "李四",
            "mobile": "13900139000",
            "role": "cashier",
            "userStatus": 0,
        }
        result = PinzhiEmployeeSync.map_to_tunxiang_employee(raw, TENANT_ID, STORE_UUID)
        assert result["name"] == "李四"
        assert result["phone"] == "13900139000"
        assert result["role"] == "cashier"
        assert result["is_active"] is False

    def test_deterministic_uuid(self):
        """相同 userId + tenant_id 生成的 UUID 是确定性的"""
        raw = _make_pinzhi_employee(userId="EMP-DET")
        r1 = PinzhiEmployeeSync.map_to_tunxiang_employee(raw, TENANT_ID, STORE_UUID)
        r2 = PinzhiEmployeeSync.map_to_tunxiang_employee(raw, TENANT_ID, STORE_UUID)
        assert r1["id"] == r2["id"]

    def test_different_tenants_produce_different_uuids(self):
        """不同 tenant_id 的相同员工 ID 生成不同 UUID"""
        raw = _make_pinzhi_employee(userId="EMP-001")
        r1 = PinzhiEmployeeSync.map_to_tunxiang_employee(raw, TENANT_ID, STORE_UUID)
        r2 = PinzhiEmployeeSync.map_to_tunxiang_employee(raw, "cccccccc-cccc-cccc-cccc-cccccccccccc", STORE_UUID)
        assert r1["id"] != r2["id"]

    def test_extra_contains_source_info(self):
        """extra 字段包含 source_system=pinzhi 和原始 userId"""
        raw = _make_pinzhi_employee(userId="EMP-XYZ")
        result = PinzhiEmployeeSync.map_to_tunxiang_employee(raw, TENANT_ID, STORE_UUID)
        assert result["extra"]["source_system"] == "pinzhi"
        assert result["extra"]["pinzhi_user_id"] == "EMP-XYZ"

    def test_none_name_becomes_empty_string(self):
        """userName 为 None 时映射为空字符串"""
        raw = _make_pinzhi_employee(userName=None)
        result = PinzhiEmployeeSync.map_to_tunxiang_employee(raw, TENANT_ID, STORE_UUID)
        assert result["name"] == ""

    def test_none_phone_becomes_empty_string(self):
        """phone 为 None 时映射为空字符串"""
        raw = _make_pinzhi_employee(phone=None)
        result = PinzhiEmployeeSync.map_to_tunxiang_employee(raw, TENANT_ID, STORE_UUID)
        assert result["phone"] == ""


# ─── 测试：fetch_employees ───────────────────────────────────────────────────

class TestFetchEmployees:
    @pytest.mark.asyncio
    async def test_fetch_employees_calls_adapter(self):
        """fetch_employees 调用 adapter.get_employees 并返回结果"""
        employees = [_make_pinzhi_employee(userId="E1"), _make_pinzhi_employee(userId="E2")]
        adapter = _make_adapter_mock(employees)
        syncer = PinzhiEmployeeSync(adapter)

        result = await syncer.fetch_employees(STORE_ID)

        adapter.get_employees.assert_called_once_with(ognid=STORE_ID)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_fetch_employees_empty_store(self):
        """门店无员工时返回空列表"""
        adapter = _make_adapter_mock([])
        syncer = PinzhiEmployeeSync(adapter)

        result = await syncer.fetch_employees(STORE_ID)
        assert result == []


# ─── 测试：upsert_employees 集成 ─────────────────────────────────────────────

class TestUpsertEmployees:
    @pytest.mark.asyncio
    async def test_upsert_employees_success(self):
        """正常同步：fetch→map→UPSERT，返回正确统计"""
        employees = [
            _make_pinzhi_employee(userId="E1"),
            _make_pinzhi_employee(userId="E2"),
            _make_pinzhi_employee(userId="E3"),
        ]
        adapter = _make_adapter_mock(employees)
        syncer = PinzhiEmployeeSync(adapter)
        db = _make_db_mock()

        result = await syncer.upsert_employees(db, TENANT_ID, STORE_UUID, STORE_ID)

        assert result["total"] == 3
        assert result["upserted"] == 3
        assert result["failed"] == 0

    @pytest.mark.asyncio
    async def test_upsert_employees_sets_rls_config(self):
        """upsert_employees 第一次 DB 操作调用 set_config('app.tenant_id')"""
        adapter = _make_adapter_mock([_make_pinzhi_employee()])
        syncer = PinzhiEmployeeSync(adapter)
        db = _make_db_mock()

        await syncer.upsert_employees(db, TENANT_ID, STORE_UUID, STORE_ID)

        first_call_sql = str(db.execute.call_args_list[0][0][0])
        assert "set_config" in first_call_sql

        first_call_params = db.execute.call_args_list[0][0][1]
        assert first_call_params["tid"] == TENANT_ID

    @pytest.mark.asyncio
    async def test_upsert_employees_commits(self):
        """upsert_employees 完成后调用 db.commit()"""
        adapter = _make_adapter_mock([_make_pinzhi_employee()])
        syncer = PinzhiEmployeeSync(adapter)
        db = _make_db_mock()

        await syncer.upsert_employees(db, TENANT_ID, STORE_UUID, STORE_ID)
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_upsert_employees_empty_skips_db(self):
        """无员工数据时跳过 UPSERT 和 commit"""
        adapter = _make_adapter_mock([])
        syncer = PinzhiEmployeeSync(adapter)
        db = _make_db_mock()

        result = await syncer.upsert_employees(db, TENANT_ID, STORE_UUID, STORE_ID)

        assert result["upserted"] == 0
        db.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_upsert_employees_db_error_counts_as_failed(self):
        """单行 UPSERT 异常时计为 failed，其余行继续处理"""
        employees = [_make_pinzhi_employee(userId=f"E{i}") for i in range(3)]
        adapter = _make_adapter_mock(employees)
        syncer = PinzhiEmployeeSync(adapter)
        db = _make_db_mock()

        call_count = 0

        async def execute_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            # call 1 = set_config, call 2 = 1st employee OK, call 3 = 2nd fails
            if call_count == 3:
                raise RuntimeError("unique violation")
            return MagicMock()

        db.execute = AsyncMock(side_effect=execute_side_effect)

        result = await syncer.upsert_employees(db, TENANT_ID, STORE_UUID, STORE_ID)

        assert result["total"] == 3
        assert result["upserted"] == 2
        assert result["failed"] == 1
