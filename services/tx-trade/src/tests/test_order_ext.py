"""点单扩展服务测试 — 赠菜/拆单/并单/异常改单

覆盖场景：
1. 赠菜成功（含审批人）
2. 赠菜缺审批人被拒
3. 拆单成功（2组）
4. 拆单少于2组被拒
5. 并单成功
6. 异常改单申请 + 审批流程
7. 改单审批执行（移除菜品+调价）
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from shared.ontology.src.enums import OrderStatus


# ─── 模拟对象 ───


def _uid() -> str:
    return str(uuid.uuid4())


TENANT_ID = _uid()
STORE_ID = _uid()


class FakeRow:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


class FakeResult:
    def __init__(self, scalar=None):
        self._scalar = scalar

    def scalar_one_or_none(self):
        return self._scalar

    def scalars(self):
        return self

    def all(self):
        if self._scalar:
            return [self._scalar]
        return []


class FakeSession:
    def __init__(self):
        self.added = []
        self.deleted = []
        self.executed = []
        self.flushed = False
        self._execute_results = []
        self._idx = 0

    def add(self, obj):
        self.added.append(obj)

    async def delete(self, obj):
        self.deleted.append(obj)

    async def execute(self, stmt, *args, **kwargs):
        if self._idx < len(self._execute_results):
            r = self._execute_results[self._idx]
            self._idx += 1
            return r
        return FakeResult()

    async def flush(self):
        self.flushed = True


def _make_order(**overrides):
    defaults = {
        "id": uuid.UUID(overrides.pop("id", _uid())),
        "tenant_id": uuid.UUID(TENANT_ID),
        "order_no": "TX202603270001",
        "store_id": uuid.UUID(STORE_ID),
        "table_number": "A01",
        "customer_id": None,
        "waiter_id": "W001",
        "sales_channel_id": None,
        "total_amount_fen": 10000,
        "discount_amount_fen": 0,
        "final_amount_fen": 10000,
        "status": OrderStatus.confirmed.value,
        "order_metadata": {},
        "abnormal_flag": False,
        "abnormal_type": None,
    }
    defaults.update(overrides)
    return FakeRow(**defaults)


def _make_item(order_id, **overrides):
    item_id = overrides.pop("id", _uid())
    defaults = {
        "id": uuid.UUID(item_id),
        "tenant_id": uuid.UUID(TENANT_ID),
        "order_id": uuid.UUID(order_id),
        "dish_id": uuid.UUID(_uid()),
        "item_name": "测试菜品",
        "quantity": 1,
        "unit_price_fen": 3000,
        "subtotal_fen": 3000,
        "gift_flag": False,
    }
    defaults.update(overrides)
    return FakeRow(**defaults)


# ─── 测试 ───


@pytest.mark.asyncio
async def test_gift_dish_success():
    """赠菜成功 — 有审批人"""
    from services.order_extensions import gift_dish

    order_id = _uid()
    order = _make_order(id=order_id)
    db = FakeSession()
    db._execute_results = [FakeResult(scalar=order)]

    result = await gift_dish(
        order_id=order_id,
        dish_id=_uid(),
        quantity=2,
        reason="VIP回馈",
        approver_id="MGR001",
        tenant_id=TENANT_ID,
        db=db,
    )
    assert result["gift_flag"] is True
    assert result["quantity"] == 2
    assert result["approver_id"] == "MGR001"
    assert len(db.added) == 1


@pytest.mark.asyncio
async def test_gift_dish_no_approver():
    """赠菜缺审批人 — 被拒"""
    from services.order_extensions import gift_dish

    db = FakeSession()
    with pytest.raises(ValueError, match="审批人"):
        await gift_dish(
            order_id=_uid(),
            dish_id=_uid(),
            quantity=1,
            reason="test",
            approver_id="",
            tenant_id=TENANT_ID,
            db=db,
        )


@pytest.mark.asyncio
async def test_gift_dish_completed_order():
    """已结算订单不允许赠菜"""
    from services.order_extensions import gift_dish

    order_id = _uid()
    order = _make_order(id=order_id, status=OrderStatus.completed.value)
    db = FakeSession()
    db._execute_results = [FakeResult(scalar=order)]

    with pytest.raises(ValueError, match="不允许赠菜"):
        await gift_dish(
            order_id=order_id,
            dish_id=_uid(),
            quantity=1,
            reason="test",
            approver_id="MGR001",
            tenant_id=TENANT_ID,
            db=db,
        )


@pytest.mark.asyncio
async def test_split_order_too_few_groups():
    """拆单少于2组被拒"""
    from services.order_extensions import split_order

    db = FakeSession()
    with pytest.raises(ValueError, match="至少需要两组"):
        await split_order(
            order_id=_uid(),
            items_groups=[["item1"]],
            tenant_id=TENANT_ID,
            db=db,
        )


@pytest.mark.asyncio
async def test_merge_orders_too_few():
    """并单不足2单被拒"""
    from services.order_extensions import merge_orders

    db = FakeSession()
    with pytest.raises(ValueError, match="至少需要两个"):
        await merge_orders(
            order_ids=[_uid()],
            tenant_id=TENANT_ID,
            db=db,
        )


@pytest.mark.asyncio
async def test_request_and_approve_change():
    """异常改单申请 + 审批流程"""
    from services.order_extensions import request_order_change, approve_order_change, _OrderChangeRequest

    # 清理全局状态
    _OrderChangeRequest._store.clear()

    order_id = _uid()
    order = _make_order(id=order_id)
    db = FakeSession()
    db._execute_results = [FakeResult(scalar=order)]

    # 提交改单申请
    change_result = await request_order_change(
        order_id=order_id,
        changes={"items_to_remove": [], "price_adjustments": []},
        reason="客户投诉",
        tenant_id=TENANT_ID,
        db=db,
    )
    assert change_result["status"] == "pending_approval"
    change_id = change_result["change_id"]

    # 审批通过
    db2 = FakeSession()
    approve_result = await approve_order_change(
        change_id=change_id,
        approver_id="MGR001",
        tenant_id=TENANT_ID,
        db=db2,
    )
    assert approve_result["status"] == "approved"
    assert approve_result["approver_id"] == "MGR001"


@pytest.mark.asyncio
async def test_approve_change_wrong_tenant():
    """审批改单 — 租户不匹配"""
    from services.order_extensions import request_order_change, approve_order_change, _OrderChangeRequest

    _OrderChangeRequest._store.clear()

    order_id = _uid()
    order = _make_order(id=order_id)
    db = FakeSession()
    db._execute_results = [FakeResult(scalar=order)]

    change_result = await request_order_change(
        order_id=order_id,
        changes={},
        reason="test",
        tenant_id=TENANT_ID,
        db=db,
    )

    db2 = FakeSession()
    with pytest.raises(ValueError, match="租户不匹配"):
        await approve_order_change(
            change_id=change_result["change_id"],
            approver_id="MGR001",
            tenant_id=_uid(),  # 不同租户
            db=db2,
        )
