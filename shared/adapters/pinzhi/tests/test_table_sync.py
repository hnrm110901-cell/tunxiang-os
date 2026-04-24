"""
品智桌台同步测试 (table_sync.py)

Round 64 Team D — 新增测试：
  - map_to_tunxiang_table 映射逻辑（状态映射 / 字段回退 / UUID确定性）
  - fetch_tables + upsert_tables 集成
  - RLS set_config 调用验证
  - 空数据 / 映射失败 / DB异常 降级路径
"""

from __future__ import annotations

import os
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

# 将 pinzhi/src 加入搜索路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from table_sync import PinzhiTableSync

# ─── 辅助工厂 ───────────────────────────────────────────────────────────────

TENANT_ID = "11111111-1111-1111-1111-111111111111"
STORE_UUID = "22222222-2222-2222-2222-222222222222"
STORE_ID = "ognid-001"


def _make_adapter_mock(tables: list[dict] | None = None) -> MagicMock:
    adapter = MagicMock()
    adapter.get_tables = AsyncMock(return_value=tables or [])
    return adapter


def _make_db_mock() -> AsyncMock:
    db = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock())
    db.commit = AsyncMock()
    return db


def _make_pinzhi_table(**overrides) -> dict:
    base = {
        "tableId": "T001",
        "tableName": "A01",
        "areaName": "大厅",
        "floor": 1,
        "personNum": 4,
        "minConsume": 0,
        "tableStatus": 1,
        "sortOrder": 10,
        "areaId": "AREA-1",
    }
    base.update(overrides)
    return base


# ─── 测试：map_to_tunxiang_table 映射逻辑 ───────────────────────────────────


class TestMapToTunxiangTable:
    def test_basic_mapping(self):
        """基本字段映射正确"""
        raw = _make_pinzhi_table()
        result = PinzhiTableSync.map_to_tunxiang_table(raw, TENANT_ID, STORE_UUID)

        assert result["tenant_id"] == TENANT_ID
        assert result["store_id"] == STORE_UUID
        assert result["table_no"] == "A01"
        assert result["area"] == "大厅"
        assert result["floor"] == 1
        assert result["seats"] == 4
        assert result["min_consume_fen"] == 0
        assert result["sort_order"] == 10

    def test_status_free(self):
        """tableStatus=1 映射为 free，is_active=True"""
        raw = _make_pinzhi_table(tableStatus=1)
        result = PinzhiTableSync.map_to_tunxiang_table(raw, TENANT_ID, STORE_UUID)
        assert result["status"] == "free"
        assert result["is_active"] is True

    def test_status_occupied(self):
        """tableStatus=2 映射为 occupied，is_active=True"""
        raw = _make_pinzhi_table(tableStatus=2)
        result = PinzhiTableSync.map_to_tunxiang_table(raw, TENANT_ID, STORE_UUID)
        assert result["status"] == "occupied"
        assert result["is_active"] is True

    def test_status_inactive(self):
        """tableStatus=0 映射为 inactive，is_active=False"""
        raw = _make_pinzhi_table(tableStatus=0)
        result = PinzhiTableSync.map_to_tunxiang_table(raw, TENANT_ID, STORE_UUID)
        assert result["status"] == "inactive"
        assert result["is_active"] is False

    def test_unknown_status_defaults_to_free(self):
        """未知 status 值默认映射为 free"""
        raw = _make_pinzhi_table(tableStatus=99)
        result = PinzhiTableSync.map_to_tunxiang_table(raw, TENANT_ID, STORE_UUID)
        assert result["status"] == "free"

    def test_alternate_field_names(self):
        """支持品智 API v2 字段名（status/tableNo/seats）"""
        raw = {
            "id": "T999",
            "tableNo": "B02",
            "area": "包间",
            "floor": 2,
            "seats": 8,
            "minConsume": 50000,
            "status": 2,
            "tableSort": 5,
            "areaId": "AREA-2",
        }
        result = PinzhiTableSync.map_to_tunxiang_table(raw, TENANT_ID, STORE_UUID)
        assert result["table_no"] == "B02"
        assert result["area"] == "包间"
        assert result["seats"] == 8
        assert result["min_consume_fen"] == 50000
        assert result["status"] == "occupied"
        assert result["sort_order"] == 5

    def test_deterministic_uuid(self):
        """相同 tableId + tenant_id 生成的 UUID 是确定性的"""
        raw = _make_pinzhi_table(tableId="T123")
        r1 = PinzhiTableSync.map_to_tunxiang_table(raw, TENANT_ID, STORE_UUID)
        r2 = PinzhiTableSync.map_to_tunxiang_table(raw, TENANT_ID, STORE_UUID)
        assert r1["id"] == r2["id"]

    def test_different_tenants_produce_different_uuids(self):
        """不同 tenant_id 的相同桌台 ID 生成不同 UUID"""
        raw = _make_pinzhi_table(tableId="T001")
        r1 = PinzhiTableSync.map_to_tunxiang_table(raw, TENANT_ID, STORE_UUID)
        r2 = PinzhiTableSync.map_to_tunxiang_table(raw, "99999999-9999-9999-9999-999999999999", STORE_UUID)
        assert r1["id"] != r2["id"]

    def test_config_contains_source_system(self):
        """config 字段包含 source_system=pinzhi 和 pinzhi_table_id"""
        raw = _make_pinzhi_table(tableId="T-ABC")
        result = PinzhiTableSync.map_to_tunxiang_table(raw, TENANT_ID, STORE_UUID)
        assert result["config"]["source_system"] == "pinzhi"
        assert result["config"]["pinzhi_table_id"] == "T-ABC"

    def test_none_values_fallback_to_defaults(self):
        """None 值字段回退为安全默认值"""
        raw = {
            "tableId": "T000",
            "tableName": None,
            "areaName": None,
            "floor": None,
            "personNum": None,
            "minConsume": None,
            "tableStatus": None,
            "sortOrder": None,
        }
        result = PinzhiTableSync.map_to_tunxiang_table(raw, TENANT_ID, STORE_UUID)
        assert result["floor"] == 1
        assert result["seats"] == 4
        assert result["min_consume_fen"] == 0
        assert result["sort_order"] == 0
        assert result["area"] == ""


