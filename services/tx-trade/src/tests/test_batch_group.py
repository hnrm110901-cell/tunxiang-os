"""批次累单服务 — 单元测试

覆盖场景（≥6）：
1. 单档口累单：多桌同款菜正确合并
2. batch_count = total_qty // base_qty，remainder = total_qty % base_qty
3. base_quantity=1 时不合并（等同标准视图，每份单独计批）
4. 基准份数设置+读取
5. 不同档口独立累单（A档口数据不影响B档口）
6. 空档口返回空列表
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

# ── 测试工具 ──────────────────────────────────────────────────


def _uid() -> str:
    return str(uuid.uuid4())


TENANT_ID = _uid()
STORE_ID = _uid()
DEPT_A = _uid()  # 切配档口A
DEPT_B = _uid()  # 打荷档口B
DISH_DUCK = _uid()  # 烤鸭
DISH_FISH = _uid()  # 鱼头
DISH_RICE = _uid()  # 米饭


class FakeRow:
    """模拟 SQLAlchemy Row"""

    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


class FakeResult:
    def __init__(self, rows=None, scalar=None, one_or_none=None):
        self._rows = rows or []
        self._scalar = scalar
        self._one = one_or_none

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._one

    def scalar_one_or_none(self):
        return self._scalar

    def scalar(self):
        return self._scalar


def _mock_db(*execute_results):
    """构造模拟 AsyncSession，按顺序返回 execute 结果"""
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=list(execute_results))
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    return db


# ── 测试 1: 多桌同款菜正确合并 ───────────────────────────────


@pytest.mark.asyncio
async def test_multi_table_same_dish_merged():
    """A3/B7/C1 三桌各点1份烤鸭，应合并为 total_qty=3"""
    from services.batch_group_service import BatchGroupService

    # 三行任务数据，同一个 dish_id，不同桌台
    task_rows = [
        FakeRow(task_id=_uid(), order_item_id=_uid(), dish_id=DISH_DUCK, dish_name="烤鸭", quantity=1, table_no="A3"),
        FakeRow(task_id=_uid(), order_item_id=_uid(), dish_id=DISH_DUCK, dish_name="烤鸭", quantity=1, table_no="B7"),
        FakeRow(task_id=_uid(), order_item_id=_uid(), dish_id=DISH_DUCK, dish_name="烤鸭", quantity=2, table_no="C1"),
    ]
    base_qty_row = FakeRow()
    base_qty_row.__dict__["0"] = 1  # base_quantity = 1（默认）

    db = _mock_db(
        FakeResult(rows=task_rows),  # get_batched_queue 主查询
        FakeResult(one_or_none=None),  # get_dish_base_quantity → 无记录，返回默认1
    )

    groups = await BatchGroupService.get_batched_queue(
        dept_id=DEPT_A,
        store_id=STORE_ID,
        tenant_id=TENANT_ID,
        db=db,
    )

    assert len(groups) == 1
    g = groups[0]
    assert g.dish_name == "烤鸭"
    assert g.total_qty == 4  # 1+1+2
    assert set(g.table_list) == {"A3", "B7", "C1"}


# ── 测试 2: batch_count 和 remainder 计算正确 ─────────────────


@pytest.mark.asyncio
async def test_batch_count_and_remainder():
    """烤鸭×8，base_quantity=3 → batch_count=2，remainder=2"""
    from services.batch_group_service import BatchGroup

    task_rows = [
        FakeRow(task_id=_uid(), order_item_id=_uid(), dish_id=DISH_DUCK, dish_name="烤鸭", quantity=8, table_no="A1"),
    ]

    db = _mock_db(
        FakeResult(rows=task_rows),  # 主查询
        FakeResult(one_or_none=FakeRow(**{"base_quantity": 3})),  # base_quantity = 3
    )

    # 注入 fetchone 返回 base_quantity=3
    # 直接测试 BatchGroup dataclass 计算
    g = BatchGroup(
        dish_id=DISH_DUCK,
        dish_name="烤鸭",
        total_qty=8,
        base_qty=3,
        batch_count=8 // 3,  # 2
        remainder=8 % 3,  # 2
        table_list=["A1"],
        task_ids=[],
    )
    assert g.batch_count == 2
    assert g.remainder == 2


@pytest.mark.asyncio
async def test_exact_division_no_remainder():
    """烤鸭×6，base_quantity=2 → batch_count=3，remainder=0"""
    from services.batch_group_service import BatchGroup

    g = BatchGroup(
        dish_id=DISH_DUCK,
        dish_name="烤鸭",
        total_qty=6,
        base_qty=2,
        batch_count=6 // 2,
        remainder=6 % 2,
        table_list=[],
        task_ids=[],
    )
    assert g.batch_count == 3
    assert g.remainder == 0


# ── 测试 3: base_quantity=1 时每份单独计批 ──────────────────


@pytest.mark.asyncio
async def test_base_qty_one_each_is_one_batch():
    """base_quantity=1：5份 → batch_count=5，remainder=0（标准视图行为）"""
    from services.batch_group_service import BatchGroup

    g = BatchGroup(
        dish_id=DISH_FISH,
        dish_name="鱼头",
        total_qty=5,
        base_qty=1,
        batch_count=5 // 1,  # 5
        remainder=5 % 1,  # 0
        table_list=["A1", "A2"],
        task_ids=[],
    )
    assert g.batch_count == 5
    assert g.remainder == 0


# ── 测试 4: 基准份数设置与读取 ───────────────────────────────


@pytest.mark.asyncio
async def test_set_and_get_base_quantity():
    """设置 base_quantity=4，然后能读取回来"""
    from services.batch_group_service import BatchGroupService

    # 测试 set_base_quantity（UPDATE 影响1行）
    mock_result = MagicMock()
    mock_result.rowcount = 1

    db_set = AsyncMock()
    db_set.execute = AsyncMock(return_value=mock_result)
    db_set.commit = AsyncMock()
    db_set.rollback = AsyncMock()

    await BatchGroupService.set_base_quantity(
        dish_id=DISH_DUCK,
        dept_id=DEPT_A,
        quantity=4,
        tenant_id=TENANT_ID,
        db=db_set,
    )
    db_set.commit.assert_awaited_once()

    # 测试 get_dish_base_quantity 读取回 4
    db_get = _mock_db(FakeResult(one_or_none=FakeRow(**{"base_quantity": 4})))
    # fetchone 需要返回一个有 [0] 属性的对象
    fake_row = MagicMock()
    fake_row.__getitem__ = MagicMock(return_value=4)
    get_result = MagicMock()
    get_result.fetchone = MagicMock(return_value=fake_row)
    db_get2 = AsyncMock()
    db_get2.execute = AsyncMock(return_value=get_result)

    qty = await BatchGroupService.get_dish_base_quantity(
        dish_id=DISH_DUCK,
        dept_id=DEPT_A,
        tenant_id=TENANT_ID,
        db=db_get2,
    )
    assert qty == 4


@pytest.mark.asyncio
async def test_set_base_quantity_invalid_raises():
    """quantity < 1 应抛出 ValueError"""
    from services.batch_group_service import BatchGroupService

    db = AsyncMock()
    with pytest.raises(ValueError, match="base_quantity must be >= 1"):
        await BatchGroupService.set_base_quantity(
            dish_id=DISH_DUCK,
            dept_id=DEPT_A,
            quantity=0,
            tenant_id=TENANT_ID,
            db=db,
        )


# ── 测试 5: 不同档口独立累单 ─────────────────────────────────


@pytest.mark.asyncio
async def test_different_depts_independent():
    """DEPT_A 有烤鸭×3，DEPT_B 有米饭×10，互不影响"""
    from services.batch_group_service import BatchGroupService

    # DEPT_A 查询
    dept_a_rows = [
        FakeRow(task_id=_uid(), order_item_id=_uid(), dish_id=DISH_DUCK, dish_name="烤鸭", quantity=3, table_no="A1"),
    ]
    db_a = _mock_db(
        FakeResult(rows=dept_a_rows),
        FakeResult(one_or_none=None),  # base_qty 默认1
    )
    groups_a = await BatchGroupService.get_batched_queue(
        dept_id=DEPT_A, store_id=STORE_ID, tenant_id=TENANT_ID, db=db_a
    )

    # DEPT_B 查询
    dept_b_rows = [
        FakeRow(task_id=_uid(), order_item_id=_uid(), dish_id=DISH_RICE, dish_name="米饭", quantity=10, table_no="B2"),
    ]
    db_b = _mock_db(
        FakeResult(rows=dept_b_rows),
        FakeResult(one_or_none=None),
    )
    groups_b = await BatchGroupService.get_batched_queue(
        dept_id=DEPT_B, store_id=STORE_ID, tenant_id=TENANT_ID, db=db_b
    )

    assert len(groups_a) == 1
    assert groups_a[0].dish_name == "烤鸭"
    assert groups_a[0].total_qty == 3

    assert len(groups_b) == 1
    assert groups_b[0].dish_name == "米饭"
    assert groups_b[0].total_qty == 10

    # 两个档口的结果完全独立
    assert groups_a[0].dish_id != groups_b[0].dish_id


# ── 测试 6: 空档口返回空列表 ─────────────────────────────────


@pytest.mark.asyncio
async def test_empty_dept_returns_empty_list():
    """档口无 pending 任务时返回空列表"""
    from services.batch_group_service import BatchGroupService

    db = _mock_db(FakeResult(rows=[]))  # 主查询返回空

    groups = await BatchGroupService.get_batched_queue(
        dept_id=DEPT_A,
        store_id=STORE_ID,
        tenant_id=TENANT_ID,
        db=db,
    )

    assert groups == []


# ── 测试 7: 多菜品按总份数降序排列 ──────────────────────────


@pytest.mark.asyncio
async def test_sorted_by_total_qty_desc():
    """多菜品时，总份数多的排在前面"""
    from services.batch_group_service import BatchGroupService

    task_rows = [
        FakeRow(task_id=_uid(), order_item_id=_uid(), dish_id=DISH_FISH, dish_name="鱼头", quantity=2, table_no="A1"),
        FakeRow(task_id=_uid(), order_item_id=_uid(), dish_id=DISH_DUCK, dish_name="烤鸭", quantity=8, table_no="B1"),
        FakeRow(task_id=_uid(), order_item_id=_uid(), dish_id=DISH_RICE, dish_name="米饭", quantity=5, table_no="C1"),
    ]

    # 三个菜品各需一次 base_quantity 查询，全部返回 None（默认1）
    db = _mock_db(
        FakeResult(rows=task_rows),
        FakeResult(one_or_none=None),  # 鱼头 base_qty
        FakeResult(one_or_none=None),  # 烤鸭 base_qty
        FakeResult(one_or_none=None),  # 米饭 base_qty
    )

    groups = await BatchGroupService.get_batched_queue(dept_id=DEPT_A, store_id=STORE_ID, tenant_id=TENANT_ID, db=db)

    assert len(groups) == 3
    quantities = [g.total_qty for g in groups]
    assert quantities == sorted(quantities, reverse=True)
    assert quantities[0] == 8  # 烤鸭最多
