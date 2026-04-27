"""外卖管理中心 — 单元测试

覆盖场景：
1. 同步美团订单 — 空结果正常返回
2. 同步饿了么订单 — 空结果正常返回
3. 同步美团订单 — 有订单时正确转换
4. 接单 — 美团接单成功
5. 接单 — 不支持的平台报错
6. 拒单 — 饿了么拒单成功
7. 沽清同步 — 同步到双平台
8. 配送状态更新 — 正常流转
9. 配送状态更新 — 无效状态报错
10. 外卖仪表盘 — 分类统计正确
11. 平台对账 — 正常返回对账结果
12. 菜品上下架 — 美团上架成功
13. 菜品上下架 — 无效操作报错
14. 自动接单规则 — 设置全自动模式
15. 自动接单规则 — 无效模式报错
16. 自动接单 — 全自动模式自动接单
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import uuid
from unittest.mock import AsyncMock

import pytest

# ─── 工具 ───


def _uid() -> str:
    return str(uuid.uuid4())


TENANT_ID = _uid()
STORE_ID = _uid()


# ─── 测试 1: 同步美团订单 — 空结果 ───


@pytest.mark.asyncio
async def test_sync_meituan_orders_empty():
    """验证美团无新订单时返回空列表"""
    from services.takeaway_manager import _meituan_client, sync_meituan_orders

    original = _meituan_client.pull_new_orders
    _meituan_client.pull_new_orders = AsyncMock(return_value=[])

    try:
        result = await sync_meituan_orders(
            store_id=STORE_ID,
            tenant_id=TENANT_ID,
        )
        assert result["synced_count"] == 0
        assert result["orders"] == []
    finally:
        _meituan_client.pull_new_orders = original


# ─── 测试 2: 同步饿了么订单 — 空结果 ───


@pytest.mark.asyncio
async def test_sync_eleme_orders_empty():
    """验证饿了么无新订单时返回空列表"""
    from services.takeaway_manager import _eleme_client, sync_eleme_orders

    original = _eleme_client.pull_new_orders
    _eleme_client.pull_new_orders = AsyncMock(return_value=[])

    try:
        result = await sync_eleme_orders(
            store_id=STORE_ID,
            tenant_id=TENANT_ID,
        )
        assert result["synced_count"] == 0
        assert result["orders"] == []
    finally:
        _eleme_client.pull_new_orders = original


# ─── 测试 3: 同步美团订单 — 有订单 ───


@pytest.mark.asyncio
async def test_sync_meituan_orders_with_data():
    """验证美团有新订单时正确转换状态和字段"""
    from services.takeaway_manager import _meituan_client, sync_meituan_orders

    mock_orders = [
        {
            "order_id": "MT20260327001",
            "status": 1,
            "order_total_price": 5800,
            "recipient_phone": "138****1234",
            "recipient_address": "长沙市岳麓区xxx",
            "delivery_time": "2026-03-27T12:00:00",
            "caution": "少辣",
            "detail": [{"food_name": "剁椒鱼头", "quantity": 1, "price": 5800}],
        }
    ]
    original = _meituan_client.pull_new_orders
    _meituan_client.pull_new_orders = AsyncMock(return_value=mock_orders)

    # 确保不自动接单
    from services.takeaway_manager import _auto_accept_rules

    _auto_accept_rules.clear()

    try:
        result = await sync_meituan_orders(
            store_id=STORE_ID,
            tenant_id=TENANT_ID,
        )
        assert result["synced_count"] == 1
        order = result["orders"][0]
        assert order["platform"] == "meituan"
        assert order["platform_order_id"] == "MT20260327001"
        assert order["status"] == "pending"
        assert order["total_fen"] == 5800
        assert order["notes"] == "少辣"
    finally:
        _meituan_client.pull_new_orders = original


# ─── 测试 4: 接单 — 美团成功 ───


@pytest.mark.asyncio
async def test_accept_order_meituan():
    """验证美团接单调用成功"""
    from services.takeaway_manager import _meituan_client, accept_order

    original = _meituan_client.confirm_order
    _meituan_client.confirm_order = AsyncMock(return_value={"code": "ok", "order_id": "MT001"})

    try:
        result = await accept_order(
            platform="meituan",
            order_id="MT001",
            tenant_id=TENANT_ID,
        )
        assert result["status"] == "confirmed"
        assert result["platform"] == "meituan"
        assert result["order_id"] == "MT001"
        _meituan_client.confirm_order.assert_awaited_once_with("MT001")
    finally:
        _meituan_client.confirm_order = original


# ─── 测试 5: 接单 — 不支持的平台 ───


@pytest.mark.asyncio
async def test_accept_order_invalid_platform():
    """验证不支持的平台报 ValueError"""
    from services.takeaway_manager import accept_order

    with pytest.raises(ValueError, match="不支持的平台"):
        await accept_order(
            platform="douyin",
            order_id="DY001",
            tenant_id=TENANT_ID,
        )


# ─── 测试 6: 拒单 — 饿了么成功 ───


@pytest.mark.asyncio
async def test_reject_order_eleme():
    """验证饿了么拒单调用成功"""
    from services.takeaway_manager import _eleme_client, reject_order

    original = _eleme_client.cancel_order
    _eleme_client.cancel_order = AsyncMock(return_value={"code": "ok", "order_id": "EL001"})

    try:
        result = await reject_order(
            platform="eleme",
            order_id="EL001",
            reason="门店已打烊",
            tenant_id=TENANT_ID,
        )
        assert result["status"] == "cancelled"
        assert result["reason"] == "门店已打烊"
        assert result["platform"] == "eleme"
        _eleme_client.cancel_order.assert_awaited_once_with("EL001", 1, "门店已打烊")
    finally:
        _eleme_client.cancel_order = original


# ─── 测试 7: 沽清同步 — 双平台 ───


@pytest.mark.asyncio
async def test_sync_stockout_to_both_platforms():
    """验证沽清同步到美团+饿了么"""
    from services.takeaway_manager import (
        _eleme_client,
        _meituan_client,
        sync_stockout_to_platforms,
    )

    orig_mt = _meituan_client.sold_out_food
    orig_el = _eleme_client.sold_out_food
    _meituan_client.sold_out_food = AsyncMock(return_value={"code": "ok"})
    _eleme_client.sold_out_food = AsyncMock(return_value={"code": "ok"})

    try:
        result = await sync_stockout_to_platforms(
            store_id=STORE_ID,
            sold_out_ids=["FOOD_001", "FOOD_002"],
            tenant_id=TENANT_ID,
        )
        # 2 个菜品 x 2 个平台 = 4 次同步
        assert result["total_count"] == 4
        assert result["synced_count"] == 4
        assert all(r["status"] == "synced" for r in result["results"])
    finally:
        _meituan_client.sold_out_food = orig_mt
        _eleme_client.sold_out_food = orig_el


# ─── 测试 8: 配送状态更新 — 正常 ───


@pytest.mark.asyncio
async def test_update_delivery_status_ok():
    """验证配送状态正常流转"""
    from services.takeaway_manager import update_delivery_status

    result = await update_delivery_status(
        order_id=_uid(),
        status="delivering",
        tenant_id=TENANT_ID,
    )
    assert result["status"] == "delivering"
    assert "updated_at" in result


# ─── 测试 9: 配送状态更新 — 无效状态 ───


@pytest.mark.asyncio
async def test_update_delivery_status_invalid():
    """验证无效状态报 ValueError"""
    from services.takeaway_manager import update_delivery_status

    with pytest.raises(ValueError, match="无效状态"):
        await update_delivery_status(
            order_id=_uid(),
            status="flying",
            tenant_id=TENANT_ID,
        )


# ─── 测试 10: 外卖仪表盘 ───


@pytest.mark.asyncio
async def test_takeaway_dashboard():
    """验证仪表盘分类统计正确"""
    from services.takeaway_manager import (
        _orders_store,
        _save_order,
        get_takeaway_dashboard,
    )

    tid = _uid()
    sid = _uid()
    # 清理
    _orders_store.pop(tid, None)

    # 插入测试订单
    _save_order(tid, sid, {"order_id": _uid(), "platform": "meituan", "status": "pending"})
    _save_order(tid, sid, {"order_id": _uid(), "platform": "meituan", "status": "preparing"})
    _save_order(tid, sid, {"order_id": _uid(), "platform": "eleme", "status": "delivering"})
    _save_order(tid, sid, {"order_id": _uid(), "platform": "eleme", "status": "completed"})
    _save_order(tid, sid, {"order_id": _uid(), "platform": "meituan", "status": "completed"})

    result = await get_takeaway_dashboard(store_id=sid, tenant_id=tid)

    assert result["pending_count"] == 1
    assert result["preparing_count"] == 1
    assert result["delivering_count"] == 1
    assert result["completed_count"] == 2
    assert result["total"] == 5
    assert result["orders_by_platform"]["meituan"] == 3
    assert result["orders_by_platform"]["eleme"] == 2


# ─── 测试 11: 平台对账 ───


@pytest.mark.asyncio
async def test_platform_reconciliation():
    """验证平台对账正常返回"""
    from services.takeaway_manager import (
        _meituan_client,
        get_platform_reconciliation,
    )

    original = _meituan_client.get_bill
    _meituan_client.get_bill = AsyncMock(
        return_value={
            "total_fen": 10000,
            "commission_fen": 1800,
            "orders": [],
        }
    )

    try:
        result = await get_platform_reconciliation(
            store_id=STORE_ID,
            platform="meituan",
            date="2026-03-27",
            tenant_id=TENANT_ID,
        )
        assert result["platform"] == "meituan"
        assert result["date"] == "2026-03-27"
        assert result["platform_total_fen"] == 10000
        assert result["platform_commission_fen"] == 1800
        assert "diff_fen" in result
    finally:
        _meituan_client.get_bill = original


# ─── 测试 12: 菜品上下架 — 美团上架 ───


@pytest.mark.asyncio
async def test_manage_menu_on_sale():
    """验证美团菜品上架成功"""
    from services.takeaway_manager import _meituan_client, manage_online_menu

    original = _meituan_client.on_sale_food
    _meituan_client.on_sale_food = AsyncMock(return_value={"code": "ok"})

    try:
        result = await manage_online_menu(
            store_id=STORE_ID,
            platform="meituan",
            actions=[{"food_id": "FOOD_001", "action": "on_sale"}],
            tenant_id=TENANT_ID,
        )
        assert result["success_count"] == 1
        assert result["results"][0]["status"] == "success"
    finally:
        _meituan_client.on_sale_food = original


# ─── 测试 13: 菜品上下架 — 无效操作 ───


@pytest.mark.asyncio
async def test_manage_menu_invalid_action():
    """验证无效操作被标记为 failed"""
    from services.takeaway_manager import manage_online_menu

    result = await manage_online_menu(
        store_id=STORE_ID,
        platform="meituan",
        actions=[{"food_id": "FOOD_001", "action": "delete"}],
        tenant_id=TENANT_ID,
    )
    assert result["success_count"] == 0
    assert result["results"][0]["status"] == "failed"


# ─── 测试 14: 自动接单规则 — 全自动 ───


@pytest.mark.asyncio
async def test_set_auto_accept_rules_all():
    """验证设置全自动接单模式"""
    from services.takeaway_manager import _auto_accept_rules, set_auto_accept_rules

    _auto_accept_rules.clear()

    result = await set_auto_accept_rules(
        store_id=STORE_ID,
        rules={"mode": "all"},
        tenant_id=TENANT_ID,
    )
    assert result["rules"]["mode"] == "all"
    assert "updated_at" in result


# ─── 测试 15: 自动接单规则 — 无效模式 ───


@pytest.mark.asyncio
async def test_set_auto_accept_rules_invalid_mode():
    """验证无效模式报 ValueError"""
    from services.takeaway_manager import set_auto_accept_rules

    with pytest.raises(ValueError, match="无效的自动接单模式"):
        await set_auto_accept_rules(
            store_id=STORE_ID,
            rules={"mode": "night_only"},
            tenant_id=TENANT_ID,
        )


# ─── 测试 16: 自动接单 — 全自动模式 ───


@pytest.mark.asyncio
async def test_auto_accept_all_mode():
    """验证全自动模式下订单自动接单"""
    from services.takeaway_manager import (
        _auto_accept_rules,
        _meituan_client,
        set_auto_accept_rules,
        sync_meituan_orders,
    )

    _auto_accept_rules.clear()

    # 先设置全自动规则
    await set_auto_accept_rules(
        store_id=STORE_ID,
        rules={"mode": "all"},
        tenant_id=TENANT_ID,
    )

    # Mock 拉取订单和接单
    orig_pull = _meituan_client.pull_new_orders
    orig_confirm = _meituan_client.confirm_order
    _meituan_client.pull_new_orders = AsyncMock(
        return_value=[
            {
                "order_id": "MT_AUTO_001",
                "status": 1,
                "order_total_price": 3200,
                "recipient_phone": "139****5678",
                "recipient_address": "长沙市天心区xxx",
                "delivery_time": "",
                "caution": "",
                "detail": [],
            }
        ]
    )
    _meituan_client.confirm_order = AsyncMock(return_value={"code": "ok", "order_id": "MT_AUTO_001"})

    try:
        result = await sync_meituan_orders(
            store_id=STORE_ID,
            tenant_id=TENANT_ID,
        )
        assert result["synced_count"] == 1
        order = result["orders"][0]
        assert order["status"] == "confirmed"
        assert order.get("auto_accepted") is True
    finally:
        _meituan_client.pull_new_orders = orig_pull
        _meituan_client.confirm_order = orig_confirm