# ─── 测试：fetch_tables ───────────────────────────────────────────────────────


class TestFetchTables:
    @pytest.mark.asyncio
    async def test_fetch_tables_calls_adapter(self):
        """fetch_tables 调用 adapter.get_tables 并返回结果"""
        tables = [_make_pinzhi_table(tableId="T1"), _make_pinzhi_table(tableId="T2")]
        adapter = _make_adapter_mock(tables)
        syncer = PinzhiTableSync(adapter)

        result = await syncer.fetch_tables(STORE_ID)

        adapter.get_tables.assert_called_once_with(ognid=STORE_ID)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_fetch_tables_returns_empty_list(self):
        """门店无桌台时返回空列表"""
        adapter = _make_adapter_mock([])
        syncer = PinzhiTableSync(adapter)

        result = await syncer.fetch_tables(STORE_ID)
        assert result == []


# ─── 测试：upsert_tables 集成 ────────────────────────────────────────────────


class TestUpsertTables:
    @pytest.mark.asyncio
    async def test_upsert_tables_success(self):
        """正常同步：fetch→map→UPSERT，返回正确统计"""
        tables = [_make_pinzhi_table(tableId="T1"), _make_pinzhi_table(tableId="T2")]
        adapter = _make_adapter_mock(tables)
        syncer = PinzhiTableSync(adapter)
        db = _make_db_mock()

        result = await syncer.upsert_tables(db, TENANT_ID, STORE_UUID, STORE_ID)

        assert result["total"] == 2
        assert result["upserted"] == 2
        assert result["failed"] == 0

    @pytest.mark.asyncio
    async def test_upsert_tables_sets_rls_config(self):
        """upsert_tables 在首次 DB 操作前调用 set_config('app.tenant_id')"""
        tables = [_make_pinzhi_table()]
        adapter = _make_adapter_mock(tables)
        syncer = PinzhiTableSync(adapter)
        db = _make_db_mock()

        await syncer.upsert_tables(db, TENANT_ID, STORE_UUID, STORE_ID)

        first_call_sql = str(db.execute.call_args_list[0][0][0])
        assert "set_config" in first_call_sql

        first_call_params = db.execute.call_args_list[0][0][1]
        assert first_call_params["tid"] == TENANT_ID

    @pytest.mark.asyncio
    async def test_upsert_tables_commits_after_upsert(self):
        """upsert_tables 完成后调用 db.commit()"""
        adapter = _make_adapter_mock([_make_pinzhi_table()])
        syncer = PinzhiTableSync(adapter)
        db = _make_db_mock()

        await syncer.upsert_tables(db, TENANT_ID, STORE_UUID, STORE_ID)
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_upsert_tables_empty_list_skips_db(self):
        """品智无桌台数据时，跳过 UPSERT，不调用 commit"""
        adapter = _make_adapter_mock([])
        syncer = PinzhiTableSync(adapter)
        db = _make_db_mock()

        result = await syncer.upsert_tables(db, TENANT_ID, STORE_UUID, STORE_ID)

        assert result["upserted"] == 0
        db.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_upsert_tables_db_error_counts_as_failed(self):
        """单行 UPSERT 异常时记录为 failed，不中断整批"""
        tables = [_make_pinzhi_table(tableId="T1"), _make_pinzhi_table(tableId="T2")]
        adapter = _make_adapter_mock(tables)
        syncer = PinzhiTableSync(adapter)
        db = _make_db_mock()

        call_count = 0

        async def execute_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            # set_config call = 1, first table ok, second table fails
            if call_count == 3:
                raise RuntimeError("DB constraint violation")
            return MagicMock()

        db.execute = AsyncMock(side_effect=execute_side_effect)

        result = await syncer.upsert_tables(db, TENANT_ID, STORE_UUID, STORE_ID)

        assert result["total"] == 2
        assert result["upserted"] == 1
        assert result["failed"] == 1
