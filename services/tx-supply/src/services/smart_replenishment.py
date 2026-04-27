"""智能库存双规则补货服务

双规则触发机制：
  safety_only: 库存 < safety_stock 时触发，补货量 = target_stock - current_stock
  dual:        safety_only + 近7日高速消耗时提前到 safety_stock*1.5 触发

Schema SQL:
  CREATE TABLE IF NOT EXISTS inventory_thresholds (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    store_id UUID NOT NULL,
    ingredient_id UUID NOT NULL,
    safety_stock NUMERIC(12,3) NOT NULL DEFAULT 0,
    target_stock NUMERIC(12,3) NOT NULL DEFAULT 0,
    min_order_qty NUMERIC(12,3) NOT NULL DEFAULT 1,
    trigger_rule TEXT NOT NULL DEFAULT 'safety_only',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(tenant_id, store_id, ingredient_id)
  );
  ALTER TABLE inventory_thresholds ENABLE ROW LEVEL SECURITY;
  CREATE POLICY inventory_thresholds_tenant ON inventory_thresholds
    USING (tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID);

# ROUTER REGISTRATION:
# from .api.smart_replenishment_routes import router as smart_replenishment_router
# app.include_router(smart_replenishment_router, prefix="/api/v1/smart-replenishment")
"""

from __future__ import annotations

import math
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, List, Optional

import structlog
from pydantic import BaseModel, Field

log = structlog.get_logger(__name__)

# 高速消耗判断阈值（日均消耗 > 平均消耗 * HIGH_CONSUMPTION_RATIO 认为高速）
HIGH_CONSUMPTION_RATIO = 1.3
# dual 规则提前触发倍数
DUAL_EARLY_TRIGGER_RATIO = 1.5
# 消耗速度统计天数
CONSUMPTION_WINDOW_DAYS = 7


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _gen_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  数据模型
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class ReplenishmentItem(BaseModel):
    """单条补货建议"""

    ingredient_id: str
    ingredient_name: str
    current_stock: float
    safety_stock: float
    target_stock: float
    recommend_qty: float = Field(ge=0)
    urgency: str  # 'urgent' | 'normal'
    trigger_threshold: float  # 实际触发阈值（safety_only=safety, dual可能更高）
    unit: str = ""


class InventoryThreshold(BaseModel):
    """库存阈值配置"""

    id: Optional[str] = None
    tenant_id: str
    store_id: str
    ingredient_id: str
    ingredient_name: str = ""
    safety_stock: float
    target_stock: float
    min_order_qty: float
    trigger_rule: str  # 'safety_only' | 'dual'
    updated_at: Optional[str] = None


