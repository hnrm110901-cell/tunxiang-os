"""KDS 出餐调度中心 — 单元测试

覆盖场景：
1. 分单引擎 — 菜品分配到正确档口
2. 分单引擎 — 未映射菜品归入默认档口
3. 出餐排序 — VIP优先
4. 出餐排序 — 催菜标记最高优先
5. KDS操作 — 开始制作状态流转
6. KDS操作 — 完成出品状态流转
7. KDS操作 — 重做重置状态
8. 超时预警 — 超时分级判定
9. KDS操作 — 缺料上报
10. KDS操作 — 任务时间线完整性
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

# ─── 工具 ───

def _uid() -> str:
    return str(uuid.uuid4())


TENANT_ID = _uid()
STORE_ID = _uid()
DEPT_HOT = _uid()
DEPT_COLD = _uid()
DISH_KUNG_PAO = _uid()
DISH_SALAD = _uid()
DISH_UNKNOWN = _uid()


class FakeRow:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


class FakeResult:
    def __init__(self, rows=None, scalar=None):
        self._rows = rows or []
        self._scalar = scalar

    def scalar_one_or_none(self):
        return self._scalar

    def scalar(self):
        return self._scalar

    def scalars(self):
        return self

    def all(self):
        return self._rows


def _make_mock_db(execute_results=None):
    db = AsyncMock()
    if execute_results:
        db.execute = AsyncMock(side_effect=execute_results)
    else:
        db.execute = AsyncMock(return_value=FakeResult())
    return db


# ─── 测试 1: 分单 — 菜品分配到正确档口 ───

@pytest.mark.asyncio
async def test_dispatch_order_maps_dishes_to_depts():
    """验证菜品根据 dish_dept_mappings 分配到正确的档口"""
    from services.kds_dispatch import dispatch_order_to_kds

    dept_hot_uuid = uuid.UUID(DEPT_HOT)
    dish_kp_uuid = uuid.UUID(DISH_KUNG_PAO)

    # Mock: 第一次查询返回映射，第二次返回档口信息
    mapping_result = FakeResult(rows=[(dish_kp_uuid, dept_hot_uuid)])
    dept_obj = FakeRow(
        id=dept_hot_uuid, dept_name="热菜间", dept_code="HOT",
        sort_order=1, tenant_id=uuid.UUID(TENANT_ID), is_deleted=False,
    )
    dept_result = FakeResult(rows=[dept_obj])

    db = _make_mock_db([mapping_result, dept_result])

    items = [{"dish_id": DISH_KUNG_PAO, "item_name": "宫保鸡丁", "quantity": 2, "order_item_id": _uid()}]
    result = await dispatch_order_to_kds(_uid(), items, TENANT_ID, db)

    assert "dept_tasks" in result
    assert len(result["dept_tasks"]) == 1
    assert result["dept_tasks"][0]["dept_name"] == "热菜间"
    assert result["dept_tasks"][0]["items"][0]["dish_name"] == "宫保鸡丁"
    assert result["dept_tasks"][0]["items"][0]["quantity"] == 2


# ─── 测试 2: 分单 — 未映射菜品归入默认档口 ───

@pytest.mark.asyncio
async def test_dispatch_unmapped_dish_goes_to_default():
    """未在 dish_dept_mappings 中配置的菜品应归入默认档口"""
    from services.kds_dispatch import dispatch_order_to_kds

    # Mock: 映射查询返回空，档口查询也空
    db = _make_mock_db([FakeResult(rows=[]), FakeResult(rows=[])])

    items = [{"dish_id": DISH_UNKNOWN, "item_name": "神秘菜品", "quantity": 1}]
    result = await dispatch_order_to_kds(_uid(), items, TENANT_ID, db)

    assert len(result["dept_tasks"]) == 1
    assert result["dept_tasks"][0]["dept_id"] == "default"
    assert result["dept_tasks"][0]["dept_name"] == "默认档口"


# ─── 测试 3: 出餐排序 — VIP优先 ───

@pytest.mark.asyncio
async def test_cooking_order_vip_first():
    """VIP 订单应排在普通订单前面"""
    from services.cooking_scheduler import calculate_cooking_order

    db = AsyncMock()
    now = datetime.now(timezone.utc).isoformat()

    dept_tasks = [{
        "dept_id": DEPT_HOT,
        "dept_name": "热菜间",
        "items": [
            {"task_id": _uid(), "dish_name": "普通菜A", "is_vip": False, "urgent": False, "created_at": now},
            {"task_id": _uid(), "dish_name": "VIP菜B", "is_vip": True, "urgent": False, "created_at": now},
        ],
        "priority": 1,
    }]

    result = await calculate_cooking_order(dept_tasks, db)
    items = result[0]["items"]
    assert items[0]["dish_name"] == "VIP菜B"
    assert items[1]["dish_name"] == "普通菜A"


# ─── 测试 4: 出餐排序 — 催菜最高优先 ───

@pytest.mark.asyncio
async def test_cooking_order_urgent_highest():
    """催菜标记的任务应排在最前面，优先于 VIP"""
    from services.cooking_scheduler import calculate_cooking_order

    db = AsyncMock()
    now = datetime.now(timezone.utc).isoformat()

    dept_tasks = [{
        "dept_id": DEPT_HOT,
        "dept_name": "热菜间",
        "items": [
            {"task_id": _uid(), "dish_name": "VIP菜", "is_vip": True, "urgent": False, "created_at": now},
            {"task_id": _uid(), "dish_name": "催菜", "is_vip": False, "urgent": True, "created_at": now},
            {"task_id": _uid(), "dish_name": "普通菜", "is_vip": False, "urgent": False, "created_at": now},
        ],
        "priority": 1,
    }]

    result = await calculate_cooking_order(dept_tasks, db)
    items = result[0]["items"]
    assert items[0]["dish_name"] == "催菜"


# ─── 测试 5: KDS操作 — 开始制作 ───

@pytest.mark.asyncio
async def test_start_cooking_transitions_to_cooking():
    """pending → cooking 状态流转"""
    from services.kds_actions import STATUS_COOKING, STATUS_PENDING, _task_store, start_cooking

    db = AsyncMock()
    task_id = _uid()

    # 确保任务初始为 pending
    _task_store[task_id] = {
        "task_id": task_id, "status": STATUS_PENDING,
        "urgent": False, "remake_count": 0, "timeline": [],
    }

    result = await start_cooking(task_id, "chef_001", db)
    assert result["ok"] is True
    assert result["data"]["status"] == STATUS_COOKING
    assert _task_store[task_id]["operator_id"] == "chef_001"


# ─── 测试 6: KDS操作 — 完成出品 ───

@pytest.mark.asyncio
async def test_finish_cooking_transitions_to_done():
    """cooking → done 状态流转"""
    from services.kds_actions import STATUS_COOKING, STATUS_DONE, _task_store, finish_cooking

    db = AsyncMock()
    task_id = _uid()

    _task_store[task_id] = {
        "task_id": task_id, "status": STATUS_COOKING,
        "urgent": False, "remake_count": 0, "timeline": [],
        "started_at": datetime.now(timezone.utc).isoformat(),
        "operator_id": "chef_001",
    }

    result = await finish_cooking(task_id, "chef_001", db)
    assert result["ok"] is True
    assert result["data"]["status"] == STATUS_DONE
    assert "duration_sec" in result["data"]


# ─── 测试 7: KDS操作 — 重做重置状态 ───

@pytest.mark.asyncio
async def test_remake_resets_to_pending():
    """重做应将状态重置为 pending 并标记 urgent"""
    from services.kds_actions import STATUS_DONE, STATUS_PENDING, _task_store, request_remake

    db = AsyncMock()
    task_id = _uid()

    _task_store[task_id] = {
        "task_id": task_id, "status": STATUS_DONE,
        "urgent": False, "remake_count": 0, "timeline": [],
    }

    result = await request_remake(task_id, "菜品过咸", db)
    assert result["ok"] is True
    assert result["data"]["status"] == STATUS_PENDING
    assert result["data"]["remake_count"] == 1
    assert _task_store[task_id]["urgent"] is True


# ─── 测试 8: 超时预警 — 分级判定 ───

def test_timeout_classification():
    """验证超时分级：normal / warning / critical"""
    from services.cooking_timeout import _classify_timeout_status

    config = {"normal_minutes": 15, "warning_minutes": 20, "critical_minutes": 30}

    assert _classify_timeout_status(10, config) == "normal"
    assert _classify_timeout_status(22, config) == "warning"
    assert _classify_timeout_status(35, config) == "critical"
    # 边界值
    assert _classify_timeout_status(20, config) == "warning"
    assert _classify_timeout_status(30, config) == "critical"


# ─── 测试 9: KDS操作 — 缺料上报 ───

@pytest.mark.asyncio
async def test_report_shortage():
    """缺料上报应记录事件并返回成功"""
    from services.kds_actions import _task_store, report_shortage

    db = AsyncMock()
    task_id = _uid()

    _task_store[task_id] = {
        "task_id": task_id, "status": "cooking",
        "urgent": False, "remake_count": 0, "timeline": [],
    }

    result = await report_shortage(task_id, "ingredient_001", db)
    assert result["ok"] is True
    assert result["data"]["ingredient_id"] == "ingredient_001"
    # 时间线应有记录
    assert len(_task_store[task_id]["timeline"]) == 1
    assert _task_store[task_id]["timeline"][0]["event"] == "shortage"


# ─── 测试 10: KDS操作 — 任务时间线完整性 ───

@pytest.mark.asyncio
async def test_task_timeline_completeness():
    """完整操作流程应产生完整时间线"""
    from services.kds_actions import (
        STATUS_PENDING,
        _task_store,
        finish_cooking,
        get_task_timeline,
        start_cooking,
    )

    db = AsyncMock()
    task_id = _uid()

    _task_store[task_id] = {
        "task_id": task_id, "status": STATUS_PENDING,
        "urgent": False, "remake_count": 0, "timeline": [],
    }

    # pending → cooking → done
    await start_cooking(task_id, "chef_001", db)
    await finish_cooking(task_id, "chef_001", db)

    result = await get_task_timeline(task_id, db)
    assert result["ok"] is True
    timeline = result["data"]["timeline"]
    assert len(timeline) == 2
    assert timeline[0]["event"] == "start_cooking"
    assert timeline[1]["event"] == "finish_cooking"
    assert result["data"]["status"] == "done"
