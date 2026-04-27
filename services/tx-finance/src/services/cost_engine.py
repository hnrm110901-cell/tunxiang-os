"""CostEngine — 订单→菜品→BOM→配料实时成本追溯

核心逻辑：
  1. 查询订单明细（order_items）
  2. 对每个菜品查找激活BOM → 计算配料成本
     配料成本 = sum(ingredient_qty × unit_cost_fen / yield_rate)
  3. 汇总：total_cost, gross_margin = (selling_price - total_cost) / selling_price
  4. 写入 cost_snapshots 表
  5. 无BOM时 fallback 到 dish.cost_fen（OrderItem.cost_fen）字段
"""

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Optional

import structlog
from sqlalchemy import and_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)


# ─── 数据类 ──────────────────────────────────────────────────────────────────


@dataclass
class DishCostResult:
    """单道菜品的成本计算结果"""

    order_item_id: uuid.UUID
    dish_id: uuid.UUID
    quantity: int
    selling_price: Decimal  # 单价（分）
    raw_material_cost: Decimal  # 原料成本（分），已含损耗
    labor_cost_allocated: Decimal = Decimal("0")
    overhead_allocated: Decimal = Decimal("0")
    bom_version_id: Optional[uuid.UUID] = None
    cost_source: str = "bom"  # bom | standard_cost

    @property
    def total_cost(self) -> Decimal:
        return self.raw_material_cost + self.labor_cost_allocated + self.overhead_allocated

    @property
    def gross_profit(self) -> Decimal:
        return self.selling_price - self.total_cost

    @property
    def gross_margin_rate(self) -> Decimal:
        if self.selling_price <= 0:
            return Decimal("0")
        rate = self.gross_profit / self.selling_price
        return rate.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


@dataclass
class OrderCostResult:
    """整笔订单的成本汇总"""

    order_id: uuid.UUID
    tenant_id: uuid.UUID
    items: list[DishCostResult] = field(default_factory=list)
    computed_at: Optional[datetime] = None

    @property
    def total_cost(self) -> Decimal:
        return sum(item.raw_material_cost * item.quantity for item in self.items)

    @property
    def total_selling_price(self) -> Decimal:
        return sum(item.selling_price * item.quantity for item in self.items)

    @property
    def gross_margin_rate(self) -> Decimal:
        if self.total_selling_price <= 0:
            return Decimal("0")
        gp = self.total_selling_price - self.total_cost
        return (gp / self.total_selling_price).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


# ─── CostEngine ──────────────────────────────────────────────────────────────