class AutoRequisitionResult(BaseModel):
    """自动申购单结果"""

    requisition_id: Optional[str] = None
    store_id: str
    tenant_id: str
    items_count: int
    total_items: List[ReplenishmentItem]
    source: str = "smart_replenishment"
    created_at: str = Field(default_factory=_now_iso)
    skipped: bool = False  # True 表示无需补货，未创建申购单


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  主服务
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class SmartReplenishmentService:
    """双规则智能补货服务

    check_and_recommend — 检查补货需求，返回补货清单
    set_threshold       — 设置/更新阈值配置
    get_thresholds      — 查询门店阈值配置
    auto_create_requisition — 自动创建 draft 申购单
    """

    # ─── 检查补货 ───

    async def check_and_recommend(
        self,
        store_id: str,
        tenant_id: str,
        db: Any,
    ) -> List[ReplenishmentItem]:
        """对比当前库存与阈值，返回需补货清单。

        safety_only 规则：current < safety_stock 触发
        dual 规则：在 safety_only 基础上，若近7日日均消耗高（>平均消耗 × HIGH_CONSUMPTION_RATIO），
                  提前到 safety_stock * DUAL_EARLY_TRIGGER_RATIO 时即触发

        补货量 = target_stock - current_stock，按 min_order_qty 向上取整。
        """
        _log = log.bind(store_id=store_id, tenant_id=tenant_id)

        # 1. 查询门店阈值配置
        thresholds = await self.get_thresholds(store_id, tenant_id, db)
        if not thresholds:
            _log.info("smart_replenishment.check.no_thresholds")
            return []

        # 2. 查询当前库存（批量）
        ingredient_ids = [t.ingredient_id for t in thresholds]
        current_stocks = await self._fetch_current_stocks(store_id, tenant_id, ingredient_ids, db)

        # 3. dual 规则：查询近7日消耗速度
        consumption_map: dict[str, float] = {}
        avg_consumption_map: dict[str, float] = {}
        has_dual = any(t.trigger_rule == "dual" for t in thresholds)
        if has_dual:
            consumption_map, avg_consumption_map = await self._fetch_consumption_speed(
                store_id, tenant_id, ingredient_ids, db
            )

        # 4. 逐条检查
        result: List[ReplenishmentItem] = []
        for threshold in thresholds:
            iid = threshold.ingredient_id
            current = current_stocks.get(iid, 0.0)
            safety = threshold.safety_stock
            target = threshold.target_stock
            min_qty = threshold.min_order_qty

            # 计算实际触发阈值
            trigger_threshold = safety
            if threshold.trigger_rule == "dual":
                daily_consumption = consumption_map.get(iid, 0.0)
                avg_consumption = avg_consumption_map.get(iid, 0.0)
                if avg_consumption > 0 and daily_consumption > avg_consumption * HIGH_CONSUMPTION_RATIO:
                    # 高速消耗：提前触发
                    trigger_threshold = safety * DUAL_EARLY_TRIGGER_RATIO
                    _log.info(
                        "smart_replenishment.dual_early_trigger",
                        ingredient_id=iid,
                        daily_consumption=daily_consumption,
                        avg_consumption=avg_consumption,
                    )

            if current >= trigger_threshold:
                continue  # 无需补货

            # 计算补货量
            raw_qty = max(0.0, target - current)
            if raw_qty <= 0:
                continue

            # 按 min_order_qty 向上取整
            recommend_qty = math.ceil(raw_qty / min_qty) * min_qty

            urgency = "urgent" if current < safety * 0.5 else "normal"

            result.append(
                ReplenishmentItem(
                    ingredient_id=iid,
                    ingredient_name=threshold.ingredient_name,
                    current_stock=current,
                    safety_stock=safety,
                    target_stock=target,
                    recommend_qty=recommend_qty,
                    urgency=urgency,
                    trigger_threshold=trigger_threshold,
                    unit="",
                )
            )

        # urgent 优先排序
        result.sort(key=lambda x: (0 if x.urgency == "urgent" else 1, x.ingredient_name))

        _log.info(
            "smart_replenishment.check_done",
            total_thresholds=len(thresholds),
            need_replenishment=len(result),
            urgent=sum(1 for r in result if r.urgency == "urgent"),
        )
        return result

    # ─── 阈值设置 ───

    async def set_threshold(
        self,
        store_id: str,
        ingredient_id: str,
        safety: float,
        target: float,
        tenant_id: str,
        db: Any,
        min_order_qty: float = 1.0,
        trigger_rule: str = "safety_only",
        ingredient_name: str = "",
    ) -> InventoryThreshold:
        """设置或更新原料库存阈值配置（upsert）。"""
        _log = log.bind(
            store_id=store_id,
            ingredient_id=ingredient_id,
            tenant_id=tenant_id,
        )

        if safety < 0 or target < 0:
            raise ValueError("safety_stock 和 target_stock 不能为负数")
        if target < safety:
            raise ValueError("target_stock 不能低于 safety_stock")
        if min_order_qty <= 0:
            raise ValueError("min_order_qty 必须大于 0")
        if trigger_rule not in ("safety_only", "dual"):
            raise ValueError(f"trigger_rule 必须是 safety_only 或 dual，收到: {trigger_rule}")

        from sqlalchemy import text

        sql = text("""
            INSERT INTO inventory_thresholds
              (tenant_id, store_id, ingredient_id, safety_stock, target_stock,
               min_order_qty, trigger_rule, updated_at)
            VALUES
              (:tenant_id, :store_id, :ingredient_id, :safety_stock, :target_stock,
               :min_order_qty, :trigger_rule, NOW())
            ON CONFLICT (tenant_id, store_id, ingredient_id) DO UPDATE SET
              safety_stock  = EXCLUDED.safety_stock,
              target_stock  = EXCLUDED.target_stock,
              min_order_qty = EXCLUDED.min_order_qty,
              trigger_rule  = EXCLUDED.trigger_rule,
              updated_at    = NOW()
            RETURNING id, updated_at
        """)

        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, TRUE)"),
            {"tid": tenant_id},
        )
        result = await db.execute(
            sql,
            {
                "tenant_id": tenant_id,
                "store_id": store_id,
                "ingredient_id": ingredient_id,
                "safety_stock": safety,
                "target_stock": target,
                "min_order_qty": min_order_qty,
                "trigger_rule": trigger_rule,
            },
        )
        row = result.fetchone()
        threshold_id = str(row.id) if row and hasattr(row, "id") else _gen_id("thr")
        updated_at = row.updated_at.isoformat() if row and hasattr(row, "updated_at") else _now_iso()

        _log.info(
            "smart_replenishment.threshold_set",
            safety_stock=safety,
            target_stock=target,
            trigger_rule=trigger_rule,
        )

        return InventoryThreshold(
            id=threshold_id,
            tenant_id=tenant_id,
            store_id=store_id,
            ingredient_id=ingredient_id,
            ingredient_name=ingredient_name,
            safety_stock=safety,
            target_stock=target,
            min_order_qty=min_order_qty,
            trigger_rule=trigger_rule,
            updated_at=updated_at,
        )

    # ─── 查询阈值 ───

    async def get_thresholds(
        self,
        store_id: str,
        tenant_id: str,
        db: Any,
    ) -> List[InventoryThreshold]:
        """查询门店所有原料的阈值配置。"""
        from sqlalchemy import text

        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, TRUE)"),
            {"tid": tenant_id},
        )
        result = await db.execute(
            text("""
                SELECT it.id, it.ingredient_id, it.safety_stock, it.target_stock,
                       it.min_order_qty, it.trigger_rule, it.updated_at,
                       COALESCE(i.ingredient_name, '') AS ingredient_name
                FROM inventory_thresholds it
                LEFT JOIN ingredients i
                  ON i.id = it.ingredient_id::uuid
                  AND i.tenant_id = it.tenant_id
                  AND i.is_deleted = FALSE
                WHERE it.tenant_id = :tenant_id
                  AND it.store_id = :store_id
                ORDER BY it.updated_at DESC
            """),
            {"tenant_id": tenant_id, "store_id": store_id},
        )
        rows = result.fetchall()

        thresholds = []
        for row in rows:
            thresholds.append(
                InventoryThreshold(
                    id=str(row.id),
                    tenant_id=tenant_id,
                    store_id=store_id,
                    ingredient_id=str(row.ingredient_id),
                    ingredient_name=row.ingredient_name or "",
                    safety_stock=float(row.safety_stock),
                    target_stock=float(row.target_stock),
                    min_order_qty=float(row.min_order_qty),
                    trigger_rule=row.trigger_rule,
                    updated_at=row.updated_at.isoformat()
                    if hasattr(row.updated_at, "isoformat")
                    else str(row.updated_at),
                )
            )
        return thresholds

    # ─── 自动创建申购单 ───

    async def auto_create_requisition(
        self,
        store_id: str,
        tenant_id: str,
        db: Any,
    ) -> AutoRequisitionResult:
        """检查补货需求，自动创建 draft 申购单（source='smart_replenishment'）。

        若无需补货项，返回 skipped=True，不创建申购单。
        """
        _log = log.bind(store_id=store_id, tenant_id=tenant_id)

        items = await self.check_and_recommend(store_id, tenant_id, db)

        if not items:
            _log.info("smart_replenishment.auto_requisition.no_items")
            return AutoRequisitionResult(
                store_id=store_id,
                tenant_id=tenant_id,
                items_count=0,
                total_items=[],
                skipped=True,
            )

        # 构造申购单明细
        requisition_items = [
            {
                "ingredient_id": item.ingredient_id,
                "name": item.ingredient_name,
                "quantity": item.recommend_qty,
                "unit": item.unit,
                "estimated_price_fen": 0,
            }
            for item in items
        ]

        req_id: str
        if db is not None:
            # 生产模式：调用现有申购服务
            try:
                from .requisition import create_requisition

                requisition = await create_requisition(
                    store_id=store_id,
                    items=requisition_items,
                    requester_id="smart_replenishment_agent",
                    tenant_id=tenant_id,
                    db=db,
                )
                req_id = requisition.get("requisition_id") or requisition.get("id", _gen_id("req"))
            except ImportError:
                req_id = _gen_id("req")
        else:
            # 测试/预览模式：生成占位 ID
            req_id = _gen_id("req")

        _log.info(
            "smart_replenishment.auto_requisition.created",
            requisition_id=req_id,
            items_count=len(items),
            urgent=sum(1 for i in items if i.urgency == "urgent"),
        )

        return AutoRequisitionResult(
            requisition_id=req_id,
            store_id=store_id,
            tenant_id=tenant_id,
            items_count=len(items),
            total_items=items,
            source="smart_replenishment",
        )

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  私有辅助方法
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    async def _fetch_current_stocks(
        self,
        store_id: str,
        tenant_id: str,
        ingredient_ids: List[str],
        db: Any,
    ) -> dict[str, float]:
        """批量查询当前库存。返回 {ingredient_id: current_quantity}"""
        if not ingredient_ids:
            return {}

        from sqlalchemy import text

        result = await db.execute(
            text("""
                SELECT id::text AS ingredient_id,
                       COALESCE(current_quantity, 0) AS current_quantity
                FROM ingredients
                WHERE tenant_id = :tenant_id
                  AND store_id = :store_id
                  AND id = ANY(:ids::uuid[])
                  AND is_deleted = FALSE
            """),
            {
                "tenant_id": tenant_id,
                "store_id": store_id,
                "ids": ingredient_ids,
            },
        )
        rows = result.fetchall()
        return {row.ingredient_id: float(row.current_quantity) for row in rows}

    async def _fetch_consumption_speed(
        self,
        store_id: str,
        tenant_id: str,
        ingredient_ids: List[str],
        db: Any,
    ) -> tuple[dict[str, float], dict[str, float]]:
        """查询近7日每日消耗速度与历史平均消耗速度。

        Returns:
            (recent_daily_map, avg_daily_map)
            recent_daily_map: {ingredient_id: 近7日日均消耗}
            avg_daily_map:    {ingredient_id: 历史整体日均消耗}
        """
        if not ingredient_ids:
            return {}, {}

        from sqlalchemy import text

        cutoff = (datetime.now(timezone.utc) - timedelta(days=CONSUMPTION_WINDOW_DAYS)).isoformat()

        # 近7日消耗
        result_recent = await db.execute(
            text("""
                SELECT ingredient_id::text,
                       COALESCE(SUM(ABS(quantity)) / :window_days, 0) AS daily_consumption
                FROM ingredient_transactions
                WHERE tenant_id = :tenant_id
                  AND store_id = :store_id
                  AND ingredient_id = ANY(:ids::uuid[])
                  AND transaction_type IN ('consume', 'deduction', 'waste')
                  AND created_at >= :cutoff
                  AND is_deleted = FALSE
                GROUP BY ingredient_id
            """),
            {
                "tenant_id": tenant_id,
                "store_id": store_id,
                "ids": ingredient_ids,
                "window_days": CONSUMPTION_WINDOW_DAYS,
                "cutoff": cutoff,
            },
        )
        recent_rows = result_recent.fetchall()
        recent_map = {row.ingredient_id: float(row.daily_consumption) for row in recent_rows}

        # 历史平均（取过去30天）
        cutoff_30 = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        result_avg = await db.execute(
            text("""
                SELECT ingredient_id::text,
                       COALESCE(SUM(ABS(quantity)) / 30.0, 0) AS daily_consumption
                FROM ingredient_transactions
                WHERE tenant_id = :tenant_id
                  AND store_id = :store_id
                  AND ingredient_id = ANY(:ids::uuid[])
                  AND transaction_type IN ('consume', 'deduction', 'waste')
                  AND created_at >= :cutoff
                  AND is_deleted = FALSE
                GROUP BY ingredient_id
            """),
            {
                "tenant_id": tenant_id,
                "store_id": store_id,
                "ids": ingredient_ids,
                "cutoff": cutoff_30,
            },
        )
        avg_rows = result_avg.fetchall()
        avg_map = {row.ingredient_id: float(row.daily_consumption) for row in avg_rows}

        return recent_map, avg_map
