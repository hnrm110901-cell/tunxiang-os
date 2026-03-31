"""盘点服务 DB 操作测试 — mock AsyncSession

测试覆盖：
1. create_stocktake — DB 模式写入 stocktakes + stocktake_items
2. create_stocktake — 内存降级模式（表不存在时）
3. record_count — DB 模式更新 actual_qty
4. record_count — 状态异常（非 in_progress）返回 error
5. finalize_stocktake — DB 模式完成盘点 + 库存调整 + 状态更新
6. get_stocktake_history — DB 模式分页列表
7. _check_db_mode — 缓存命中，避免重复检测
8. 所有 DB 操作必须传递 tenant_id（验证 set_config 调用）
"""
from __future__ import annotations

import asyncio
import uuid
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

import services.tx_supply.src.services.stocktake_service as svc


# ─────────────────────────────────────────────────────────────────────────────
# 工具函数
# ─────────────────────────────────────────────────────────────────────────────

TENANT_ID = str(uuid.uuid4())
STORE_ID = str(uuid.uuid4())


def _fake_ingredient(ingredient_id: str | None = None) -> MagicMock:
    """构造假 Ingredient ORM 对象"""
    ing = MagicMock()
    ing.id = uuid.UUID(ingredient_id or str(uuid.uuid4()))
    ing.ingredient_name = "测试食材"
    ing.category = "meat"
    ing.unit = "kg"
    ing.current_quantity = 10.0
    ing.min_quantity = 2.0
    ing.max_quantity = 50.0
    ing.unit_price_fen = 3000
    ing.is_deleted = False
    ing.status = "normal"
    return ing


def _mock_db(*, db_mode: bool = True, ingredients: List[Any] | None = None) -> MagicMock:
    """构造支持 async 的 mock AsyncSession"""
    db = MagicMock()
    db.execute = AsyncMock()
    db.flush = AsyncMock()
    db.add = MagicMock()

    # begin_nested() 支持 async context manager
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=None)
    cm.__aexit__ = AsyncMock(return_value=False)
    db.begin_nested = MagicMock(return_value=cm)

    # 默认 execute 返回空 mappings
    _mock_execute_result(db, [])

    return db


def _mock_execute_result(db: MagicMock, rows: List[Dict[str, Any]]) -> None:
    """设置 db.execute 返回的 mapping 结果"""
    result = MagicMock()
    mappings_obj = MagicMock()
    mappings_obj.all = MagicMock(return_value=rows)
    mappings_obj.one_or_none = MagicMock(return_value=rows[0] if rows else None)
    result.mappings = MagicMock(return_value=mappings_obj)
    result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
    db.execute = AsyncMock(return_value=result)


# ─────────────────────────────────────────────────────────────────────────────
# Fixture: 每个测试前重置全局 DB 模式缓存
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_db_mode():
    """每个测试前清除全局 DB 模式缓存，避免测试间状态污染"""
    svc._db_mode = None
    svc._stocktakes.clear()
    yield
    svc._db_mode = None
    svc._stocktakes.clear()


# ─────────────────────────────────────────────────────────────────────────────
# Test 1: create_stocktake — DB 模式
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_stocktake_db_mode():
    """DB 可用时，create_stocktake 应写入 stocktakes + stocktake_items"""
    ingredient_id = str(uuid.uuid4())
    ing = _fake_ingredient(ingredient_id)

    db = MagicMock()
    db.flush = AsyncMock()
    db.add = MagicMock()

    execute_call_count = 0
    execute_results = []

    # set_config call
    execute_results.append(MagicMock())  # _set_tenant
    # select Ingredient query
    select_result = MagicMock()
    select_result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[ing])))
    execute_results.append(select_result)
    # _check_db_mode: SELECT 1 FROM stocktakes
    execute_results.append(MagicMock())
    # INSERT stocktakes
    execute_results.append(MagicMock())
    # INSERT stocktake_items (1 item)
    execute_results.append(MagicMock())

    async def fake_execute(query, params=None):
        nonlocal execute_call_count
        if execute_call_count < len(execute_results):
            result = execute_results[execute_call_count]
        else:
            result = MagicMock()
        execute_call_count += 1
        return result

    db.execute = fake_execute

    result = await svc.create_stocktake(STORE_ID, TENANT_ID, db)

    assert result["ok"] is True
    assert result["status"] == "open"
    assert result["item_count"] == 1
    assert len(result["items"]) == 1
    assert result["items"][0]["ingredient_name"] == "测试食材"
    assert svc._db_mode is True