class CostEngine:
    """财务成本计算引擎

    所有公共方法均接受显式的 tenant_id，确保 RLS 租户隔离。
    金额单位统一为分（fen），计算时转换为 Decimal 保持精度。
    """

    # ── 公共接口 ──────────────────────────────────────────────

    async def compute_order_cost(
        self,
        order_id: uuid.UUID,
        tenant_id: uuid.UUID,
        db: AsyncSession,
    ) -> OrderCostResult:
        """计算单笔订单的完整成本，并写入 cost_snapshots 表

        流程：
          1. 获取订单明细
          2. 逐菜品查BOM → 计算配料成本（含损耗）
          3. 无BOM时 fallback 到标准成本
          4. 持久化快照
        """
        log = logger.bind(order_id=str(order_id), tenant_id=str(tenant_id))

        order_items = await self._fetch_order_items(order_id, tenant_id, db)
        if not order_items:
            log.warning("compute_order_cost.no_items")
            return OrderCostResult(
                order_id=order_id,
                tenant_id=tenant_id,
                computed_at=datetime.now(timezone.utc),
            )

        dish_results: list[DishCostResult] = []
        for item in order_items:
            dish_cost = await self._compute_dish_cost(item, tenant_id, db)
            dish_results.append(dish_cost)
            log.debug(
                "dish_cost_computed",
                dish_id=str(item.dish_id),
                raw_cost=str(dish_cost.raw_material_cost),
                margin=str(dish_cost.gross_margin_rate),
                source=dish_cost.cost_source,
            )

        result = OrderCostResult(
            order_id=order_id,
            tenant_id=tenant_id,
            items=dish_results,
            computed_at=datetime.now(timezone.utc),
        )

        try:
            await self._save_cost_snapshots(result, db)
        except Exception as exc:
            log.error("save_cost_snapshots.failed", error=str(exc), exc_info=True)
            raise

        log.info(
            "order_cost_computed",
            total_cost=str(result.total_cost),
            gross_margin=str(result.gross_margin_rate),
            item_count=len(dish_results),
        )
        return result

    async def get_order_margin(
        self,
        order_id: uuid.UUID,
        tenant_id: uuid.UUID,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """获取订单毛利率，优先从 cost_snapshots 缓存读取，否则实时计算"""
        snapshot = await self._fetch_cost_snapshot(order_id, tenant_id, db)
        if snapshot:
            return snapshot

        result = await self.compute_order_cost(order_id, tenant_id, db)
        return {
            "order_id": str(order_id),
            "total_cost": result.total_cost,
            "selling_price": result.total_selling_price,
            "gross_margin_rate": result.gross_margin_rate,
            "computed_at": result.computed_at.isoformat() if result.computed_at else None,
            "from_cache": False,
        }

    async def batch_recompute_date(
        self,
        store_id: uuid.UUID,
        biz_date: date,
        tenant_id: uuid.UUID,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """批量重算某天所有订单的成本快照（夜批作业）

        用于：
        - 采购价格修正后的成本回算
        - BOM版本更新后的历史成本刷新
        """
        log = logger.bind(
            store_id=str(store_id),
            biz_date=str(biz_date),
            tenant_id=str(tenant_id),
        )
        order_ids = await self._fetch_order_ids_by_date(store_id, biz_date, tenant_id, db)
        log.info("batch_recompute.start", order_count=len(order_ids))

        success_count = 0
        error_count = 0

        for oid in order_ids:
            try:
                await self.compute_order_cost(oid, tenant_id, db)
                success_count += 1
            except (OSError, RuntimeError, ValueError) as exc:
                error_count += 1
                log.error(
                    "batch_recompute.order_failed",
                    order_id=str(oid),
                    error=str(exc),
                    exc_info=True,
                )

        log.info(
            "batch_recompute.done",
            success=success_count,
            errors=error_count,
        )
        return {
            "store_id": str(store_id),
            "biz_date": str(biz_date),
            "total_orders": len(order_ids),
            "success": success_count,
            "errors": error_count,
        }

    # ── 内部计算 ──────────────────────────────────────────────

    async def _compute_dish_cost(
        self,
        order_item: Any,
        tenant_id: uuid.UUID,
        db: AsyncSession,
    ) -> DishCostResult:
        """计算单个菜品的原料成本

        BOM路径：
          配料成本 = sum(item.standard_qty × item.unit_cost_fen / bom.yield_rate)

        fallback路径（无BOM）：
          成本 = order_item.cost_fen
        """
        dish_id = order_item.dish_id
        bom = await self._fetch_active_bom(dish_id, tenant_id, db)

        if bom is not None and bom.items:
            yield_rate = Decimal(str(bom.yield_rate)) if bom.yield_rate else Decimal("1")
            if yield_rate <= 0:
                yield_rate = Decimal("1")

            raw_cost = Decimal("0")
            for bom_item in bom.items:
                qty = Decimal(str(bom_item.standard_qty))
                unit_cost = Decimal(str(bom_item.unit_cost_fen or 0))
                raw_cost += qty * unit_cost / yield_rate

            raw_cost = raw_cost.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)

            return DishCostResult(
                order_item_id=order_item.id,
                dish_id=dish_id,
                quantity=order_item.quantity,
                selling_price=Decimal(str(order_item.unit_price_fen)),
                raw_material_cost=raw_cost,
                bom_version_id=bom.id,
                cost_source="bom",
            )
        else:
            # fallback：使用订单行的标准成本字段
            std_cost = Decimal(str(getattr(order_item, "cost_fen", 0) or 0))
            logger.debug(
                "bom_fallback_to_standard_cost",
                dish_id=str(dish_id),
                std_cost=str(std_cost),
            )
            return DishCostResult(
                order_item_id=order_item.id,
                dish_id=dish_id,
                quantity=order_item.quantity,
                selling_price=Decimal(str(order_item.unit_price_fen)),
                raw_material_cost=std_cost,
                bom_version_id=None,
                cost_source="standard_cost",
            )

    # ── DB 查询（可在测试中 patch）────────────────────────────

    async def _fetch_order_items(
        self,
        order_id: uuid.UUID,
        tenant_id: uuid.UUID,
        db: AsyncSession,
    ) -> list[Any]:
        """从 order_items 表查询订单明细行

        注意：依赖 RLS + 显式 tenant_id 双重隔离。
        """
        from shared.ontology.src.entities import Order, OrderItem

        result = await db.execute(
            select(OrderItem)
            .join(Order, OrderItem.order_id == Order.id)
            .where(
                and_(
                    OrderItem.order_id == order_id,
                    Order.tenant_id == tenant_id,
                )
            )
        )
        return list(result.scalars().all())

    async def _fetch_active_bom(
        self,
        dish_id: uuid.UUID,
        tenant_id: uuid.UUID,
        db: AsyncSession,
    ) -> Optional[Any]:
        """查询菜品的激活BOM模板（含配料明细）

        跨服务查询：tx-finance 直接访问 bom_templates + bom_items 表。
        生产中可改为调用 tx-supply 内部gRPC/HTTP接口。
        """
        try:
            result = await db.execute(
                text("""
                    SELECT bt.id, bt.dish_id, bt.yield_rate,
                           json_agg(json_build_object(
                               'ingredient_id', bi.ingredient_id,
                               'standard_qty', bi.standard_qty,
                               'unit_cost_fen', bi.unit_cost_fen
                           )) AS items
                    FROM bom_templates bt
                    JOIN bom_items bi ON bi.template_id = bt.id
                    WHERE bt.dish_id = :dish_id
                      AND bt.tenant_id = :tenant_id
                      AND bt.is_active = TRUE
                      AND bt.is_deleted = FALSE
                    GROUP BY bt.id, bt.dish_id, bt.yield_rate
                    LIMIT 1
                """),
                {"dish_id": str(dish_id), "tenant_id": str(tenant_id)},
            )
            row = result.fetchone()
            if not row:
                return None

            # 将原始行包装为简单对象供 _compute_dish_cost 使用
            class _BomProxy:
                def __init__(self, r: Any) -> None:
                    self.id = uuid.UUID(str(r.id))
                    self.dish_id = uuid.UUID(str(r.dish_id))
                    self.yield_rate = float(r.yield_rate or 1.0)

                    class _Item:
                        def __init__(self, d: dict) -> None:
                            self.ingredient_id = d["ingredient_id"]
                            self.standard_qty = float(d["standard_qty"])
                            self.unit_cost_fen = int(d.get("unit_cost_fen") or 0)

                    self.items = [_Item(i) for i in (r.items or [])]

            return _BomProxy(row)

        except Exception as exc:
            logger.error(
                "fetch_active_bom.failed",
                dish_id=str(dish_id),
                error=str(exc),
                exc_info=True,
            )
            return None

    async def _fetch_cost_snapshot(
        self,
        order_id: uuid.UUID,
        tenant_id: uuid.UUID,
        db: AsyncSession,
    ) -> Optional[dict[str, Any]]:
        """从 cost_snapshots 聚合查询订单级快照"""
        result = await db.execute(
            text("""
                SELECT
                    order_id,
                    SUM(total_cost)      AS total_cost,
                    SUM(selling_price)   AS selling_price,
                    AVG(gross_margin_rate) AS gross_margin_rate,
                    MAX(computed_at)     AS computed_at
                FROM cost_snapshots
                WHERE order_id = :order_id
                  AND tenant_id = :tenant_id
                GROUP BY order_id
                LIMIT 1
            """),
            {"order_id": str(order_id), "tenant_id": str(tenant_id)},
        )
        row = result.fetchone()
        if not row:
            return None

        return {
            "order_id": str(order_id),
            "total_cost": Decimal(str(row.total_cost or 0)),
            "selling_price": Decimal(str(row.selling_price or 0)),
            "gross_margin_rate": Decimal(str(row.gross_margin_rate or 0)),
            "computed_at": row.computed_at.isoformat() if row.computed_at else None,
            "from_cache": True,
        }

    async def _save_cost_snapshots(
        self,
        result: OrderCostResult,
        db: AsyncSession,
    ) -> None:
        """将订单成本结果批量写入 cost_snapshots 表（upsert）"""
        if not result.items:
            return

        rows = []
        for item in result.items:
            rows.append(
                {
                    "tenant_id": str(result.tenant_id),
                    "order_id": str(result.order_id),
                    "order_item_id": str(item.order_item_id),
                    "dish_id": str(item.dish_id),
                    "raw_material_cost": float(item.raw_material_cost),
                    "labor_cost_allocated": float(item.labor_cost_allocated),
                    "overhead_allocated": float(item.overhead_allocated),
                    "total_cost": float(item.total_cost),
                    "selling_price": float(item.selling_price),
                    "gross_margin_rate": float(item.gross_margin_rate),
                    "bom_version_id": str(item.bom_version_id) if item.bom_version_id else None,
                    "cost_source": item.cost_source,
                    "computed_at": result.computed_at.isoformat() if result.computed_at else None,
                }
            )

        await db.execute(
            text("""
                INSERT INTO cost_snapshots (
                    tenant_id, order_id, order_item_id, dish_id,
                    raw_material_cost, labor_cost_allocated, overhead_allocated,
                    total_cost, selling_price, gross_margin_rate,
                    bom_version_id, cost_source, computed_at
                ) VALUES (
                    :tenant_id::UUID, :order_id::UUID, :order_item_id::UUID, :dish_id::UUID,
                    :raw_material_cost, :labor_cost_allocated, :overhead_allocated,
                    :total_cost, :selling_price, :gross_margin_rate,
                    :bom_version_id::UUID, :cost_source, :computed_at::TIMESTAMPTZ
                )
                ON CONFLICT (order_item_id)
                DO UPDATE SET
                    raw_material_cost = EXCLUDED.raw_material_cost,
                    total_cost        = EXCLUDED.total_cost,
                    selling_price     = EXCLUDED.selling_price,
                    gross_margin_rate = EXCLUDED.gross_margin_rate,
                    bom_version_id    = EXCLUDED.bom_version_id,
                    cost_source       = EXCLUDED.cost_source,
                    computed_at       = EXCLUDED.computed_at
            """),
            rows,
        )
        await db.commit()

    async def _fetch_order_ids_by_date(
        self,
        store_id: uuid.UUID,
        biz_date: date,
        tenant_id: uuid.UUID,
        db: AsyncSession,
    ) -> list[uuid.UUID]:
        """查询指定门店指定日期的所有已完成订单ID"""
        from datetime import datetime, timezone

        from shared.ontology.src.entities import Order

        start_dt = datetime.combine(biz_date, datetime.min.time()).replace(tzinfo=timezone.utc)
        end_dt = datetime.combine(biz_date, datetime.max.time()).replace(tzinfo=timezone.utc)

        result = await db.execute(
            select(Order.id).where(
                and_(
                    Order.store_id == store_id,
                    Order.tenant_id == tenant_id,
                    Order.status.in_(["completed", "settled"]),
                    Order.created_at >= start_dt,
                    Order.created_at <= end_dt,
                )
            )
        )
        return [row[0] for row in result.all()]
