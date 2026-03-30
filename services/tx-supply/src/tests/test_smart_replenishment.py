"""智能双规则补货服务测试

覆盖场景：
1. 库存低于 safety_stock 触发补货
2. 库存高于 safety_stock 不触发
3. 补货量 = target_stock - current，按 min_order_qty 取整（向上）
4. dual 规则：高消耗速度提前触发（safety * 1.5）
5. 阈值设置 + 读取（get_thresholds）
6. 自动申购单创建，source 标注正确
7. 无需补货时 auto 返回 skipped=True，items_count=0
8. 租户隔离：不同 tenant_id 只能看到自己的数据
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import math
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ─── 工具 ───

def _uid() -> str:
    return str(uuid.uuid4())


TENANT_A = _uid()
TENANT_B = _uid()
STORE_ID = _uid()
ING_PORK = _uid()
ING_FISH = _uid()


class FakeRow:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


class FakeResult:
    def __init__(self, rows=None, scalar=None):
        self._rows = rows or []
        self._scalar = scalar

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return self._rows

    def scalar_one_or_none(self):
        return self._scalar

    def scalar(self):
        return self._scalar


def _make_db(execute_results=None):
    """创建 AsyncMock DB，execute 按顺序返回结果"""
    db = AsyncMock()
    if execute_results:
        db.execute = AsyncMock(side_effect=execute_results)
    else:
        db.execute = AsyncMock(return_value=FakeResult())
    return db


# ─── 导入服务 ───

from services.smart_replenishment import (
    SmartReplenishmentService,
    InventoryThreshold,
    ReplenishmentItem,
    HIGH_CONSUMPTION_RATIO,
    DUAL_EARLY_TRIGGER_RATIO,
)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  场景 1: 库存低于 safety_stock 触发补货
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@pytest.mark.asyncio
async def test_trigger_when_below_safety_stock():
    """current < safety_stock 应触发补货建议"""
    svc = SmartReplenishmentService()

    # 阈值配置：安全库存 10，目标库存 50
    thresholds = [
        InventoryThreshold(
            tenant_id=TENANT_A,
            store_id=STORE_ID,
            ingredient_id=ING_PORK,
            ingredient_name="猪肉",
            safety_stock=10.0,
            target_stock=50.0,
            min_order_qty=1.0,
            trigger_rule="safety_only",
        )
    ]

    # 当前库存 = 5（低于安全库存 10）
    current_stocks = {ING_PORK: 5.0}

    with patch.object(svc, "get_thresholds", AsyncMock(return_value=thresholds)), \
         patch.object(svc, "_fetch_current_stocks", AsyncMock(return_value=current_stocks)), \
         patch.object(svc, "_fetch_consumption_speed", AsyncMock(return_value=({}, {}))):
        items = await svc.check_and_recommend(STORE_ID, TENANT_A, db=None)

    assert len(items) == 1
    assert items[0].ingredient_id == ING_PORK
    assert items[0].current_stock == 5.0
    assert items[0].safety_stock == 10.0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  场景 2: 库存高于 safety_stock 不触发
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@pytest.mark.asyncio
async def test_no_trigger_when_above_safety_stock():
    """current >= safety_stock 时不返回补货建议"""
    svc = SmartReplenishmentService()

    thresholds = [
        InventoryThreshold(
            tenant_id=TENANT_A,
            store_id=STORE_ID,
            ingredient_id=ING_PORK,
            ingredient_name="猪肉",
            safety_stock=10.0,
            target_stock=50.0,
            min_order_qty=1.0,
            trigger_rule="safety_only",
        )
    ]
    # 库存 = 15，高于安全库存 10
    current_stocks = {ING_PORK: 15.0}

    with patch.object(svc, "get_thresholds", AsyncMock(return_value=thresholds)), \
         patch.object(svc, "_fetch_current_stocks", AsyncMock(return_value=current_stocks)), \
         patch.object(svc, "_fetch_consumption_speed", AsyncMock(return_value=({}, {}))):
        items = await svc.check_and_recommend(STORE_ID, TENANT_A, db=None)

    assert len(items) == 0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  场景 3: 补货量 = target - current，按 min_order_qty 向上取整
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@pytest.mark.asyncio
async def test_recommend_qty_ceiling_by_min_order_qty():
    """补货量按 min_order_qty 向上取整"""
    svc = SmartReplenishmentService()

    # target=50, current=7, raw=43, min_order_qty=5 → ceil(43/5)*5 = 45
    thresholds = [
        InventoryThreshold(
            tenant_id=TENANT_A,
            store_id=STORE_ID,
            ingredient_id=ING_PORK,
            ingredient_name="猪肉",
            safety_stock=10.0,
            target_stock=50.0,
            min_order_qty=5.0,
            trigger_rule="safety_only",
        )
    ]
    current_stocks = {ING_PORK: 7.0}

    with patch.object(svc, "get_thresholds", AsyncMock(return_value=thresholds)), \
         patch.object(svc, "_fetch_current_stocks", AsyncMock(return_value=current_stocks)), \
         patch.object(svc, "_fetch_consumption_speed", AsyncMock(return_value=({}, {}))):
        items = await svc.check_and_recommend(STORE_ID, TENANT_A, db=None)

    assert len(items) == 1
    raw_qty = 50.0 - 7.0  # = 43
    expected = math.ceil(raw_qty / 5.0) * 5.0  # = 45
    assert items[0].recommend_qty == expected


@pytest.mark.asyncio
async def test_recommend_qty_exact_multiple_unchanged():
    """原料缺口恰好是 min_order_qty 的倍数时，补货量不变"""
    svc = SmartReplenishmentService()

    # target=50, current=10, raw=40, min_order_qty=10 → 40
    thresholds = [
        InventoryThreshold(
            tenant_id=TENANT_A,
            store_id=STORE_ID,
            ingredient_id=ING_PORK,
            ingredient_name="猪肉",
            safety_stock=15.0,
            target_stock=50.0,
            min_order_qty=10.0,
            trigger_rule="safety_only",
        )
    ]
    current_stocks = {ING_PORK: 10.0}

    with patch.object(svc, "get_thresholds", AsyncMock(return_value=thresholds)), \
         patch.object(svc, "_fetch_current_stocks", AsyncMock(return_value=current_stocks)), \
         patch.object(svc, "_fetch_consumption_speed", AsyncMock(return_value=({}, {}))):
        items = await svc.check_and_recommend(STORE_ID, TENANT_A, db=None)

    assert items[0].recommend_qty == 40.0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  场景 4: dual 规则 — 高消耗速度提前触发
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@pytest.mark.asyncio
async def test_dual_rule_early_trigger_on_high_consumption():
    """dual 规则下，近7日消耗速度 > avg*1.3 时提前到 safety*1.5 触发

    库存 = 12，safety = 10，safety*1.5 = 15，current < 15 → 触发
    """
    svc = SmartReplenishmentService()

    thresholds = [
        InventoryThreshold(
            tenant_id=TENANT_A,
            store_id=STORE_ID,
            ingredient_id=ING_FISH,
            ingredient_name="三文鱼",
            safety_stock=10.0,
            target_stock=60.0,
            min_order_qty=1.0,
            trigger_rule="dual",
        )
    ]
    current_stocks = {ING_FISH: 12.0}  # 12 < safety*1.5=15 → 提前触发
    # 近7日日均 = 5，历史平均 = 3 → 5 > 3 * 1.3 = 3.9 → 高速消耗
    consumption_map = {ING_FISH: 5.0}
    avg_map = {ING_FISH: 3.0}

    with patch.object(svc, "get_thresholds", AsyncMock(return_value=thresholds)), \
         patch.object(svc, "_fetch_current_stocks", AsyncMock(return_value=current_stocks)), \
         patch.object(svc, "_fetch_consumption_speed", AsyncMock(return_value=(consumption_map, avg_map))):
        items = await svc.check_and_recommend(STORE_ID, TENANT_A, db=None)

    assert len(items) == 1
    assert items[0].ingredient_id == ING_FISH
    assert items[0].trigger_threshold == pytest.approx(10.0 * DUAL_EARLY_TRIGGER_RATIO)


@pytest.mark.asyncio
async def test_dual_rule_no_early_trigger_when_normal_consumption():
    """dual 规则下消耗速度正常，不提前触发（current > safety，不应触发）"""
    svc = SmartReplenishmentService()

    thresholds = [
        InventoryThreshold(
            tenant_id=TENANT_A,
            store_id=STORE_ID,
            ingredient_id=ING_FISH,
            ingredient_name="三文鱼",
            safety_stock=10.0,
            target_stock=60.0,
            min_order_qty=1.0,
            trigger_rule="dual",
        )
    ]
    current_stocks = {ING_FISH: 12.0}  # 12 > safety=10，正常不触发
    # 近7日消耗正常：不超过阈值
    consumption_map = {ING_FISH: 2.0}
    avg_map = {ING_FISH: 2.0}

    with patch.object(svc, "get_thresholds", AsyncMock(return_value=thresholds)), \
         patch.object(svc, "_fetch_current_stocks", AsyncMock(return_value=current_stocks)), \
         patch.object(svc, "_fetch_consumption_speed", AsyncMock(return_value=(consumption_map, avg_map))):
        items = await svc.check_and_recommend(STORE_ID, TENANT_A, db=None)

    assert len(items) == 0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  场景 5: 阈值设置 + 读取
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@pytest.mark.asyncio
async def test_set_and_get_threshold():
    """set_threshold 写入后 get_thresholds 可读取"""
    svc = SmartReplenishmentService()
    threshold_id = str(uuid.uuid4())
    now_dt = datetime.now(timezone.utc)

    # mock set_threshold 的 DB 返回
    upsert_result = FakeResult(
        rows=[FakeRow(id=uuid.UUID(threshold_id), updated_at=now_dt)]
    )
    # mock get_thresholds 的 DB 返回
    select_result = FakeResult(
        rows=[
            FakeRow(
                id=uuid.UUID(threshold_id),
                ingredient_id=uuid.UUID(ING_PORK),
                safety_stock=8.0,
                target_stock=40.0,
                min_order_qty=2.0,
                trigger_rule="dual",
                updated_at=now_dt,
                ingredient_name="猪肉",
            )
        ]
    )

    db = _make_db(execute_results=[
        FakeResult(),           # set_config
        upsert_result,          # INSERT ... ON CONFLICT
        FakeResult(),           # set_config (get_thresholds)
        select_result,          # SELECT
    ])

    threshold = await svc.set_threshold(
        store_id=STORE_ID,
        ingredient_id=ING_PORK,
        safety=8.0,
        target=40.0,
        tenant_id=TENANT_A,
        db=db,
        min_order_qty=2.0,
        trigger_rule="dual",
        ingredient_name="猪肉",
    )
    assert threshold.safety_stock == 8.0
    assert threshold.target_stock == 40.0
    assert threshold.trigger_rule == "dual"

    thresholds = await svc.get_thresholds(STORE_ID, TENANT_A, db=db)
    assert len(thresholds) == 1
    assert thresholds[0].ingredient_id == ING_PORK
    assert thresholds[0].min_order_qty == 2.0


@pytest.mark.asyncio
async def test_set_threshold_validates_target_gte_safety():
    """target_stock < safety_stock 时应抛出 ValueError"""
    svc = SmartReplenishmentService()
    db = _make_db()

    with pytest.raises(ValueError, match="target_stock"):
        await svc.set_threshold(
            store_id=STORE_ID,
            ingredient_id=ING_PORK,
            safety=20.0,
            target=10.0,  # 低于安全库存
            tenant_id=TENANT_A,
            db=db,
        )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  场景 6: 自动申购单创建，source 标注正确
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@pytest.mark.asyncio
async def test_auto_create_requisition_sets_source():
    """auto_create_requisition 成功时 source='smart_replenishment'

    db=None 时走测试/预览路径（生成占位 ID），保证 source 标注正确。
    """
    svc = SmartReplenishmentService()

    need_items = [
        ReplenishmentItem(
            ingredient_id=ING_PORK,
            ingredient_name="猪肉",
            current_stock=3.0,
            safety_stock=10.0,
            target_stock=50.0,
            recommend_qty=47.0,
            urgency="normal",
            trigger_threshold=10.0,
        )
    ]

    with patch.object(svc, "check_and_recommend", AsyncMock(return_value=need_items)):
        result = await svc.auto_create_requisition(STORE_ID, TENANT_A, db=None)

    assert result.source == "smart_replenishment"
    assert result.items_count == 1
    assert result.requisition_id is not None
    assert result.skipped is False


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  场景 7: 无需补货时 auto 返回 skipped=True
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@pytest.mark.asyncio
async def test_auto_skipped_when_no_replenishment_needed():
    """库存充足时 auto_create_requisition 返回 skipped=True，不创建申购单"""
    svc = SmartReplenishmentService()

    with patch.object(svc, "check_and_recommend", AsyncMock(return_value=[])):
        result = await svc.auto_create_requisition(STORE_ID, TENANT_A, db=None)

    assert result.skipped is True
    assert result.items_count == 0
    assert result.requisition_id is None
    assert result.total_items == []


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  场景 8: 租户隔离
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@pytest.mark.asyncio
async def test_tenant_isolation():
    """不同 tenant_id 的查询互不干扰，set_config 携带正确租户 ID"""
    svc = SmartReplenishmentService()
    executed_params = []

    async def _capture_execute(stmt, params=None, **kwargs):
        if params:
            executed_params.append(dict(params))
        return FakeResult()

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=_capture_execute)

    await svc.get_thresholds(STORE_ID, TENANT_B, db=db)

    # 第一次调用是 set_config，应带 TENANT_B
    assert any(
        p.get("tid") == TENANT_B
        for p in executed_params
    ), "set_config 应传入 TENANT_B"
    # 不应出现 TENANT_A
    assert not any(
        p.get("tenant_id") == TENANT_A
        for p in executed_params
    ), "不应查询 TENANT_A 的数据"


@pytest.mark.asyncio
async def test_urgency_is_urgent_when_below_half_safety():
    """current < safety * 0.5 时，urgency 应为 urgent"""
    svc = SmartReplenishmentService()

    thresholds = [
        InventoryThreshold(
            tenant_id=TENANT_A,
            store_id=STORE_ID,
            ingredient_id=ING_PORK,
            ingredient_name="猪肉",
            safety_stock=20.0,
            target_stock=100.0,
            min_order_qty=1.0,
            trigger_rule="safety_only",
        )
    ]
    # current = 8 < safety*0.5 = 10 → urgent
    current_stocks = {ING_PORK: 8.0}

    with patch.object(svc, "get_thresholds", AsyncMock(return_value=thresholds)), \
         patch.object(svc, "_fetch_current_stocks", AsyncMock(return_value=current_stocks)), \
         patch.object(svc, "_fetch_consumption_speed", AsyncMock(return_value=({}, {}))):
        items = await svc.check_and_recommend(STORE_ID, TENANT_A, db=None)

    assert len(items) == 1
    assert items[0].urgency == "urgent"
