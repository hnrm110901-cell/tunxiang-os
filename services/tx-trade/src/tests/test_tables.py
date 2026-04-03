"""桌台与包厢经营中心测试 — 覆盖转台/并台/拆台/清台/预留/包厢规则

使用 mock AsyncSession 避免真实数据库依赖。
"""
import os
import sys
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ─── Fixtures ───


def _make_table(
    *,
    table_no: str = "A01",
    status: str = "free",
    area: str = "大厅",
    seats: int = 4,
    min_consume_fen: int = 0,
    store_id: uuid.UUID | None = None,
    tenant_id: uuid.UUID | None = None,
    current_order_id: uuid.UUID | None = None,
    config: dict | None = None,
) -> MagicMock:
    """构造一个 mock Table 对象"""
    t = MagicMock()
    t.id = uuid.uuid4()
    t.table_no = table_no
    t.status = status
    t.area = area
    t.seats = seats
    t.min_consume_fen = min_consume_fen
    t.store_id = store_id or uuid.uuid4()
    t.tenant_id = tenant_id or uuid.uuid4()
    t.current_order_id = current_order_id
    t.config = config or {}
    t.floor = 1
    t.sort_order = 0
    t.is_active = True
    t.is_deleted = False
    return t


def _mock_db_returning(table: MagicMock) -> AsyncMock:
    """创建一个 mock db session，execute 返回指定 table"""
    db = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = table
    db.execute.return_value = result_mock
    return db


def _mock_db_sequence(tables: list[MagicMock]) -> AsyncMock:
    """创建一个 mock db session，按顺序返回多个 table"""
    db = AsyncMock()
    results = []
    for t in tables:
        r = MagicMock()
        r.scalar_one_or_none.return_value = t
        results.append(r)
    db.execute.side_effect = results
    return db


TENANT_ID = uuid.uuid4()


# ─── Test: 转台 ───


class TestTransferTable:
    @pytest.mark.asyncio
    async def test_transfer_success(self):
        """转台成功：源桌 occupied -> free，目标桌 free -> occupied"""
        from services.table_operations import transfer_table

        from_t = _make_table(table_no="A01", status="occupied", tenant_id=TENANT_ID)
        to_t = _make_table(table_no="A02", status="free", tenant_id=TENANT_ID)
        order_id = uuid.uuid4()

        db = _mock_db_sequence([from_t, to_t])

        result = await transfer_table(from_t.id, to_t.id, order_id, TENANT_ID, db)

        assert result["from_table"]["status"] == "free"
        assert result["to_table"]["status"] == "occupied"
        assert result["order_id"] == str(order_id)

    @pytest.mark.asyncio
    async def test_transfer_fails_if_source_not_occupied(self):
        """源桌非 occupied 时转台失败"""
        from services.table_operations import transfer_table

        from_t = _make_table(table_no="A01", status="free", tenant_id=TENANT_ID)
        to_t = _make_table(table_no="A02", status="free", tenant_id=TENANT_ID)

        db = _mock_db_sequence([from_t, to_t])

        with pytest.raises(ValueError, match="需为 occupied"):
            await transfer_table(from_t.id, to_t.id, uuid.uuid4(), TENANT_ID, db)

    @pytest.mark.asyncio
    async def test_transfer_fails_if_target_not_free(self):
        """目标桌非 free 时转台失败"""
        from services.table_operations import transfer_table

        from_t = _make_table(table_no="A01", status="occupied", tenant_id=TENANT_ID)
        to_t = _make_table(table_no="A02", status="occupied", tenant_id=TENANT_ID)

        db = _mock_db_sequence([from_t, to_t])

        with pytest.raises(ValueError, match="需为 free"):
            await transfer_table(from_t.id, to_t.id, uuid.uuid4(), TENANT_ID, db)


# ─── Test: 并台 ───


class TestMergeTables:
    @pytest.mark.asyncio
    async def test_merge_success(self):
        """并台成功：主桌 config 包含 merged_with"""
        from services.table_operations import merge_tables

        t1 = _make_table(table_no="A01", status="occupied", seats=4, tenant_id=TENANT_ID)
        t2 = _make_table(table_no="A02", status="free", seats=4, tenant_id=TENANT_ID)
        main_id = t1.id

        db = _mock_db_sequence([t1, t2])

        result = await merge_tables([t1.id, t2.id], main_id, TENANT_ID, db)

        assert result["merged_count"] == 2
        assert result["total_seats"] == 8
        assert result["main_table"]["table_no"] == "A01"

    @pytest.mark.asyncio
    async def test_merge_requires_at_least_two(self):
        """并台至少需要 2 张桌"""
        from services.table_operations import merge_tables

        t1 = _make_table(table_no="A01", tenant_id=TENANT_ID)
        db = AsyncMock()

        with pytest.raises(ValueError, match="至少需要 2 张"):
            await merge_tables([t1.id], t1.id, TENANT_ID, db)