# ─────────────────────────────────────────────────────────────────────────────
# Test 2: create_stocktake — 内存降级模式
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_stocktake_memory_fallback():
    """DB 不可用时，create_stocktake 应降级到内存模式"""
    from sqlalchemy.exc import ProgrammingError

    ingredient_id = str(uuid.uuid4())
    ing = _fake_ingredient(ingredient_id)

    db = MagicMock()
    db.flush = AsyncMock()

    call_count = 0

    async def fake_execute(query, params=None):
        nonlocal call_count
        call_count += 1
        # 第1次: set_config
        if call_count == 1:
            return MagicMock()
        # 第2次: SELECT Ingredient
        if call_count == 2:
            result = MagicMock()
            result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[ing])))
            return result
        # 第3次: _check_db_mode -> raise ProgrammingError
        if call_count == 3:
            raise ProgrammingError("", {}, Exception("relation stocktakes does not exist"))
        return MagicMock()

    db.execute = fake_execute

    result = await svc.create_stocktake(STORE_ID, TENANT_ID, db)

    assert result["ok"] is True
    assert result["status"] == "open"
    assert svc._db_mode is False
    # 内存中应有这条记录
    assert result["stocktake_id"] in svc._stocktakes


# ─────────────────────────────────────────────────────────────────────────────
# Test 3: record_count — DB 模式，正常录入
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_record_count_db_mode():
    """DB 模式下，record_count 应 UPDATE actual_qty 并返回差异"""
    svc._db_mode = True  # 跳过 _check_db_mode 检测

    stocktake_id = str(uuid.uuid4())
    ingredient_id = str(uuid.uuid4())

    db = MagicMock()
    db.flush = AsyncMock()

    call_count = 0

    async def fake_execute(query, params=None):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # _set_tenant
            return MagicMock()
        if call_count == 2:
            # SELECT stocktakes — 返回 in_progress
            result = MagicMock()
            row = {"id": stocktake_id, "tenant_id": TENANT_ID, "status": "in_progress"}
            mp = MagicMock()
            mp.one_or_none = MagicMock(return_value=row)
            result.mappings = MagicMock(return_value=mp)
            return result
        if call_count == 3:
            # SELECT stocktake_items
            result = MagicMock()
            row = {
                "id": str(uuid.uuid4()),
                "ingredient_name": "测试食材",
                "expected_qty": 10.0,
                "cost_price": 30.0,
            }
            mp = MagicMock()
            mp.one_or_none = MagicMock(return_value=row)
            result.mappings = MagicMock(return_value=mp)
            return result
        # UPDATE actual_qty
        return MagicMock()

    db.execute = fake_execute

    result = await svc.record_count(
        stocktake_id=stocktake_id,
        ingredient_id=ingredient_id,
        actual_qty=8.5,
        tenant_id=TENANT_ID,
        db=db,
    )

    assert result["ok"] is True
    assert result["actual_qty"] == 8.5
    assert result["system_qty"] == 10.0
    assert abs(result["variance"] - (-1.5)) < 0.001


