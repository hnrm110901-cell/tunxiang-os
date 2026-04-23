"""采购预测引擎：销售预测 × BOM → 食材需求 → 采购建议

集成链路：
  DemandForecastService（tx-supply/demand_forecast）
      ↓ 计算未来N天食材消耗预测
  BOM 分解（bom_templates / bom_items，优雅降级）
      ↓ 食材需求量 = 销售预测量 × BOM 单位用量
  当前库存对比 + 安全库存阈值 + 供应商交期
      ↓
  采购建议清单（含 confidence 字段）
      ↓ 总金额 > 1万元时触发 ModelRouter AI 摘要
  分供应商采购草稿单

AI 调用约束：
  - 只在 generate_purchase_order_draft 且总金额 > 10,000 元时触发
  - 通过 ModelRouter 调用（符合 CLAUDE.md 安全规范）

数据库表依赖：
  - inventory_thresholds  — 阈值配置（来自 smart_replenishment）
  - ingredients           — 当前库存
  - ingredient_transactions — 消耗历史
  - bom_templates / bom_items — BOM分解（可降级）
  - suppliers             — 供应商信息（可降级）
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Optional

import structlog
from pydantic import BaseModel, Field, field_validator

from .demand_forecast import DemandForecastService

log = structlog.get_logger(__name__)

# ─── 常量 ───
AI_SUMMARY_THRESHOLD_FEN = 1_000_000  # 1万元（分）
SAFETY_FACTOR = 1.1  # EOQ 安全系数
DEFAULT_FORECAST_DAYS = 7
DEFAULT_LEAD_DAYS = 2  # 供应商交期默认值（供应商信息缺失时）
DEFAULT_PACKAGE_SIZE = 1.0  # 包装规格默认值


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  数据模型（Pydantic V2）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class IngredientDemandForecast(BaseModel):
    """单个食材的需求预测与采购建议"""

    ingredient_id: str
    ingredient_name: str
    forecast_qty: float = Field(ge=0, description="未来N天预计消耗总量")
    current_stock: float = Field(ge=0, description="当前库存量")
    safety_stock: float = Field(ge=0, description="安全库存阈值")
    purchase_qty: float = Field(default=0.0, ge=0, description="建议采购量（0=无需采购）")
    unit: str = ""
    unit_cost_fen: int = Field(default=0, ge=0, description="单价（分）")
    supplier_id: str = ""
    supplier_lead_days: int = Field(default=DEFAULT_LEAD_DAYS, ge=0, description="供应商交期（天）")
    package_size: float = Field(default=DEFAULT_PACKAGE_SIZE, gt=0, description="包装规格（取整单位）")
    confidence: float = Field(default=0.5, ge=0.0, le=1.0, description="预测置信度 0-1")
    forecast_days: int = Field(default=DEFAULT_FORECAST_DAYS, gt=0)
    estimated_amount_fen: int = Field(default=0, ge=0, description="本次采购估算金额（分）")

    @field_validator("forecast_qty", mode="before")
    @classmethod
    def clamp_forecast_qty(cls, v: Any) -> float:
        """负预测量（数据异常）钳制到 0"""
        return max(0.0, float(v))


class SupplierOrderItem(BaseModel):
    """供应商采购单明细行"""

    ingredient_id: str
    ingredient_name: str
    purchase_qty: float = Field(ge=0)
    unit: str = ""
    unit_cost_fen: int = Field(ge=0)
    subtotal_fen: int = Field(ge=0)
    package_size: float = Field(gt=0)


class SupplierOrder(BaseModel):
    """单个供应商的采购单"""

    supplier_id: str
    items: list[SupplierOrderItem]
    total_fen: int = Field(ge=0)
    lead_days: int = Field(ge=0)


class PurchaseOrderDraft(BaseModel):
    """采购草稿（按供应商分组）"""

    store_id: str
    tenant_id: str
    forecast_days: int
    orders_by_supplier: list[SupplierOrder]
    total_amount_fen: int = Field(ge=0, description="所有供应商合计金额（分）")
    ai_summary: Optional[str] = None
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class UrgentIngredient(BaseModel):
    """紧急补货预警：库存不足以支撑明日营业"""

    ingredient_id: str
    ingredient_name: str
    current_stock: float = Field(ge=0)
    tomorrow_demand: float = Field(ge=0, description="明日预计消耗量")
    shortage_qty: float = Field(ge=0, description="缺口量 = max(0, tomorrow_demand - current_stock)")
    safety_stock: float = Field(ge=0)
    supplier_id: str = ""
    supplier_lead_days: int = Field(ge=0)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  纯函数：采购量计算（EOQ 简化版，便于测试）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _calc_purchase_qty(
    forecast_demand: float,
    current_stock: float,
    safety_stock: float,
    supplier_lead_days: int,
    daily_demand: float,
    package_size: float,
    safety_factor: float = SAFETY_FACTOR,
) -> float:
    """计算建议采购量（EOQ 简化版）

    公式：
      lead_buffer = daily_demand × lead_days        （交期内额外消耗缓冲）
      net_demand  = max(0, demand - current + safety + lead_buffer)
      raw_qty     = net_demand × safety_factor
      purchase    = ceil(raw_qty / package_size) × package_size

    边界处理：
      - forecast_demand < 0 → 视为 0
      - 净需求 ≤ 0 → 返回 0.0（无需采购）
    """
    # 负预测钳制
    demand = max(0.0, forecast_demand)

    # 交期缓冲（交期内还会继续消耗）
    lead_buffer = daily_demand * max(0, supplier_lead_days)

    # 净需求 = 预测消耗 - 现有库存 + 安全库存 + 交期缓冲
    net_demand = demand - current_stock + safety_stock + lead_buffer

    if net_demand <= 0:
        return 0.0

    # 应用安全系数
    raw_qty = net_demand * safety_factor

    # 向上取整到包装规格
    packages = math.ceil(raw_qty / package_size)
    return packages * package_size


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  主服务
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class ProcurementForecastService:
    """采购预测引擎：销售预测 × BOM → 食材需求 → 采购建议

    公开方法：
      forecast_ingredient_demand  — 预测未来N天食材需求，生成采购建议
      generate_purchase_order_draft — 需求转为分供应商采购草稿单
      get_replenishment_urgency   — 紧急补货预警（实时，不走AI）
    """

    # ─── 公开接口 ───

    async def forecast_ingredient_demand(
        self,
        store_id: str,
        tenant_id: str,
        db: Any,
        forecast_days: int = DEFAULT_FORECAST_DAYS,
    ) -> list[IngredientDemandForecast]:
        """预测未来N天食材需求量，生成采购建议清单。

        流程：
          1. 获取门店所有食材的阈值配置
          2. 调用 DemandForecastService 获取各食材预测消耗量
          3. 查询当前库存
          4. 查询供应商信息（交期、包装规格）
          5. 计算建议采购量（含安全系数和交期缓冲）
          6. 返回带 confidence 字段的预测清单

        Args:
            store_id: 门店 ID
            tenant_id: 租户 ID（RLS 隔离）
            db: 数据库会话
            forecast_days: 预测天数，默认 7

        Returns:
            list[IngredientDemandForecast]，purchase_qty=0 表示库存充足
        """
        _log = log.bind(store_id=store_id, tenant_id=tenant_id, forecast_days=forecast_days)

        # Step 1: 获取阈值配置
        thresholds = await self._fetch_thresholds(store_id, tenant_id, db)
        if not thresholds:
            _log.info("procurement_forecast.no_thresholds")
            return []

        ingredient_ids = [t.ingredient_id for t in thresholds]

        # Step 2: 批量查询当前库存
        current_stocks = await self._fetch_current_stocks(store_id, tenant_id, ingredient_ids, db)

        # Step 3: 查询供应商信息（交期/包装/单价）
        supplier_info = await self._fetch_supplier_info(tenant_id, ingredient_ids, db)

        # Step 4: 使用 DemandForecastService 预测各食材消耗量
        demand_svc = DemandForecastService()
        result: list[IngredientDemandForecast] = []

        for threshold in thresholds:
            iid = threshold.ingredient_id
            current = current_stocks.get(iid, 0.0)
            safety = threshold.safety_stock
            sup_info = supplier_info.get(iid, {})
            lead_days = sup_info.get("lead_days", DEFAULT_LEAD_DAYS)
            package_size = sup_info.get("package_size", DEFAULT_PACKAGE_SIZE)
            unit_cost_fen = sup_info.get("unit_cost_fen", 0)
            supplier_id = sup_info.get("supplier_id", "")

            # 调用需求预测
            try:
                forecast_qty = await demand_svc.forecast_next_period(
                    ingredient_id=iid,
                    store_id=store_id,
                    days=forecast_days,
                    tenant_id=tenant_id,
                    db=db,
                )
            except (ValueError, AttributeError) as exc:
                _log.warning(
                    "procurement_forecast.demand_svc_error",
                    ingredient_id=iid,
                    error=str(exc),
                )
                forecast_qty = 0.0

            # 日均需求（用于交期缓冲计算）
            daily_demand = forecast_qty / forecast_days if forecast_days > 0 else 0.0

            # 计算建议采购量
            purchase_qty = _calc_purchase_qty(
                forecast_demand=forecast_qty,
                current_stock=current,
                safety_stock=safety,
                supplier_lead_days=lead_days,
                daily_demand=daily_demand,
                package_size=package_size,
                safety_factor=SAFETY_FACTOR,
            )

            # 置信度：有历史数据 → 较高；无数据（forecast=0 且 stock>0）→ 低
            confidence = _calc_confidence(forecast_qty=forecast_qty, current_stock=current)

            estimated_amount_fen = int(purchase_qty * unit_cost_fen)

            result.append(
                IngredientDemandForecast(
                    ingredient_id=iid,
                    ingredient_name=threshold.ingredient_name,
                    forecast_qty=forecast_qty,
                    current_stock=current,
                    safety_stock=safety,
                    purchase_qty=purchase_qty,
                    unit="",
                    unit_cost_fen=unit_cost_fen,
                    supplier_id=supplier_id,
                    supplier_lead_days=lead_days,
                    package_size=package_size,
                    confidence=confidence,
                    forecast_days=forecast_days,
                    estimated_amount_fen=estimated_amount_fen,
                )
            )

        # 按需采购优先，再按置信度降序
        result.sort(key=lambda x: (0 if x.purchase_qty > 0 else 1, -x.confidence))

        _log.info(
            "procurement_forecast.done",
            total=len(result),
            need_purchase=sum(1 for r in result if r.purchase_qty > 0),
        )
        return result

    async def generate_purchase_order_draft(
        self,
        store_id: str,
        tenant_id: str,
        demand_forecast: list[IngredientDemandForecast],
        db: Any,
    ) -> PurchaseOrderDraft:
        """将食材需求转化为分供应商的采购建议单草稿。

        逻辑：
          1. 过滤 purchase_qty > 0 的食材
          2. 按 supplier_id 分组
          3. 计算每张供应商单的合计金额
          4. 汇总总金额
          5. 总金额 ≥ AI_SUMMARY_THRESHOLD_FEN（1万元）时调用 ModelRouter 生成摘要

        Args:
            store_id: 门店 ID
            tenant_id: 租户 ID
            demand_forecast: forecast_ingredient_demand 的返回结果
            db: 数据库会话（AI 摘要时需用于取门店名称）

        Returns:
            PurchaseOrderDraft，含按供应商分组的采购清单
        """
        _log = log.bind(store_id=store_id, tenant_id=tenant_id)

        # 过滤无需采购项
        purchase_items = [d for d in demand_forecast if d.purchase_qty > 0]

        if not purchase_items:
            _log.info("procurement_forecast.draft.no_purchase_needed")
            return PurchaseOrderDraft(
                store_id=store_id,
                tenant_id=tenant_id,
                forecast_days=demand_forecast[0].forecast_days if demand_forecast else DEFAULT_FORECAST_DAYS,
                orders_by_supplier=[],
                total_amount_fen=0,
            )

        # 按供应商分组
        sup_map: dict[str, list[IngredientDemandForecast]] = {}
        for item in purchase_items:
            key = item.supplier_id or "unknown"
            sup_map.setdefault(key, []).append(item)

        orders_by_supplier: list[SupplierOrder] = []
        total_amount_fen = 0

        for supplier_id, items in sup_map.items():
            sup_items: list[SupplierOrderItem] = []
            sup_total = 0

            for d in items:
                subtotal = int(d.purchase_qty * d.unit_cost_fen)
                sup_items.append(
                    SupplierOrderItem(
                        ingredient_id=d.ingredient_id,
                        ingredient_name=d.ingredient_name,
                        purchase_qty=d.purchase_qty,
                        unit=d.unit,
                        unit_cost_fen=d.unit_cost_fen,
                        subtotal_fen=subtotal,
                        package_size=d.package_size,
                    )
                )
                sup_total += subtotal

            orders_by_supplier.append(
                SupplierOrder(
                    supplier_id=supplier_id,
                    items=sup_items,
                    total_fen=sup_total,
                    lead_days=items[0].supplier_lead_days,
                )
            )
            total_amount_fen += sup_total

        # AI 摘要：仅在总金额超过阈值时触发
        ai_summary: Optional[str] = None
        if total_amount_fen >= AI_SUMMARY_THRESHOLD_FEN:
            _log.info(
                "procurement_forecast.draft.triggering_ai_summary",
                total_amount_fen=total_amount_fen,
            )
            try:
                ai_summary = await self._call_ai_summary(
                    store_id=store_id,
                    tenant_id=tenant_id,
                    orders=orders_by_supplier,
                    total_amount_fen=total_amount_fen,
                )
            except (RuntimeError, ValueError, OSError) as exc:
                _log.warning(
                    "procurement_forecast.draft.ai_summary_failed",
                    error=str(exc),
                )
                ai_summary = None

        forecast_days = purchase_items[0].forecast_days if purchase_items else DEFAULT_FORECAST_DAYS

        _log.info(
            "procurement_forecast.draft.created",
            suppliers=len(orders_by_supplier),
            total_amount_fen=total_amount_fen,
            has_ai_summary=ai_summary is not None,
        )

        return PurchaseOrderDraft(
            store_id=store_id,
            tenant_id=tenant_id,
            forecast_days=forecast_days,
            orders_by_supplier=orders_by_supplier,
            total_amount_fen=total_amount_fen,
            ai_summary=ai_summary,
        )

    async def get_replenishment_urgency(
        self,
        store_id: str,
        tenant_id: str,
        db: Any,
    ) -> list[UrgentIngredient]:
        """紧急补货预警：库存不足以支撑明日营业的食材清单。

        实时计算，不走 AI，低延迟优先。
        判断逻辑：current_stock < tomorrow_demand（1天预测）

        Args:
            store_id: 门店 ID
            tenant_id: 租户 ID
            db: 数据库会话

        Returns:
            list[UrgentIngredient]，按缺口量降序排列
        """
        _log = log.bind(store_id=store_id, tenant_id=tenant_id)

        thresholds = await self._fetch_thresholds(store_id, tenant_id, db)
        if not thresholds:
            return []

        ingredient_ids = [t.ingredient_id for t in thresholds]
        current_stocks = await self._fetch_current_stocks(store_id, tenant_id, ingredient_ids, db)
        supplier_info = await self._fetch_supplier_info(tenant_id, ingredient_ids, db)

        demand_svc = DemandForecastService()
        urgent: list[UrgentIngredient] = []

        for threshold in thresholds:
            iid = threshold.ingredient_id
            current = current_stocks.get(iid, 0.0)

            # 预测明日消耗（1天）
            try:
                tomorrow_demand = await demand_svc.forecast_next_period(
                    ingredient_id=iid,
                    store_id=store_id,
                    days=1,
                    tenant_id=tenant_id,
                    db=db,
                )
            except (ValueError, AttributeError) as exc:
                _log.warning(
                    "procurement_forecast.urgency.forecast_error",
                    ingredient_id=iid,
                    error=str(exc),
                )
                tomorrow_demand = 0.0

            # 判断是否紧急：库存低于明日需求或低于安全库存
            is_urgent = current < tomorrow_demand or current < threshold.safety_stock

            if is_urgent:
                shortage = max(0.0, tomorrow_demand - current)
                sup_info = supplier_info.get(iid, {})
                urgent.append(
                    UrgentIngredient(
                        ingredient_id=iid,
                        ingredient_name=threshold.ingredient_name,
                        current_stock=current,
                        tomorrow_demand=tomorrow_demand,
                        shortage_qty=shortage,
                        safety_stock=threshold.safety_stock,
                        supplier_id=sup_info.get("supplier_id", ""),
                        supplier_lead_days=sup_info.get("lead_days", DEFAULT_LEAD_DAYS),
                    )
                )

        # 按缺口量降序（最紧急的在前）
        urgent.sort(key=lambda x: x.shortage_qty, reverse=True)

        _log.info(
            "procurement_forecast.urgency.done",
            total_thresholds=len(thresholds),
            urgent_count=len(urgent),
        )
        return urgent

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  私有辅助方法
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    async def _fetch_thresholds(
        self,
        store_id: str,
        tenant_id: str,
        db: Any,
    ):
        """从 inventory_thresholds 获取门店阈值配置（复用 SmartReplenishmentService）"""
        from .smart_replenishment import SmartReplenishmentService

        svc = SmartReplenishmentService()
        return await svc.get_thresholds(store_id, tenant_id, db)

    async def _fetch_current_stocks(
        self,
        store_id: str,
        tenant_id: str,
        ingredient_ids: list[str],
        db: Any,
    ) -> dict[str, float]:
        """批量查询当前库存（复用 SmartReplenishmentService）"""
        from .smart_replenishment import SmartReplenishmentService

        svc = SmartReplenishmentService()
        return await svc._fetch_current_stocks(store_id, tenant_id, ingredient_ids, db)

    async def _fetch_supplier_info(
        self,
        tenant_id: str,
        ingredient_ids: list[str],
        db: Any,
    ) -> dict[str, dict]:
        """查询食材的默认供应商信息（交期、包装规格、单价）。

        优雅降级：供应商表不存在或查询失败时，返回默认值。

        Returns:
            {ingredient_id: {supplier_id, lead_days, package_size, unit_cost_fen}}
        """
        if not ingredient_ids or db is None:
            return {}

        try:
            from sqlalchemy import text

            await db.execute(
                text("SELECT set_config('app.tenant_id', :tid, TRUE)"),
                {"tid": tenant_id},
            )
            result = await db.execute(
                text("""
                    SELECT
                        ism.ingredient_id::text,
                        ism.supplier_id::text,
                        COALESCE(ism.lead_days, :default_lead) AS lead_days,
                        COALESCE(ism.package_size, :default_pkg) AS package_size,
                        COALESCE(ism.last_price_fen, 0) AS unit_cost_fen
                    FROM ingredient_supplier_mapping ism
                    WHERE ism.tenant_id = :tenant_id
                      AND ism.ingredient_id = ANY(:ids::uuid[])
                      AND ism.is_primary = TRUE
                      AND ism.is_deleted = FALSE
                """),
                {
                    "tenant_id": tenant_id,
                    "ids": ingredient_ids,
                    "default_lead": DEFAULT_LEAD_DAYS,
                    "default_pkg": DEFAULT_PACKAGE_SIZE,
                },
            )
            rows = result.fetchall()
            return {
                row.ingredient_id: {
                    "supplier_id": row.supplier_id,
                    "lead_days": int(row.lead_days),
                    "package_size": float(row.package_size),
                    "unit_cost_fen": int(row.unit_cost_fen),
                }
                for row in rows
            }
        except Exception as exc:  # noqa: BLE001 — 最外层兜底：supplier表可能不存在
            log.warning(
                "procurement_forecast.supplier_info_fallback",
                error=str(exc),
                exc_info=True,
            )
            return {}

    async def _call_ai_summary(
        self,
        store_id: str,
        tenant_id: str,
        orders: list[SupplierOrder],
        total_amount_fen: int,
    ) -> str:
        """通过 ModelRouter 生成采购摘要（仅在总金额 > 1万时调用）。

        遵循 CLAUDE.md 规范：所有 AI 调用必须通过 ModelRouter，不直接调用 API。
        """
        try:
            from tx_agent.model_router import ModelRouter  # type: ignore[import]
        except ImportError:
            # 模块未就绪时降级，不影响主流程
            log.warning("procurement_forecast.model_router_not_available")
            return ""

        total_yuan = total_amount_fen / 100

        # 构建摘要上下文
        supplier_lines = []
        for order in orders:
            items_str = "、".join(f"{i.ingredient_name}×{i.purchase_qty}{i.unit}" for i in order.items)
            supplier_lines.append(
                f"供应商 {order.supplier_id}（交期{order.lead_days}天）：{items_str}，小计{order.total_fen // 100}元"
            )

        prompt = (
            f"请为以下采购计划生成简洁的中文摘要（100字内），重点说明总金额、主要食材和风险提示：\n"
            f"总金额：{total_yuan:.0f}元\n" + "\n".join(supplier_lines)
        )

        router = ModelRouter()
        summary = await router.complete(
            prompt=prompt,
            max_tokens=200,
            context="procurement_summary",
        )
        return summary or ""


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  辅助纯函数
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _calc_confidence(forecast_qty: float, current_stock: float) -> float:
    """根据预测数据质量估算置信度。

    规则：
      - forecast_qty > 0 且有库存数据 → 0.75（有历史数据支撑）
      - forecast_qty > 0 但 current_stock = 0 → 0.65（零库存可能是异常）
      - forecast_qty = 0 → 0.40（无历史消耗数据，置信度低）
    """
    if forecast_qty > 0 and current_stock >= 0:
        return 0.75 if current_stock > 0 else 0.65
    return 0.40