# ─── Test: 清台 ───


class TestClearTable:
    @pytest.mark.asyncio
    async def test_clear_occupied_table(self):
        """清台：occupied -> free"""
        from services.table_operations import clear_table

        t = _make_table(table_no="B01", status="occupied", tenant_id=TENANT_ID)
        db = _mock_db_returning(t)

        result = await clear_table(t.id, TENANT_ID, db)

        assert result["status"] == "free"
        assert t.status == "free"
        assert t.current_order_id is None

    @pytest.mark.asyncio
    async def test_clear_fails_if_free(self):
        """已空闲的桌台无法再清台"""
        from services.table_operations import clear_table

        t = _make_table(table_no="B02", status="free", tenant_id=TENANT_ID)
        db = _mock_db_returning(t)

        with pytest.raises(ValueError, match="无法清台"):
            await clear_table(t.id, TENANT_ID, db)


# ─── Test: 预留 ───


class TestLockTable:
    @pytest.mark.asyncio
    async def test_lock_success(self):
        """预留成功：free -> reserved"""
        from services.table_operations import lock_table

        t = _make_table(table_no="C01", status="free", tenant_id=TENANT_ID)
        reservation_id = uuid.uuid4()
        db = _mock_db_returning(t)

        result = await lock_table(t.id, reservation_id, TENANT_ID, db)

        assert result["status"] == "reserved"
        assert result["reservation_id"] == str(reservation_id)


# ─── Test: 包厢低消 ───


class TestRoomRules:
    @pytest.mark.asyncio
    async def test_minimum_charge_met(self):
        """低消达标"""
        from services.room_rules import check_minimum_charge

        room = _make_table(
            table_no="VIP01", area="包间", min_consume_fen=50000, tenant_id=TENANT_ID,
        )
        db = _mock_db_returning(room)

        result = await check_minimum_charge(room.id, 60000, TENANT_ID, db)

        assert result["met"] is True
        assert result["gap_fen"] == 0

    @pytest.mark.asyncio
    async def test_minimum_charge_not_met(self):
        """低消未达标：gap_fen > 0"""
        from services.room_rules import check_minimum_charge

        room = _make_table(
            table_no="VIP02", area="包间", min_consume_fen=50000, tenant_id=TENANT_ID,
        )
        db = _mock_db_returning(room)

        result = await check_minimum_charge(room.id, 30000, TENANT_ID, db)

        assert result["met"] is False
        assert result["gap_fen"] == 20000
        assert result["minimum_fen"] == 50000

    @pytest.mark.asyncio
    async def test_get_room_config(self):
        """查询包厢配置"""
        from services.room_rules import get_room_config

        room = _make_table(
            table_no="VIP03",
            area="包厢",
            seats=12,
            min_consume_fen=80000,
            config={"time_limit_minutes": 120},
            tenant_id=TENANT_ID,
        )
        db = _mock_db_returning(room)

        result = await get_room_config(room.id, TENANT_ID, db)

        assert result["minimum_charge_fen"] == 80000
        assert result["capacity"] == 12
        assert result["time_limit_minutes"] == 120

    @pytest.mark.asyncio
    async def test_set_room_rules(self):
        """设置包厢规则"""
        from services.room_rules import set_room_rules

        room = _make_table(
            table_no="VIP04",
            area="包间",
            seats=8,
            min_consume_fen=30000,
            tenant_id=TENANT_ID,
        )
        db = _mock_db_returning(room)

        result = await set_room_rules(
            room.id,
            {"minimum_charge_fen": 60000, "time_limit_minutes": 90, "capacity": 10},
            TENANT_ID,
            db,
        )

        assert result["minimum_charge_fen"] == 60000
        assert result["capacity"] == 10
        assert result["time_limit_minutes"] == 90
        assert room.min_consume_fen == 60000
        assert room.seats == 10