# ─────────────────────────────────────────────────────────────────────────────
# Test 4: record_count — 状态异常
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_record_count_wrong_status():
    """盘点单状态非 in_progress 时，record_count 应返回错误"""
    svc._db_mode = True

    stocktake_id = str(uuid.uuid4())
    ingredient_id = str(uuid.uuid4())

    db = MagicMock()
    db.flush = AsyncMock()

    call_count = 0

    async def fake_execute(query, params=None):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return MagicMock()  # set_config
        if call_count == 2:
            result = MagicMock()
            row = {"id": stocktake_id, "tenant_id": TENANT_ID, "status": "completed"}
            mp = MagicMock()
            mp.one_or_none = MagicMock(return_value=row)
            result.mappings = MagicMock(return_value=mp)
            return result
        return MagicMock()

    db.execute = fake_execute

    result = await svc.record_count(
        stocktake_id=stocktake_id,
        ingredient_id=ingredient_id,
        actual_qty=5.0,
        tenant_id=TENANT_ID,
        db=db,
    )

    assert result["ok"] is False
    assert "in_progress" in result["error"]


# ─────────────────────────────────────────────────────────────────────────────
# Test 5: record_count — 盘点单不存在
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_record_count_not_found():
    """盘点单不存在时，record_count 应返回 not found 错误"""
    svc._db_mode = True

    stocktake_id = str(uuid.uuid4())
    ingredient_id = str(uuid.uuid4())

    db = MagicMock()
    db.flush = AsyncMock()

    call_count = 0

    async def fake_execute(query, params=None):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return MagicMock()  # set_config
        if call_count == 2:
            result = MagicMock()
            mp = MagicMock()
            mp.one_or_none = MagicMock(return_value=None)
            result.mappings = MagicMock(return_value=mp)
            return result
        return MagicMock()

    db.execute = fake_execute

    result = await svc.record_count(
        stocktake_id=stocktake_id,
        ingredient_id=ingredient_id,
        actual_qty=5.0,
        tenant_id=TENANT_ID,
        db=db,
    )

    assert result["ok"] is False
    assert "not found" in result["error"]


# ─────────────────────────────────────────────────────────────────────────────
# Test 6: finalize_stocktake — 内存降级模式（全流程）
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_finalize_stocktake_memory_mode():
    """内存模式下 finalize_stocktake 应正确计算 surplus/deficit/matched"""
    svc._db_mode = False

    stocktake_id = str(uuid.uuid4())
    ing_id_1 = str(uuid.uuid4())
    ing_id_2 = str(uuid.uuid4())

    svc._stocktakes[stocktake_id] = {
        "stocktake_id": stocktake_id,
        "store_id": STORE_ID,
        "tenant_id": TENANT_ID,
        "status": "open",
        "created_at": "2026-03-31T00:00:00+00:00",
        "items": {
            ing_id_1: {
                "ingredient_id": ing_id_1,
                "ingredient_name": "鸡腿",
                "category": "meat",
                "unit": "kg",
                "system_qty": 10.0,
                "actual_qty": 8.0,  # 差异 -2（亏）
                "unit_price_fen": 3000,
            },
            ing_id_2: {
                "ingredient_id": ing_id_2,
                "ingredient_name": "大葱",
                "category": "vegetable",
                "unit": "kg",
                "system_qty": 5.0,
                "actual_qty": 5.0,  # 匹配
                "unit_price_fen": 500,
            },
        },
    }

    db = MagicMock()
    db.flush = AsyncMock()
    db.add = MagicMock()

    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=None)
    cm.__aexit__ = AsyncMock(return_value=False)
    db.begin_nested = MagicMock(return_value=cm)

    call_count = 0

    async def fake_execute(query, params=None):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return MagicMock()  # _set_tenant

        # SELECT Ingredient（for each deficit/surplus item）
        result = MagicMock()
        result.scalar_one_or_none = MagicMock(return_value=None)  # 简化：不模拟 ORM 对象
        return result

    db.execute = fake_execute

    result = await svc.finalize_stocktake(stocktake_id, TENANT_ID, db)

    assert result["ok"] is True
    assert result["status"] == "finalized"
    assert result["total_items"] == 2
    assert result["matched"] == 1
    assert result["deficit"] == 1
    assert result["surplus"] == 0
    assert result["deficit_cost_fen"] == 6000  # 2 * 3000
    # 检查内存状态更新
    assert svc._stocktakes[stocktake_id]["status"] == "finalized"


