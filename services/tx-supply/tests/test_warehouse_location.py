"""库位/库区/温区服务测试 — TASK-2 (v367)

测试覆盖：
1. test_create_zone_persists                 创建库区 → DB INSERT
2. test_create_location_under_zone           库位创建（zone 校验）
3. test_auto_allocate_matches_temperature    海鲜→活鲜区/肉→冷藏区
4. test_auto_allocate_rejects_mismatch       温区类目不匹配抛 TemperatureMismatchError
5. test_move_between_locations_updates       库位间转移（更新两条记录）
6. test_zone_utilization_calculation         库区使用率计算
7. test_cross_tenant_isolation               RLS：跨租户查询返回空
8. test_abc_suggestion_based_on_turnover     ABC 重分类建议
9. test_bind_ingredient_emits_event          绑定主库位发事件
10. test_move_insufficient_inventory_raises  库存不足抛异常

实现策略：
  使用 mock AsyncSession（参照 test_stocktake_db.py 风格）。
  对于 DB 行返回，构造 mappings.one_or_none / all 返回所需 dict。
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from services.tx_supply.src.models.warehouse_location import (
    AutoAllocateRequest,
    BindIngredientRequest,
    LocationCreate,
    MoveBetweenLocationsRequest,
    TemperatureType,
    ZoneCreate,
)
from services.tx_supply.src.services import warehouse_location_service as svc
from services.tx_supply.src.services.warehouse_location_service import (
    InsufficientInventoryError,
    LocationNotFoundError,
    TemperatureMismatchError,
)

TENANT_A = str(uuid.uuid4())
TENANT_B = str(uuid.uuid4())
STORE_ID = str(uuid.uuid4())
ZONE_ID = str(uuid.uuid4())


# ─────────────────────────────────────────────────────────────────────────────
# 工具：mock execute / mappings
# ─────────────────────────────────────────────────────────────────────────────


def _mock_result(
    *,
    one: dict | None = None,
    many: list[dict] | None = None,
    first: Any = None,
) -> MagicMock:
    """构造可调用 mappings().one_or_none() / all() 的 result mock。"""
    result = MagicMock()
    mp = MagicMock()
    mp.one_or_none = MagicMock(return_value=one)
    mp.all = MagicMock(return_value=list(many or []))
    result.mappings = MagicMock(return_value=mp)
    result.first = MagicMock(return_value=first)
    return result


class _ScriptedDB:
    """按调用顺序返回预设 result 的 mock AsyncSession。

    缺省返回空 result；首次匹配某 SQL 关键字返回对应 mock。
    """

    def __init__(self, sql_to_results: list[tuple[str, MagicMock]]):
        self.sql_to_results = list(sql_to_results)
        self.calls: list[tuple[str, dict]] = []
        self.flush = AsyncMock()
        self.add = MagicMock()

    async def execute(self, query, params=None):  # type: ignore[no-untyped-def]
        sql = str(query)
        self.calls.append((sql, params or {}))
        for keyword, result in self.sql_to_results:
            if keyword in sql:
                # 一次性消费
                self.sql_to_results.remove((keyword, result))
                return result
        return _mock_result()


# ─────────────────────────────────────────────────────────────────────────────
# 1. test_create_zone_persists
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_zone_persists():
    """create_zone 应执行 INSERT + SELECT 回查"""
    body = ZoneCreate(
        store_id=STORE_ID,
        zone_code="Z-COLD-01",
        zone_name="冷藏区A",
        temperature_type=TemperatureType.REFRIGERATED,
        min_temp_celsius=Decimal("0.0"),
        max_temp_celsius=Decimal("8.0"),
        description="主冷藏区",
    )

    fetched_row = {
        "id": uuid.uuid4(),
        "tenant_id": uuid.UUID(TENANT_A),
        "store_id": uuid.UUID(STORE_ID),
        "zone_code": body.zone_code,
        "zone_name": body.zone_name,
        "temperature_type": "REFRIGERATED",
        "min_temp_celsius": Decimal("0.0"),
        "max_temp_celsius": Decimal("8.0"),
        "description": body.description,
        "enabled": True,
        "created_at": MagicMock(isoformat=MagicMock(return_value="2026-04-27T00:00:00+00:00")),
        "updated_at": MagicMock(isoformat=MagicMock(return_value="2026-04-27T00:00:00+00:00")),
    }

    db = _ScriptedDB(
        [
            ("set_config", _mock_result()),
            ("INSERT INTO warehouse_zones", _mock_result()),
            ("set_config", _mock_result()),
            ("FROM warehouse_zones", _mock_result(one=fetched_row)),
        ]
    )

    data = await svc.create_zone(body, TENANT_A, db)
    assert data["zone_code"] == "Z-COLD-01"
    assert data["temperature_type"] == "REFRIGERATED"
    # 第一次调用必须是 set_config
    assert "set_config" in db.calls[0][0]


# ─────────────────────────────────────────────────────────────────────────────
# 2. test_create_location_under_zone
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_location_under_zone():
    body = LocationCreate(
        zone_id=ZONE_ID,
        store_id=STORE_ID,
        location_code="A-01-03",
        aisle="A",
        rack="01",
        shelf="03",
        abc_class="A",
        max_capacity_units=100,
    )

    fetched = {
        "id": uuid.uuid4(),
        "tenant_id": uuid.UUID(TENANT_A),
        "zone_id": uuid.UUID(ZONE_ID),
        "store_id": uuid.UUID(STORE_ID),
        "location_code": "A-01-03",
        "aisle": "A",
        "rack": "01",
        "shelf": "03",
        "abc_class": "A",
        "max_capacity_units": 100,
        "enabled": True,
        "created_at": MagicMock(isoformat=MagicMock(return_value="x")),
        "updated_at": MagicMock(isoformat=MagicMock(return_value="x")),
    }

    db = _ScriptedDB(
        [
            ("set_config", _mock_result()),
            ("FROM warehouse_zones", _mock_result(one={"store_id": uuid.UUID(STORE_ID)})),
            ("INSERT INTO warehouse_locations", _mock_result()),
            ("set_config", _mock_result()),
            ("FROM warehouse_locations", _mock_result(one=fetched)),
        ]
    )

    data = await svc.create_location(body, TENANT_A, db)
    assert data["location_code"] == "A-01-03"
    assert data["abc_class"] == "A"


# ─────────────────────────────────────────────────────────────────────────────
# 3. test_auto_allocate_matches_temperature_type
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_auto_allocate_matches_temperature_type():
    """海鲜应被分到活鲜或冷冻区，按 ABC 优先级排序"""
    body = AutoAllocateRequest(
        ingredient_id=str(uuid.uuid4()),
        store_id=STORE_ID,
        quantity=Decimal("5.0"),
        ingredient_category="seafood",
    )

    candidate_loc_id = uuid.uuid4()
    candidate_row = {
        "id": candidate_loc_id,
        "zone_id": uuid.uuid4(),
        "location_code": "LIVE-01",
        "abc_class": "A",
        "max_capacity_units": 50,
        "temperature_type": "LIVE_SEAFOOD",
        "current_units": Decimal("10.0"),
    }

    db = _ScriptedDB(
        [
            ("set_config", _mock_result()),
            # ingredient_location_bindings 主库位查询：返回空
            ("ingredient_location_bindings", _mock_result(one=None)),
            # 候选库位查询：返回 LIVE_SEAFOOD A 类
            ("warehouse_locations l", _mock_result(many=[candidate_row])),
            # INSERT inventory_by_location
            ("INSERT INTO inventory_by_location", _mock_result()),
        ]
    )

    data = await svc.auto_allocate_location(body, TENANT_A, db)
    assert data["temperature_type"] == "LIVE_SEAFOOD"
    assert data["abc_class"] == "A"
    assert data["quantity_allocated"] == 5.0


# ─────────────────────────────────────────────────────────────────────────────
# 4. test_auto_allocate_rejects_temperature_mismatch
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_auto_allocate_rejects_temperature_mismatch():
    """已绑定主库位是常温，但食材是海鲜 → 抛 TemperatureMismatchError"""
    body = AutoAllocateRequest(
        ingredient_id=str(uuid.uuid4()),
        store_id=STORE_ID,
        quantity=Decimal("3.0"),
        ingredient_category="seafood",
    )

    primary_row = {
        "id": uuid.uuid4(),
        "zone_id": uuid.uuid4(),
        "location_code": "DRY-01",
        "abc_class": "B",
        "max_capacity_units": 100,
        "temperature_type": "NORMAL",  # 错误：海鲜不能放常温
    }

    db = _ScriptedDB(
        [
            ("set_config", _mock_result()),
            ("ingredient_location_bindings", _mock_result(one=primary_row)),
        ]
    )

    with pytest.raises(TemperatureMismatchError):
        await svc.auto_allocate_location(body, TENANT_A, db)


# ─────────────────────────────────────────────────────────────────────────────
# 5. test_move_between_locations_updates_inventory
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_move_between_locations_updates_inventory():
    from_loc = str(uuid.uuid4())
    to_loc = str(uuid.uuid4())
    ing_id = str(uuid.uuid4())

    body = MoveBetweenLocationsRequest(
        from_location_id=from_loc,
        to_location_id=to_loc,
        ingredient_id=ing_id,
        quantity=Decimal("2.0"),
        batch_no="B-2026-01",
        operator_id=str(uuid.uuid4()),
    )

    src_row = {
        "id": uuid.uuid4(),
        "quantity": Decimal("10.0"),
        "expiry_date": None,
        "store_id": uuid.UUID(STORE_ID),
    }
    tgt_loc_row = {"store_id": uuid.UUID(STORE_ID)}

    db = _ScriptedDB(
        [
            ("set_config", _mock_result()),
            ("FROM inventory_by_location", _mock_result(one=src_row)),
            ("FROM warehouse_locations", _mock_result(one=tgt_loc_row)),
            ("UPDATE inventory_by_location", _mock_result()),
            ("INSERT INTO inventory_by_location", _mock_result()),
        ]
    )

    data = await svc.move_between_locations(body, TENANT_A, db)
    assert data["ok"] is True
    assert data["from_location_id"] == from_loc
    assert data["to_location_id"] == to_loc
    assert data["quantity"] == 2.0


@pytest.mark.asyncio
async def test_move_insufficient_inventory_raises():
    body = MoveBetweenLocationsRequest(
        from_location_id=str(uuid.uuid4()),
        to_location_id=str(uuid.uuid4()),
        ingredient_id=str(uuid.uuid4()),
        quantity=Decimal("100.0"),  # 大于源库存
    )

    src_row = {
        "id": uuid.uuid4(),
        "quantity": Decimal("5.0"),  # 不够
        "expiry_date": None,
        "store_id": uuid.UUID(STORE_ID),
    }

    db = _ScriptedDB(
        [
            ("set_config", _mock_result()),
            ("FROM inventory_by_location", _mock_result(one=src_row)),
        ]
    )

    with pytest.raises(InsufficientInventoryError):
        await svc.move_between_locations(body, TENANT_A, db)


# ─────────────────────────────────────────────────────────────────────────────
# 6. test_zone_utilization_calculation
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_zone_utilization_calculation():
    """zone_utilization = used / total_capacity"""
    db = _ScriptedDB(
        [
            ("set_config", _mock_result()),
            (
                "FROM warehouse_locations",
                _mock_result(one={"loc_count": 4, "total_capacity": Decimal("400")}),
            ),
            (
                "FROM inventory_by_location ibl",
                _mock_result(one={"used_units": Decimal("100")}),
            ),
        ]
    )

    data = await svc.compute_zone_utilization(ZONE_ID, TENANT_A, db)
    assert data["location_count"] == 4
    assert data["total_capacity_units"] == 400.0
    assert data["used_units"] == 100.0
    assert data["utilization_pct"] == 0.25  # 100/400


@pytest.mark.asyncio
async def test_zone_utilization_empty_zone():
    """空库区返回 0 %"""
    db = _ScriptedDB(
        [
            ("set_config", _mock_result()),
            (
                "FROM warehouse_locations",
                _mock_result(one={"loc_count": 0, "total_capacity": Decimal("0")}),
            ),
        ]
    )
    data = await svc.compute_zone_utilization(ZONE_ID, TENANT_A, db)
    assert data["utilization_pct"] == 0.0
    assert data["location_count"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# 7. test_cross_tenant_isolation
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cross_tenant_isolation():
    """模拟 RLS：tenant_B 的 set_config 后查询 tenant_A 的 zone 应返回空。

    这里我们验证 service 层正确把 x_tenant_id 通过 set_config 注入。
    DB 层 RLS 真正生效需依赖集成测试，单元测试只校验路径。
    """
    db = _ScriptedDB(
        [
            ("set_config", _mock_result()),
            # 模拟 RLS 拦截：tenant_B 看不到 tenant_A 的 zone
            ("FROM warehouse_zones", _mock_result(many=[])),
        ]
    )

    data = await svc.list_zones(STORE_ID, TENANT_B, db)
    assert data == []
    # 确认 set_config 被调用且参数是 TENANT_B
    setcfg_calls = [c for c in db.calls if "set_config" in c[0]]
    assert setcfg_calls, "未调用 set_config"
    assert setcfg_calls[0][1].get("tid") == TENANT_B


# ─────────────────────────────────────────────────────────────────────────────
# 8. test_abc_suggestion_based_on_turnover
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_abc_suggestion_based_on_turnover():
    """5 个食材，前 1 个应是 A，中 1 个 B，后 3 个 C"""
    ing_ids = [uuid.uuid4() for _ in range(5)]
    turnover_rows = [
        {"ingredient_id": ing_ids[0], "turn_count": 100},
        {"ingredient_id": ing_ids[1], "turn_count": 50},
        {"ingredient_id": ing_ids[2], "turn_count": 30},
        {"ingredient_id": ing_ids[3], "turn_count": 20},
        {"ingredient_id": ing_ids[4], "turn_count": 5},
    ]

    # 每个 ingredient 主库位查询都返回 None（即"未绑定"）→ 全部产生建议
    scripted = [
        ("set_config", _mock_result()),
        ("FROM ingredient_transactions", _mock_result(many=turnover_rows)),
    ]
    for _ in range(5):
        scripted.append(("ingredient_location_bindings", _mock_result(one=None)))

    db = _ScriptedDB(scripted)

    data = await svc.suggest_abc_optimization(STORE_ID, TENANT_A, db, days=30)
    assert data["total_ingredients"] == 5
    sugg = data["suggestions"]
    # 因为 current_abc=None vs suggested 不同，5 个都会出现
    assert len(sugg) == 5
    # 第一个建议是最高频的 → A
    assert sugg[0]["ingredient_id"] == str(ing_ids[0])
    assert sugg[0]["suggested_abc"] == "A"
    # 第二个 → B
    assert sugg[1]["suggested_abc"] == "B"
    # 末三个 → C
    for s in sugg[2:]:
        assert s["suggested_abc"] == "C"


# ─────────────────────────────────────────────────────────────────────────────
# 9. test_bind_ingredient
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_bind_ingredient_to_location():
    location_id = str(uuid.uuid4())
    ing_id = str(uuid.uuid4())
    body = BindIngredientRequest(
        ingredient_id=ing_id,
        is_primary=True,
        bound_by=str(uuid.uuid4()),
    )

    fetched_loc = {
        "id": uuid.UUID(location_id),
        "tenant_id": uuid.UUID(TENANT_A),
        "zone_id": uuid.uuid4(),
        "store_id": uuid.UUID(STORE_ID),
        "location_code": "A-01-01",
        "aisle": "A",
        "rack": "01",
        "shelf": "01",
        "abc_class": "A",
        "max_capacity_units": 50,
        "enabled": True,
        "created_at": MagicMock(isoformat=MagicMock(return_value="x")),
        "updated_at": MagicMock(isoformat=MagicMock(return_value="x")),
    }

    db = _ScriptedDB(
        [
            ("set_config", _mock_result()),
            ("set_config", _mock_result()),  # _fetch_location 内部
            ("FROM warehouse_locations", _mock_result(one=fetched_loc)),
            ("UPDATE ingredient_location_bindings", _mock_result()),
            ("INSERT INTO ingredient_location_bindings", _mock_result()),
        ]
    )

    data = await svc.bind_ingredient_to_location(location_id, body, TENANT_A, db)
    assert data["ok"] is True
    assert data["is_primary"] is True
    assert data["ingredient_id"] == ing_id


# ─────────────────────────────────────────────────────────────────────────────
# 10. test_auto_allocate_no_category_no_binding_raises
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_auto_allocate_requires_category_or_binding():
    """无主库位绑定 + 无 ingredient_category → 抛 WarehouseLocationError"""
    body = AutoAllocateRequest(
        ingredient_id=str(uuid.uuid4()),
        store_id=STORE_ID,
        quantity=Decimal("1.0"),
        ingredient_category=None,
    )
    db = _ScriptedDB(
        [
            ("set_config", _mock_result()),
            ("ingredient_location_bindings", _mock_result(one=None)),
        ]
    )
    with pytest.raises(svc.WarehouseLocationError):
        await svc.auto_allocate_location(body, TENANT_A, db)


# ─────────────────────────────────────────────────────────────────────────────
# 11. test_get_location_by_code_not_found
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_location_by_code_not_found():
    db = _ScriptedDB(
        [
            ("set_config", _mock_result()),
            ("FROM warehouse_locations", _mock_result(one=None)),
        ]
    )
    with pytest.raises(LocationNotFoundError):
        await svc.get_location_by_code("NONEXIST", STORE_ID, TENANT_A, db)