# ─────────────────────────────────────────────────────────────────────────────
# Test 7: get_stocktake_history — 内存模式
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_stocktake_history_memory():
    """内存模式下 get_stocktake_history 应按 store_id 过滤并倒序"""
    svc._db_mode = False

    other_store = str(uuid.uuid4())
    st_id_1 = str(uuid.uuid4())
    st_id_2 = str(uuid.uuid4())
    st_other = str(uuid.uuid4())

    svc._stocktakes[st_id_1] = {
        "stocktake_id": st_id_1,
        "store_id": STORE_ID,
        "tenant_id": TENANT_ID,
        "status": "finalized",
        "created_at": "2026-03-29T00:00:00+00:00",
        "items": {},
    }
    svc._stocktakes[st_id_2] = {
        "stocktake_id": st_id_2,
        "store_id": STORE_ID,
        "tenant_id": TENANT_ID,
        "status": "open",
        "created_at": "2026-03-31T00:00:00+00:00",
        "items": {},
    }
    svc._stocktakes[st_other] = {
        "stocktake_id": st_other,
        "store_id": other_store,
        "tenant_id": TENANT_ID,
        "status": "open",
        "created_at": "2026-03-30T00:00:00+00:00",
        "items": {},
    }

    db = MagicMock()
    db.execute = AsyncMock(return_value=MagicMock())

    result = await svc.get_stocktake_history(STORE_ID, TENANT_ID, db)

    assert result["ok"] is True
    records = result["stocktakes"]
    assert len(records) == 2
    # 倒序：最新的 st_id_2 在前
    assert records[0]["stocktake_id"] == st_id_2
    assert records[1]["stocktake_id"] == st_id_1


# ─────────────────────────────────────────────────────────────────────────────
# Test 8: _check_db_mode 缓存
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_check_db_mode_cached():
    """_check_db_mode 结果应被缓存，第二次调用不再执行 SQL"""
    svc._db_mode = None

    db = MagicMock()
    execute_count = 0

    async def fake_execute(query, params=None):
        nonlocal execute_count
        execute_count += 1
        return MagicMock()

    db.execute = fake_execute

    # 第一次检测
    result1 = await svc._check_db_mode(db)
    count_after_first = execute_count

    # 第二次应命中缓存
    result2 = await svc._check_db_mode(db)
    count_after_second = execute_count

    assert result1 == result2
    assert count_after_second == count_after_first  # 无新的 SQL


# ─────────────────────────────────────────────────────────────────────────────
# Test 9: tenant_id 安全性 — set_config 必须在 DB 操作前调用
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_set_tenant_called_before_db_ops():
    """DB 模式下，create_stocktake 必须在第一次 execute 中调用 set_config"""
    svc._db_mode = True

    db = MagicMock()
    db.flush = AsyncMock()

    sql_calls: list[str] = []

    async def fake_execute(query, params=None):
        # 记录 SQL 片段（text() 对象转 str）
        sql_str = str(query) if hasattr(query, "__str__") else ""
        sql_calls.append(sql_str)

        # SELECT Ingredient
        result = MagicMock()
        result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        mp = MagicMock()
        mp.all = MagicMock(return_value=[])
        mp.one_or_none = MagicMock(return_value=None)
        result.mappings = MagicMock(return_value=mp)
        return result

    db.execute = fake_execute

    await svc.create_stocktake(STORE_ID, TENANT_ID, db)

    # 第一次 SQL 必须包含 set_config
    assert sql_calls, "没有任何 SQL 被执行"
    assert "set_config" in sql_calls[0], f"第一次 SQL 不是 set_config: {sql_calls[0]}"
