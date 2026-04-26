"""MRP智能预估引擎 — 生产计划+采购计划联动

对标天财商龙SCM"精益管理"的MRP智能预估+按计划领料功能。

核心流程:
  1. create_forecast_plan — 创建预估计划
  2. calculate_demand — 销售预测→BOM展开→净需求计算
  3. generate_production_plan — 自制半成品生产建议
  4. generate_procurement_plan — 外购原料采购建议（匹配供应商+MOQ+前置时间）
  5. approve_plan — 审批计划
  6. convert_to_purchase_orders — 采购建议→采购订单
  7. convert_to_production_tasks — 生产建议→生产任务
  8. plan_material_issue / execute_material_issue — 按计划领料
  9. get_plan_summary / get_variance_report — 汇总与差异报告

Schema: v283_mrp_forecast_tables.py

# ROUTER REGISTRATION:
# from .api.mrp_routes import router as mrp_router
# app.include_router(mrp_router, prefix="/api/v1/supply/mrp")
"""

from __future__ import annotations

import math
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import structlog
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger(__name__)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  常量
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# 默认计划参数
DEFAULT_PARAMETERS = {
    "lookback_days": 30,
    "safety_stock_multiplier": 1.2,
    "lead_time_days": 2,
    "min_order_qty_enabled": True,
}

# 计划状态转换
PLAN_TRANSITIONS: Dict[str, List[str]] = {
    "draft": ["calculating", "cancelled"],
    "calculating": ["calculated", "draft"],  # 计算失败可回退
    "calculated": ["approved", "draft"],  # 驳回可回退
    "approved": ["executing"],
    "executing": ["completed"],
    "completed": [],
}

# 优先级权重（用于排序）
PRIORITY_WEIGHT: Dict[str, int] = {
    "urgent": 4,
    "high": 3,
    "medium": 2,
    "low": 1,
}

# BOM损耗率默认值
DEFAULT_WASTE_RATE = 0.03  # 3%


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now_utc().isoformat()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  数据模型
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class MRPPlanCreate(BaseModel):
    """创建预估计划请求"""
    plan_name: str = Field(..., min_length=1, max_length=200)
    plan_type: str = Field(default="demand_driven", pattern="^(demand_driven|manual|hybrid)$")
    store_id: Optional[str] = None  # null=集团级别
    forecast_date_from: date
    forecast_date_to: date
    parameters: Dict[str, Any] = Field(default_factory=lambda: DEFAULT_PARAMETERS.copy())


class MRPPlanInfo(BaseModel):
    """计划信息"""
    id: str
    tenant_id: str
    store_id: Optional[str] = None
    plan_name: str
    plan_type: str
    status: str
    forecast_date_from: date
    forecast_date_to: date
    parameters: Dict[str, Any]
    created_by: str
    approved_by: Optional[str] = None
    approved_at: Optional[str] = None
    created_at: str
    updated_at: str


class DemandLineInfo(BaseModel):
    """需求行"""
    id: str
    plan_id: str
    ingredient_id: str
    ingredient_name: str
    unit: str
    forecast_demand_qty: float
    safety_stock_qty: float
    current_stock_qty: float
    in_transit_qty: float
    net_requirement_qty: float
    source: str


class ProductionSuggestionInfo(BaseModel):
    """生产建议"""
    id: str
    plan_id: str
    product_id: str
    product_name: str
    suggested_qty: float
    unit: str
    bom_id: Optional[str] = None
    required_date: date
    priority: str
    status: str


class ProcurementSuggestionInfo(BaseModel):
    """采购建议"""
    id: str
    plan_id: str
    ingredient_id: str
    ingredient_name: str
    suggested_qty: float
    unit: str
    supplier_id: Optional[str] = None
    supplier_name: Optional[str] = None
    estimated_cost_fen: int
    required_date: date
    lead_time_days: int
    status: str
    purchase_order_id: Optional[str] = None


class PlannedIssueInfo(BaseModel):
    """领料单"""
    id: str
    production_suggestion_id: str
    ingredient_id: str
    ingredient_name: str
    planned_qty: float
    actual_qty: Optional[float] = None
    unit: str
    issued_at: Optional[str] = None
    issued_by: Optional[str] = None
    status: str
    variance_qty: Optional[float] = None


class PlanSummary(BaseModel):
    """计划总览"""
    plan: MRPPlanInfo
    demand_lines_count: int
    total_forecast_demand_qty: float
    total_net_requirement_qty: float
    production_suggestions_count: int
    production_completed_count: int
    procurement_suggestions_count: int
    procurement_ordered_count: int
    total_estimated_cost_fen: int
    planned_issues_count: int
    issued_count: int


class VarianceItem(BaseModel):
    """差异行"""
    ingredient_id: str
    ingredient_name: str
    planned_qty: float
    actual_qty: float
    variance_qty: float
    variance_pct: float  # 差异百分比


class VarianceReport(BaseModel):
    """差异报告"""
    plan_id: str
    items: List[VarianceItem]
    total_planned: float
    total_actual: float
    overall_variance_pct: float


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  主服务
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class MRPEngineService:
    """MRP智能预估引擎

    create_forecast_plan       — 创建预估计划
    calculate_demand           — 需求计算（销售预测→BOM展开→净需求）
    generate_production_plan   — 生成生产建议
    generate_procurement_plan  — 生成采购建议
    approve_plan               — 审批计划
    convert_to_purchase_orders — 采购建议→采购订单
    convert_to_production_tasks— 生产建议→生产任务
    plan_material_issue        — 生成领料单
    execute_material_issue     — 执行领料
    get_plan_summary           — 计划总览
    get_variance_report        — 差异报告
    """

    # ─── 内部工具 ───

    async def _set_tenant(self, db: AsyncSession, tenant_id: str) -> None:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": tenant_id},
        )

    def _validate_transition(self, current: str, target: str) -> None:
        """校验计划状态转换"""
        allowed = PLAN_TRANSITIONS.get(current, [])
        if target not in allowed:
            raise ValueError(
                f"计划状态不允许从 '{current}' 转换到 '{target}'，"
                f"允许的目标状态: {allowed}"
            )

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  1. 创建预估计划
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    async def create_forecast_plan(
        self,
        tenant_id: str,
        created_by: str,
        plan_data: MRPPlanCreate,
        db: AsyncSession,
    ) -> MRPPlanInfo:
        """创建MRP预估计划

        Args:
            tenant_id: 租户ID
            created_by: 创建人ID
            plan_data: 计划数据
            db: 数据库会话

        Returns:
            MRPPlanInfo 创建后的计划信息
        """
        _log = log.bind(tenant_id=tenant_id, plan_name=plan_data.plan_name)
        await self._set_tenant(db, tenant_id)

        if plan_data.forecast_date_to < plan_data.forecast_date_from:
            raise ValueError("预测结束日期不能早于开始日期")

        # 合并默认参数
        params = {**DEFAULT_PARAMETERS, **plan_data.parameters}

        result = await db.execute(
            text("""
                INSERT INTO mrp_forecast_plans
                    (tenant_id, store_id, plan_name, plan_type, status,
                     forecast_date_from, forecast_date_to, parameters, created_by)
                VALUES
                    (:tenant_id, :store_id, :plan_name, :plan_type, 'draft',
                     :date_from, :date_to, :parameters::jsonb, :created_by)
                RETURNING id, created_at, updated_at
            """),
            {
                "tenant_id": tenant_id,
                "store_id": plan_data.store_id,
                "plan_name": plan_data.plan_name,
                "plan_type": plan_data.plan_type,
                "date_from": plan_data.forecast_date_from.isoformat(),
                "date_to": plan_data.forecast_date_to.isoformat(),
                "parameters": __import__("json").dumps(params),
                "created_by": created_by,
            },
        )
        row = result.mappings().fetchone()
        await db.commit()

        _log.info("mrp.plan.created", plan_id=str(row["id"]))

        return MRPPlanInfo(
            id=str(row["id"]),
            tenant_id=tenant_id,
            store_id=plan_data.store_id,
            plan_name=plan_data.plan_name,
            plan_type=plan_data.plan_type,
            status="draft",
            forecast_date_from=plan_data.forecast_date_from,
            forecast_date_to=plan_data.forecast_date_to,
            parameters=params,
            created_by=created_by,
            approved_by=None,
            approved_at=None,
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  获取计划
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    async def get_plan(
        self,
        tenant_id: str,
        plan_id: str,
        db: AsyncSession,
    ) -> MRPPlanInfo:
        """获取单个计划详情"""
        await self._set_tenant(db, tenant_id)

        result = await db.execute(
            text("""
                SELECT id, tenant_id, store_id, plan_name, plan_type, status,
                       forecast_date_from, forecast_date_to, parameters,
                       created_by, approved_by, approved_at, created_at, updated_at
                FROM mrp_forecast_plans
                WHERE id = :plan_id AND is_deleted = false
            """),
            {"plan_id": plan_id},
        )
        row = result.mappings().fetchone()
        if not row:
            raise ValueError(f"计划不存在: {plan_id}")

        return self._row_to_plan_info(row)

    async def list_plans(
        self,
        tenant_id: str,
        db: AsyncSession,
        store_id: Optional[str] = None,
        status: Optional[str] = None,
        page: int = 1,
        size: int = 20,
    ) -> Dict[str, Any]:
        """计划列表（分页）"""
        await self._set_tenant(db, tenant_id)

        conditions = ["is_deleted = false"]
        params: Dict[str, Any] = {"limit": size, "offset": (page - 1) * size}

        if store_id:
            conditions.append("store_id = :store_id")
            params["store_id"] = store_id
        if status:
            conditions.append("status = :status")
            params["status"] = status

        where_clause = " AND ".join(conditions)

        # 查总数
        count_result = await db.execute(
            text(f"SELECT COUNT(*) FROM mrp_forecast_plans WHERE {where_clause}"),
            params,
        )
        total = count_result.scalar() or 0

        # 查列表
        result = await db.execute(
            text(f"""
                SELECT id, tenant_id, store_id, plan_name, plan_type, status,
                       forecast_date_from, forecast_date_to, parameters,
                       created_by, approved_by, approved_at, created_at, updated_at
                FROM mrp_forecast_plans
                WHERE {where_clause}
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
            """),
            params,
        )
        rows = result.mappings().fetchall()

        return {
            "items": [self._row_to_plan_info(r).model_dump() for r in rows],
            "total": total,
        }

    def _row_to_plan_info(self, row: Any) -> MRPPlanInfo:
        """行数据转计划模型"""
        return MRPPlanInfo(
            id=str(row["id"]),
            tenant_id=str(row["tenant_id"]),
            store_id=str(row["store_id"]) if row["store_id"] else None,
            plan_name=row["plan_name"],
            plan_type=row["plan_type"],
            status=row["status"],
            forecast_date_from=row["forecast_date_from"],
            forecast_date_to=row["forecast_date_to"],
            parameters=row["parameters"] if isinstance(row["parameters"], dict) else {},
            created_by=str(row["created_by"]),
            approved_by=str(row["approved_by"]) if row["approved_by"] else None,
            approved_at=str(row["approved_at"]) if row["approved_at"] else None,
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  2. 需求计算
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    async def calculate_demand(
        self,
        tenant_id: str,
        plan_id: str,
        db: AsyncSession,
    ) -> List[DemandLineInfo]:
        """执行需求计算

        流程：
          1) 获取预测期内销售预测（历史加权平均）
          2) BOM展开: 菜品需求→原料需求（考虑损耗率）
          3) 计算净需求 = 预测需求 + 安全库存 - 当前库存 - 在途库存
          4) 生成 demand_lines

        Args:
            tenant_id: 租户ID
            plan_id: 计划ID
            db: 数据库会话

        Returns:
            List[DemandLineInfo] 需求行列表
        """
        _log = log.bind(tenant_id=tenant_id, plan_id=plan_id)
        await self._set_tenant(db, tenant_id)

        # 获取计划并校验状态
        plan = await self.get_plan(tenant_id, plan_id, db)
        self._validate_transition(plan.status, "calculating")

        # 更新状态为 calculating
        await db.execute(
            text("""
                UPDATE mrp_forecast_plans
                SET status = 'calculating', updated_at = NOW()
                WHERE id = :plan_id
            """),
            {"plan_id": plan_id},
        )

        # 清理旧的需求行
        await db.execute(
            text("DELETE FROM mrp_demand_lines WHERE plan_id = :plan_id"),
            {"plan_id": plan_id},
        )

        params = plan.parameters
        lookback_days = params.get("lookback_days", 30)
        safety_multiplier = params.get("safety_stock_multiplier", 1.2)
        lead_time_days = params.get("lead_time_days", 2)

        forecast_days = (plan.forecast_date_to - plan.forecast_date_from).days + 1

        try:
            # Step 1: 获取历史销售数据，计算日均消耗
            ingredient_demand = await self._calc_forecast_demand(
                db, tenant_id, plan.store_id, lookback_days, forecast_days,
            )

            # Step 2: BOM展开补充（菜品级预测→原料级需求）
            bom_demand = await self._bom_explosion(
                db, tenant_id, plan.store_id, lookback_days, forecast_days,
            )
            # 合并BOM展开的需求
            for iid, info in bom_demand.items():
                if iid in ingredient_demand:
                    ingredient_demand[iid]["forecast_qty"] += info["forecast_qty"]
                    ingredient_demand[iid]["source"] = "bom_explosion"
                else:
                    ingredient_demand[iid] = info

            # Step 3: 查询当前库存和在途库存
            ingredient_ids = list(ingredient_demand.keys())
            if not ingredient_ids:
                _log.info("mrp.calculate.no_demand")
                await db.execute(
                    text("""
                        UPDATE mrp_forecast_plans
                        SET status = 'calculated', updated_at = NOW()
                        WHERE id = :plan_id
                    """),
                    {"plan_id": plan_id},
                )
                await db.commit()
                return []

            current_stocks = await self._fetch_current_stocks(
                db, tenant_id, plan.store_id, ingredient_ids,
            )
            in_transit = await self._fetch_in_transit(
                db, tenant_id, plan.store_id, ingredient_ids,
            )

            # Step 4: 计算净需求并写入 demand_lines
            demand_lines: List[DemandLineInfo] = []

            for iid, info in ingredient_demand.items():
                forecast_qty = info["forecast_qty"]
                # 安全库存 = 日均消耗 x 前置时间 x 安全系数
                daily_avg = forecast_qty / forecast_days if forecast_days > 0 else 0
                safety_qty = daily_avg * lead_time_days * safety_multiplier
                current_qty = current_stocks.get(iid, 0.0)
                transit_qty = in_transit.get(iid, 0.0)

                # 净需求 = 预测需求 + 安全库存 - 当前库存 - 在途库存
                net_req = max(0, forecast_qty + safety_qty - current_qty - transit_qty)

                result = await db.execute(
                    text("""
                        INSERT INTO mrp_demand_lines
                            (tenant_id, plan_id, ingredient_id, ingredient_name, unit,
                             forecast_demand_qty, safety_stock_qty, current_stock_qty,
                             in_transit_qty, net_requirement_qty, source)
                        VALUES
                            (:tenant_id, :plan_id, :ingredient_id, :ingredient_name, :unit,
                             :forecast_qty, :safety_qty, :current_qty,
                             :transit_qty, :net_req, :source)
                        RETURNING id
                    """),
                    {
                        "tenant_id": tenant_id,
                        "plan_id": plan_id,
                        "ingredient_id": iid,
                        "ingredient_name": info.get("name", ""),
                        "unit": info.get("unit", ""),
                        "forecast_qty": round(forecast_qty, 3),
                        "safety_qty": round(safety_qty, 3),
                        "current_qty": round(current_qty, 3),
                        "transit_qty": round(transit_qty, 3),
                        "net_req": round(net_req, 3),
                        "source": info.get("source", "sales_forecast"),
                    },
                )
                row = result.mappings().fetchone()

                demand_lines.append(DemandLineInfo(
                    id=str(row["id"]),
                    plan_id=plan_id,
                    ingredient_id=iid,
                    ingredient_name=info.get("name", ""),
                    unit=info.get("unit", ""),
                    forecast_demand_qty=round(forecast_qty, 3),
                    safety_stock_qty=round(safety_qty, 3),
                    current_stock_qty=round(current_qty, 3),
                    in_transit_qty=round(transit_qty, 3),
                    net_requirement_qty=round(net_req, 3),
                    source=info.get("source", "sales_forecast"),
                ))

            # 更新状态为 calculated
            await db.execute(
                text("""
                    UPDATE mrp_forecast_plans
                    SET status = 'calculated', updated_at = NOW()
                    WHERE id = :plan_id
                """),
                {"plan_id": plan_id},
            )
            await db.commit()

            _log.info("mrp.calculate.done", demand_lines_count=len(demand_lines))
            return demand_lines

        except Exception:
            # 计算失败，回退状态为 draft
            await db.execute(
                text("""
                    UPDATE mrp_forecast_plans
                    SET status = 'draft', updated_at = NOW()
                    WHERE id = :plan_id
                """),
                {"plan_id": plan_id},
            )
            await db.commit()
            _log.exception("mrp.calculate.failed")
            raise

    # ─── 需求计算内部方法 ───

    async def _calc_forecast_demand(
        self,
        db: AsyncSession,
        tenant_id: str,
        store_id: Optional[str],
        lookback_days: int,
        forecast_days: int,
    ) -> Dict[str, Dict[str, Any]]:
        """从出库记录计算原料级预测需求

        策略：近N天日均消耗 x 预测天数
        结果: {ingredient_id: {"forecast_qty": float, "name": str, "unit": str, "source": str}}
        """
        store_filter = "AND store_id = :store_id" if store_id else ""
        params: Dict[str, Any] = {"lookback": lookback_days}
        if store_id:
            params["store_id"] = store_id

        result = await db.execute(
            text(f"""
                SELECT
                    ingredient_id,
                    MAX(ingredient_name) AS ingredient_name,
                    MAX(unit) AS unit,
                    COALESCE(SUM(ABS(quantity)), 0) AS total_consumed
                FROM inventory_transactions
                WHERE transaction_type IN ('usage', 'deduction', 'waste')
                  AND created_at >= NOW() - INTERVAL '1 day' * :lookback
                  AND is_deleted = false
                  {store_filter}
                GROUP BY ingredient_id
                HAVING SUM(ABS(quantity)) > 0
            """),
            params,
        )
        rows = result.mappings().fetchall()

        demand_map: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            iid = str(row["ingredient_id"])
            total = float(row["total_consumed"])
            daily_avg = total / lookback_days if lookback_days > 0 else 0
            demand_map[iid] = {
                "forecast_qty": round(daily_avg * forecast_days, 3),
                "name": row["ingredient_name"] or "",
                "unit": row["unit"] or "",
                "source": "sales_forecast",
            }

        return demand_map

    async def _bom_explosion(
        self,
        db: AsyncSession,
        tenant_id: str,
        store_id: Optional[str],
        lookback_days: int,
        forecast_days: int,
    ) -> Dict[str, Dict[str, Any]]:
        """BOM展开: 菜品销量→原料需求（补充直接出库记录不足的部分）

        从订单明细统计菜品销量，通过BOM配方展开为原料需求。
        考虑损耗率（waste_rate）。
        """
        store_filter = "AND o.store_id = :store_id" if store_id else ""
        params: Dict[str, Any] = {"lookback": lookback_days}
        if store_id:
            params["store_id"] = store_id

        # 查询近N天菜品销售量
        dish_result = await db.execute(
            text(f"""
                SELECT
                    oi.dish_id,
                    SUM(oi.quantity) AS total_sold
                FROM order_items oi
                JOIN orders o ON o.id = oi.order_id
                WHERE o.status IN ('paid', 'completed')
                  AND o.created_at >= NOW() - INTERVAL '1 day' * :lookback
                  AND o.is_deleted = false
                  {store_filter}
                GROUP BY oi.dish_id
                HAVING SUM(oi.quantity) > 0
            """),
            params,
        )
        dish_rows = dish_result.mappings().fetchall()

        if not dish_rows:
            return {}

        dish_ids = [str(r["dish_id"]) for r in dish_rows]
        dish_qty_map = {str(r["dish_id"]): float(r["total_sold"]) for r in dish_rows}

        # 查询BOM配方
        bom_result = await db.execute(
            text("""
                SELECT
                    bi.dish_id,
                    bi.ingredient_id,
                    bi.ingredient_name,
                    bi.quantity AS bom_qty,
                    bi.unit,
                    COALESCE(bi.waste_rate, :default_waste) AS waste_rate
                FROM bom_items bi
                WHERE bi.dish_id = ANY(:dish_ids::uuid[])
                  AND bi.is_deleted = false
            """),
            {"dish_ids": dish_ids, "default_waste": DEFAULT_WASTE_RATE},
        )
        bom_rows = bom_result.mappings().fetchall()

        # 展开计算
        bom_demand: Dict[str, Dict[str, Any]] = {}
        for bom in bom_rows:
            dish_id = str(bom["dish_id"])
            iid = str(bom["ingredient_id"])
            dish_sold = dish_qty_map.get(dish_id, 0)
            bom_qty = float(bom["bom_qty"])
            waste_rate = float(bom["waste_rate"])

            # 日均销量 x BOM用量 x (1 + 损耗率) x 预测天数
            daily_dish = dish_sold / lookback_days if lookback_days > 0 else 0
            ingredient_need = daily_dish * bom_qty * (1 + waste_rate) * forecast_days

            if iid in bom_demand:
                bom_demand[iid]["forecast_qty"] += round(ingredient_need, 3)
            else:
                bom_demand[iid] = {
                    "forecast_qty": round(ingredient_need, 3),
                    "name": bom["ingredient_name"] or "",
                    "unit": bom["unit"] or "",
                    "source": "bom_explosion",
                }

        return bom_demand

    async def _fetch_current_stocks(
        self,
        db: AsyncSession,
        tenant_id: str,
        store_id: Optional[str],
        ingredient_ids: List[str],
    ) -> Dict[str, float]:
        """查询当前库存"""
        if not ingredient_ids:
            return {}

        store_filter = "AND store_id = :store_id" if store_id else ""
        params: Dict[str, Any] = {"ids": ingredient_ids}
        if store_id:
            params["store_id"] = store_id

        result = await db.execute(
            text(f"""
                SELECT ingredient_id, COALESCE(SUM(quantity), 0) AS qty
                FROM inventory_stocks
                WHERE ingredient_id = ANY(:ids::uuid[])
                  AND is_deleted = false
                  {store_filter}
                GROUP BY ingredient_id
            """),
            params,
        )
        rows = result.mappings().fetchall()
        return {str(r["ingredient_id"]): float(r["qty"]) for r in rows}

    async def _fetch_in_transit(
        self,
        db: AsyncSession,
        tenant_id: str,
        store_id: Optional[str],
        ingredient_ids: List[str],
    ) -> Dict[str, float]:
        """查询在途库存（已下单未收货的采购量）"""
        if not ingredient_ids:
            return {}

        store_filter = "AND po.store_id = :store_id" if store_id else ""
        params: Dict[str, Any] = {"ids": ingredient_ids}
        if store_id:
            params["store_id"] = store_id

        result = await db.execute(
            text(f"""
                SELECT
                    poi.ingredient_id,
                    COALESCE(SUM(poi.quantity), 0) AS qty
                FROM purchase_order_items poi
                JOIN purchase_orders po ON po.id = poi.purchase_order_id
                WHERE poi.ingredient_id = ANY(:ids::uuid[])
                  AND po.status IN ('ordered', 'approved', 'pending_delivery')
                  AND po.is_deleted = false
                  {store_filter}
                GROUP BY poi.ingredient_id
            """),
            params,
        )
        rows = result.mappings().fetchall()
        return {str(r["ingredient_id"]): float(r["qty"]) for r in rows}

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  3. 生成生产建议
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    async def generate_production_plan(
        self,
        tenant_id: str,
        plan_id: str,
        db: AsyncSession,
    ) -> List[ProductionSuggestionInfo]:
        """生成生产建议

        流程：
          1) 筛选需要自制的半成品（有BOM且标记为自产）
          2) 按BOM计算生产数量
          3) 按交期排序优先级

        Args:
            tenant_id: 租户ID
            plan_id: 计划ID
            db: 数据库会话

        Returns:
            List[ProductionSuggestionInfo]
        """
        _log = log.bind(tenant_id=tenant_id, plan_id=plan_id)
        await self._set_tenant(db, tenant_id)

        plan = await self.get_plan(tenant_id, plan_id, db)
        if plan.status not in ("calculated", "approved"):
            raise ValueError(f"计划状态 '{plan.status}' 不支持生成生产建议，需为 calculated 或 approved")

        # 清理旧的生产建议（先清领料单）
        await db.execute(
            text("""
                DELETE FROM mrp_planned_issues
                WHERE production_suggestion_id IN (
                    SELECT id FROM mrp_production_suggestions WHERE plan_id = :plan_id
                )
            """),
            {"plan_id": plan_id},
        )
        await db.execute(
            text("DELETE FROM mrp_production_suggestions WHERE plan_id = :plan_id"),
            {"plan_id": plan_id},
        )

        # 查询需求行中有BOM且为自产的原料/半成品
        # 自产标识: bom_recipes 表中 production_type = 'self'
        result = await db.execute(
            text("""
                SELECT
                    dl.ingredient_id,
                    dl.ingredient_name,
                    dl.unit,
                    dl.net_requirement_qty,
                    br.id AS bom_id,
                    br.product_name
                FROM mrp_demand_lines dl
                JOIN bom_recipes br ON br.output_ingredient_id = dl.ingredient_id
                    AND br.is_deleted = false
                    AND br.production_type = 'self'
                WHERE dl.plan_id = :plan_id
                  AND dl.net_requirement_qty > 0
                  AND dl.is_deleted = false
            """),
            {"plan_id": plan_id},
        )
        rows = result.mappings().fetchall()

        if not rows:
            _log.info("mrp.production.no_self_made")
            return []

        # 计算required_date和priority
        lead_time = plan.parameters.get("lead_time_days", 2)
        required_date = plan.forecast_date_from - timedelta(days=lead_time)
        today = date.today()

        suggestions: List[ProductionSuggestionInfo] = []
        for row in rows:
            # 优先级判定: 距离交期越近越紧急
            days_until = (required_date - today).days
            if days_until <= 0:
                priority = "urgent"
            elif days_until <= 1:
                priority = "high"
            elif days_until <= 3:
                priority = "medium"
            else:
                priority = "low"

            ins_result = await db.execute(
                text("""
                    INSERT INTO mrp_production_suggestions
                        (tenant_id, plan_id, product_id, product_name, suggested_qty,
                         unit, bom_id, required_date, priority, status)
                    VALUES
                        (:tenant_id, :plan_id, :product_id, :product_name, :suggested_qty,
                         :unit, :bom_id, :required_date, :priority, 'suggested')
                    RETURNING id
                """),
                {
                    "tenant_id": tenant_id,
                    "plan_id": plan_id,
                    "product_id": str(row["ingredient_id"]),
                    "product_name": row["product_name"] or row["ingredient_name"],
                    "suggested_qty": float(row["net_requirement_qty"]),
                    "unit": row["unit"] or "",
                    "bom_id": str(row["bom_id"]),
                    "required_date": required_date.isoformat(),
                    "priority": priority,
                },
            )
            ins_row = ins_result.mappings().fetchone()

            suggestions.append(ProductionSuggestionInfo(
                id=str(ins_row["id"]),
                plan_id=plan_id,
                product_id=str(row["ingredient_id"]),
                product_name=row["product_name"] or row["ingredient_name"],
                suggested_qty=float(row["net_requirement_qty"]),
                unit=row["unit"] or "",
                bom_id=str(row["bom_id"]),
                required_date=required_date,
                priority=priority,
                status="suggested",
            ))

        await db.commit()

        # 按优先级排序
        suggestions.sort(key=lambda s: PRIORITY_WEIGHT.get(s.priority, 0), reverse=True)

        _log.info("mrp.production.generated", count=len(suggestions))
        return suggestions

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  4. 生成采购建议
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    async def generate_procurement_plan(
        self,
        tenant_id: str,
        plan_id: str,
        db: AsyncSession,
    ) -> List[ProcurementSuggestionInfo]:
        """生成采购建议

        流程：
          1) 筛选需要外购的原料（net_requirement > 0，排除自产）
          2) 匹配供应商（按评分优先）
          3) 考虑最小订货量（MOQ）和前置时间
          4) 估算采购金额

        Args:
            tenant_id: 租户ID
            plan_id: 计划ID
            db: 数据库会话

        Returns:
            List[ProcurementSuggestionInfo]
        """
        _log = log.bind(tenant_id=tenant_id, plan_id=plan_id)
        await self._set_tenant(db, tenant_id)

        plan = await self.get_plan(tenant_id, plan_id, db)
        if plan.status not in ("calculated", "approved"):
            raise ValueError(f"计划状态 '{plan.status}' 不支持生成采购建议，需为 calculated 或 approved")

        min_order_qty_enabled = plan.parameters.get("min_order_qty_enabled", True)
        lead_time_days = plan.parameters.get("lead_time_days", 2)

        # 清理旧的采购建议
        await db.execute(
            text("DELETE FROM mrp_procurement_suggestions WHERE plan_id = :plan_id"),
            {"plan_id": plan_id},
        )

        # 查询需要外购的需求行（排除有自产BOM的）
        result = await db.execute(
            text("""
                SELECT
                    dl.ingredient_id,
                    dl.ingredient_name,
                    dl.unit,
                    dl.net_requirement_qty
                FROM mrp_demand_lines dl
                LEFT JOIN bom_recipes br ON br.output_ingredient_id = dl.ingredient_id
                    AND br.is_deleted = false
                    AND br.production_type = 'self'
                WHERE dl.plan_id = :plan_id
                  AND dl.net_requirement_qty > 0
                  AND dl.is_deleted = false
                  AND br.id IS NULL
            """),
            {"plan_id": plan_id},
        )
        demand_rows = result.mappings().fetchall()

        if not demand_rows:
            _log.info("mrp.procurement.no_external_demand")
            return []

        # 查询供应商信息（按评分排序取最优）
        ingredient_ids = [str(r["ingredient_id"]) for r in demand_rows]
        supplier_map = await self._match_suppliers(db, tenant_id, ingredient_ids)

        # 查询MOQ配置
        moq_map = await self._fetch_moq(db, tenant_id, ingredient_ids)

        # 查询最近采购单价
        price_map = await self._fetch_latest_prices(db, tenant_id, ingredient_ids)

        required_date = plan.forecast_date_from - timedelta(days=lead_time_days)

        suggestions: List[ProcurementSuggestionInfo] = []
        for row in demand_rows:
            iid = str(row["ingredient_id"])
            net_qty = float(row["net_requirement_qty"])

            # 考虑MOQ
            if min_order_qty_enabled:
                moq = moq_map.get(iid, 1.0)
                if moq > 0 and net_qty > 0:
                    net_qty = max(net_qty, moq)
                    # 按MOQ向上取整
                    net_qty = math.ceil(net_qty / moq) * moq

            # 匹配供应商
            supplier = supplier_map.get(iid)
            supplier_id = supplier["id"] if supplier else None
            supplier_name = supplier["name"] if supplier else None
            actual_lead_time = supplier.get("lead_time_days", lead_time_days) if supplier else lead_time_days

            # 估算金额
            unit_price_fen = price_map.get(iid, 0)
            estimated_cost_fen = int(net_qty * unit_price_fen)

            ins_result = await db.execute(
                text("""
                    INSERT INTO mrp_procurement_suggestions
                        (tenant_id, plan_id, ingredient_id, ingredient_name,
                         suggested_qty, unit, supplier_id, supplier_name,
                         estimated_cost_fen, required_date, lead_time_days, status)
                    VALUES
                        (:tenant_id, :plan_id, :ingredient_id, :ingredient_name,
                         :suggested_qty, :unit, :supplier_id, :supplier_name,
                         :estimated_cost_fen, :required_date, :lead_time_days, 'suggested')
                    RETURNING id
                """),
                {
                    "tenant_id": tenant_id,
                    "plan_id": plan_id,
                    "ingredient_id": iid,
                    "ingredient_name": row["ingredient_name"],
                    "suggested_qty": round(net_qty, 3),
                    "unit": row["unit"] or "",
                    "supplier_id": supplier_id,
                    "supplier_name": supplier_name,
                    "estimated_cost_fen": estimated_cost_fen,
                    "required_date": required_date.isoformat(),
                    "lead_time_days": actual_lead_time,
                },
            )
            ins_row = ins_result.mappings().fetchone()

            suggestions.append(ProcurementSuggestionInfo(
                id=str(ins_row["id"]),
                plan_id=plan_id,
                ingredient_id=iid,
                ingredient_name=row["ingredient_name"],
                suggested_qty=round(net_qty, 3),
                unit=row["unit"] or "",
                supplier_id=supplier_id,
                supplier_name=supplier_name,
                estimated_cost_fen=estimated_cost_fen,
                required_date=required_date,
                lead_time_days=actual_lead_time,
                status="suggested",
                purchase_order_id=None,
            ))

        await db.commit()

        _log.info(
            "mrp.procurement.generated",
            count=len(suggestions),
            total_cost_fen=sum(s.estimated_cost_fen for s in suggestions),
        )
        return suggestions

    # ─── 采购建议内部方法 ───

    async def _match_suppliers(
        self,
        db: AsyncSession,
        tenant_id: str,
        ingredient_ids: List[str],
    ) -> Dict[str, Dict[str, Any]]:
        """按评分匹配最优供应商"""
        if not ingredient_ids:
            return {}

        result = await db.execute(
            text("""
                SELECT DISTINCT ON (si.ingredient_id)
                    si.ingredient_id,
                    s.id AS supplier_id,
                    s.name AS supplier_name,
                    si.lead_time_days,
                    COALESCE(ss.total_score, 60) AS score
                FROM supplier_ingredients si
                JOIN suppliers s ON s.id = si.supplier_id AND s.is_deleted = false
                LEFT JOIN supplier_scores ss ON ss.supplier_id = s.id
                WHERE si.ingredient_id = ANY(:ids::uuid[])
                  AND si.is_deleted = false
                ORDER BY si.ingredient_id, COALESCE(ss.total_score, 60) DESC
            """),
            {"ids": ingredient_ids},
        )
        rows = result.mappings().fetchall()
        return {
            str(r["ingredient_id"]): {
                "id": str(r["supplier_id"]),
                "name": r["supplier_name"],
                "lead_time_days": r["lead_time_days"] or 2,
            }
            for r in rows
        }

    async def _fetch_moq(
        self,
        db: AsyncSession,
        tenant_id: str,
        ingredient_ids: List[str],
    ) -> Dict[str, float]:
        """获取最小订货量配置"""
        if not ingredient_ids:
            return {}

        result = await db.execute(
            text("""
                SELECT ingredient_id, min_order_qty
                FROM inventory_thresholds
                WHERE ingredient_id = ANY(:ids::uuid[])
                  AND min_order_qty > 0
            """),
            {"ids": ingredient_ids},
        )
        rows = result.mappings().fetchall()
        return {str(r["ingredient_id"]): float(r["min_order_qty"]) for r in rows}

    async def _fetch_latest_prices(
        self,
        db: AsyncSession,
        tenant_id: str,
        ingredient_ids: List[str],
    ) -> Dict[str, int]:
        """获取最近采购单价（分/单位）"""
        if not ingredient_ids:
            return {}

        result = await db.execute(
            text("""
                SELECT DISTINCT ON (ingredient_id)
                    ingredient_id,
                    unit_price_fen
                FROM purchase_order_items
                WHERE ingredient_id = ANY(:ids::uuid[])
                  AND is_deleted = false
                ORDER BY ingredient_id, created_at DESC
            """),
            {"ids": ingredient_ids},
        )
        rows = result.mappings().fetchall()
        return {str(r["ingredient_id"]): int(r["unit_price_fen"]) for r in rows}

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  5. 审批计划
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    async def approve_plan(
        self,
        tenant_id: str,
        plan_id: str,
        approved_by: str,
        db: AsyncSession,
    ) -> MRPPlanInfo:
        """审批MRP计划

        Args:
            tenant_id: 租户ID
            plan_id: 计划ID
            approved_by: 审批人ID
            db: 数据库会话

        Returns:
            MRPPlanInfo 审批后的计划信息
        """
        _log = log.bind(tenant_id=tenant_id, plan_id=plan_id, approved_by=approved_by)
        await self._set_tenant(db, tenant_id)

        plan = await self.get_plan(tenant_id, plan_id, db)
        self._validate_transition(plan.status, "approved")

        await db.execute(
            text("""
                UPDATE mrp_forecast_plans
                SET status = 'approved',
                    approved_by = :approved_by,
                    approved_at = NOW(),
                    updated_at = NOW()
                WHERE id = :plan_id
            """),
            {"plan_id": plan_id, "approved_by": approved_by},
        )

        # 同步审批生产建议和采购建议
        await db.execute(
            text("""
                UPDATE mrp_production_suggestions
                SET status = 'approved', updated_at = NOW()
                WHERE plan_id = :plan_id AND status = 'suggested'
                  AND is_deleted = false
            """),
            {"plan_id": plan_id},
        )
        await db.execute(
            text("""
                UPDATE mrp_procurement_suggestions
                SET status = 'approved', updated_at = NOW()
                WHERE plan_id = :plan_id AND status = 'suggested'
                  AND is_deleted = false
            """),
            {"plan_id": plan_id},
        )

        await db.commit()
        _log.info("mrp.plan.approved")

        return await self.get_plan(tenant_id, plan_id, db)

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  6. 采购建议→采购订单
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    async def convert_to_purchase_orders(
        self,
        tenant_id: str,
        plan_id: str,
        suggestion_ids: List[str],
        db: AsyncSession,
    ) -> List[Dict[str, Any]]:
        """将采购建议转为采购订单

        按供应商分组创建采购订单。

        Args:
            tenant_id: 租户ID
            plan_id: 计划ID
            suggestion_ids: 要转换的采购建议ID列表
            db: 数据库会话

        Returns:
            创建的采购订单列表
        """
        _log = log.bind(tenant_id=tenant_id, plan_id=plan_id)
        await self._set_tenant(db, tenant_id)

        if not suggestion_ids:
            raise ValueError("采购建议ID列表不能为空")

        # 查询选中的采购建议
        result = await db.execute(
            text("""
                SELECT id, ingredient_id, ingredient_name, suggested_qty, unit,
                       supplier_id, supplier_name, estimated_cost_fen, required_date,
                       lead_time_days, status
                FROM mrp_procurement_suggestions
                WHERE id = ANY(:ids::uuid[])
                  AND plan_id = :plan_id
                  AND status = 'approved'
                  AND is_deleted = false
            """),
            {"ids": suggestion_ids, "plan_id": plan_id},
        )
        rows = result.mappings().fetchall()

        if not rows:
            raise ValueError("未找到可转换的已审批采购建议")

        # 按供应商分组
        by_supplier: Dict[Optional[str], List[Any]] = {}
        for row in rows:
            sid = str(row["supplier_id"]) if row["supplier_id"] else None
            by_supplier.setdefault(sid, []).append(row)

        created_orders: List[Dict[str, Any]] = []
        now_str = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")

        for supplier_id, items in by_supplier.items():
            po_no = f"MRP-PO{now_str}{uuid.uuid4().hex[:4].upper()}"
            total_fen = sum(int(item["estimated_cost_fen"]) for item in items)
            supplier_name = items[0]["supplier_name"] if items[0]["supplier_name"] else "未指定供应商"

            # 创建采购订单
            po_result = await db.execute(
                text("""
                    INSERT INTO purchase_orders
                        (tenant_id, order_no, supplier_id, supplier_name,
                         status, total_amount_fen, source, notes)
                    VALUES
                        (:tenant_id, :order_no, :supplier_id, :supplier_name,
                         'draft', :total_fen, 'mrp', :notes)
                    RETURNING id
                """),
                {
                    "tenant_id": tenant_id,
                    "order_no": po_no,
                    "supplier_id": supplier_id,
                    "supplier_name": supplier_name,
                    "total_fen": total_fen,
                    "notes": f"MRP计划 {plan_id} 自动生成",
                },
            )
            po_row = po_result.mappings().fetchone()
            po_id = str(po_row["id"])

            # 创建采购订单行
            for item in items:
                await db.execute(
                    text("""
                        INSERT INTO purchase_order_items
                            (tenant_id, purchase_order_id, ingredient_id,
                             ingredient_name, quantity, unit, unit_price_fen)
                        VALUES
                            (:tenant_id, :po_id, :ingredient_id,
                             :ingredient_name, :quantity, :unit, :unit_price_fen)
                    """),
                    {
                        "tenant_id": tenant_id,
                        "po_id": po_id,
                        "ingredient_id": str(item["ingredient_id"]),
                        "ingredient_name": item["ingredient_name"],
                        "quantity": float(item["suggested_qty"]),
                        "unit": item["unit"] or "",
                        "unit_price_fen": int(
                            item["estimated_cost_fen"] / max(float(item["suggested_qty"]), 0.001)
                        ),
                    },
                )

                # 更新采购建议状态
                await db.execute(
                    text("""
                        UPDATE mrp_procurement_suggestions
                        SET status = 'ordered',
                            purchase_order_id = :po_id,
                            updated_at = NOW()
                        WHERE id = :sug_id
                    """),
                    {"po_id": po_id, "sug_id": str(item["id"])},
                )

            created_orders.append({
                "purchase_order_id": po_id,
                "order_no": po_no,
                "supplier_id": supplier_id,
                "supplier_name": supplier_name,
                "items_count": len(items),
                "total_amount_fen": total_fen,
            })

        await db.commit()
        _log.info("mrp.procurement.converted", orders_count=len(created_orders))
        return created_orders

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  7. 生产建议→生产任务
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    async def convert_to_production_tasks(
        self,
        tenant_id: str,
        plan_id: str,
        suggestion_ids: List[str],
        db: AsyncSession,
    ) -> List[Dict[str, Any]]:
        """将生产建议转为生产任务

        Args:
            tenant_id: 租户ID
            plan_id: 计划ID
            suggestion_ids: 要转换的生产建议ID列表
            db: 数据库会话

        Returns:
            创建的生产任务列表
        """
        _log = log.bind(tenant_id=tenant_id, plan_id=plan_id)
        await self._set_tenant(db, tenant_id)

        if not suggestion_ids:
            raise ValueError("生产建议ID列表不能为空")

        result = await db.execute(
            text("""
                SELECT id, product_id, product_name, suggested_qty, unit,
                       bom_id, required_date, priority, status
                FROM mrp_production_suggestions
                WHERE id = ANY(:ids::uuid[])
                  AND plan_id = :plan_id
                  AND status = 'approved'
                  AND is_deleted = false
            """),
            {"ids": suggestion_ids, "plan_id": plan_id},
        )
        rows = result.mappings().fetchall()

        if not rows:
            raise ValueError("未找到可转换的已审批生产建议")

        created_tasks: List[Dict[str, Any]] = []
        now_str = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")

        for row in rows:
            task_no = f"MRP-PT{now_str}{uuid.uuid4().hex[:4].upper()}"

            task_result = await db.execute(
                text("""
                    INSERT INTO production_tasks
                        (tenant_id, task_no, product_id, product_name,
                         planned_qty, unit, bom_id, required_date,
                         priority, status, source)
                    VALUES
                        (:tenant_id, :task_no, :product_id, :product_name,
                         :planned_qty, :unit, :bom_id, :required_date,
                         :priority, 'pending', 'mrp')
                    RETURNING id
                """),
                {
                    "tenant_id": tenant_id,
                    "task_no": task_no,
                    "product_id": str(row["product_id"]),
                    "product_name": row["product_name"],
                    "planned_qty": float(row["suggested_qty"]),
                    "unit": row["unit"] or "",
                    "bom_id": str(row["bom_id"]) if row["bom_id"] else None,
                    "required_date": row["required_date"],
                    "priority": row["priority"],
                },
            )
            task_row = task_result.mappings().fetchone()

            # 更新生产建议状态
            await db.execute(
                text("""
                    UPDATE mrp_production_suggestions
                    SET status = 'scheduled', updated_at = NOW()
                    WHERE id = :sug_id
                """),
                {"sug_id": str(row["id"])},
            )

            created_tasks.append({
                "production_task_id": str(task_row["id"]),
                "task_no": task_no,
                "product_name": row["product_name"],
                "planned_qty": float(row["suggested_qty"]),
                "required_date": str(row["required_date"]),
                "priority": row["priority"],
            })

        await db.commit()
        _log.info("mrp.production.converted", tasks_count=len(created_tasks))
        return created_tasks

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  8. 按计划领料
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    async def plan_material_issue(
        self,
        tenant_id: str,
        production_suggestion_id: str,
        db: AsyncSession,
    ) -> List[PlannedIssueInfo]:
        """根据生产建议生成按计划领料单

        从BOM展开所需原料，生成领料明细。

        Args:
            tenant_id: 租户ID
            production_suggestion_id: 生产建议ID
            db: 数据库会话

        Returns:
            List[PlannedIssueInfo] 领料单明细
        """
        _log = log.bind(tenant_id=tenant_id, production_suggestion_id=production_suggestion_id)
        await self._set_tenant(db, tenant_id)

        # 查询生产建议
        result = await db.execute(
            text("""
                SELECT id, product_id, product_name, suggested_qty, bom_id, status
                FROM mrp_production_suggestions
                WHERE id = :sug_id AND is_deleted = false
            """),
            {"sug_id": production_suggestion_id},
        )
        sug_row = result.mappings().fetchone()
        if not sug_row:
            raise ValueError(f"生产建议不存在: {production_suggestion_id}")

        if sug_row["status"] not in ("approved", "scheduled"):
            raise ValueError(f"生产建议状态 '{sug_row['status']}' 不支持生成领料单")

        bom_id = sug_row["bom_id"]
        production_qty = float(sug_row["suggested_qty"])

        if not bom_id:
            raise ValueError("生产建议未关联BOM，无法生成领料单")

        # 清理旧的领料单
        await db.execute(
            text("""
                DELETE FROM mrp_planned_issues
                WHERE production_suggestion_id = :sug_id
            """),
            {"sug_id": production_suggestion_id},
        )

        # 查询BOM明细
        bom_result = await db.execute(
            text("""
                SELECT
                    ingredient_id,
                    ingredient_name,
                    quantity AS bom_qty,
                    unit,
                    COALESCE(waste_rate, :default_waste) AS waste_rate
                FROM bom_items
                WHERE bom_id = :bom_id AND is_deleted = false
            """),
            {"bom_id": str(bom_id), "default_waste": DEFAULT_WASTE_RATE},
        )
        bom_rows = bom_result.mappings().fetchall()

        if not bom_rows:
            _log.warning("mrp.material_issue.no_bom_items", bom_id=str(bom_id))
            return []

        issues: List[PlannedIssueInfo] = []
        for bom in bom_rows:
            bom_qty = float(bom["bom_qty"])
            waste_rate = float(bom["waste_rate"])
            # 领料量 = 生产量 x BOM用量 x (1 + 损耗率)
            planned_qty = round(production_qty * bom_qty * (1 + waste_rate), 3)

            ins_result = await db.execute(
                text("""
                    INSERT INTO mrp_planned_issues
                        (tenant_id, production_suggestion_id, ingredient_id,
                         ingredient_name, planned_qty, unit, status)
                    VALUES
                        (:tenant_id, :sug_id, :ingredient_id,
                         :ingredient_name, :planned_qty, :unit, 'planned')
                    RETURNING id
                """),
                {
                    "tenant_id": tenant_id,
                    "sug_id": production_suggestion_id,
                    "ingredient_id": str(bom["ingredient_id"]),
                    "ingredient_name": bom["ingredient_name"],
                    "planned_qty": planned_qty,
                    "unit": bom["unit"] or "",
                },
            )
            ins_row = ins_result.mappings().fetchone()

            issues.append(PlannedIssueInfo(
                id=str(ins_row["id"]),
                production_suggestion_id=production_suggestion_id,
                ingredient_id=str(bom["ingredient_id"]),
                ingredient_name=bom["ingredient_name"],
                planned_qty=planned_qty,
                actual_qty=None,
                unit=bom["unit"] or "",
                issued_at=None,
                issued_by=None,
                status="planned",
                variance_qty=None,
            ))

        await db.commit()
        _log.info("mrp.material_issue.planned", count=len(issues))
        return issues

    async def execute_material_issue(
        self,
        tenant_id: str,
        planned_issue_id: str,
        actual_qty: float,
        issued_by: str,
        db: AsyncSession,
    ) -> PlannedIssueInfo:
        """执行领料

        记录实际领料量，计算差异，更新库存。

        Args:
            tenant_id: 租户ID
            planned_issue_id: 领料单ID
            actual_qty: 实际领料量
            issued_by: 领料人ID
            db: 数据库会话

        Returns:
            PlannedIssueInfo 更新后的领料信息
        """
        _log = log.bind(tenant_id=tenant_id, planned_issue_id=planned_issue_id)
        await self._set_tenant(db, tenant_id)

        if actual_qty < 0:
            raise ValueError("实际领料量不能为负数")

        # 查询领料单
        result = await db.execute(
            text("""
                SELECT id, production_suggestion_id, ingredient_id, ingredient_name,
                       planned_qty, unit, status
                FROM mrp_planned_issues
                WHERE id = :issue_id AND is_deleted = false
            """),
            {"issue_id": planned_issue_id},
        )
        row = result.mappings().fetchone()
        if not row:
            raise ValueError(f"领料单不存在: {planned_issue_id}")

        if row["status"] not in ("planned", "partial"):
            raise ValueError(f"领料单状态 '{row['status']}' 不支持执行领料")

        planned_qty = float(row["planned_qty"])
        variance = round(actual_qty - planned_qty, 3)

        # 判定状态
        if actual_qty <= 0:
            new_status = "cancelled"
        elif abs(actual_qty - planned_qty) / max(planned_qty, 0.001) < 0.05:
            # 差异在5%以内视为完全领料
            new_status = "issued"
        else:
            new_status = "partial" if actual_qty < planned_qty else "issued"

        await db.execute(
            text("""
                UPDATE mrp_planned_issues
                SET actual_qty = :actual_qty,
                    issued_at = NOW(),
                    issued_by = :issued_by,
                    status = :status,
                    variance_qty = :variance,
                    updated_at = NOW()
                WHERE id = :issue_id
            """),
            {
                "actual_qty": actual_qty,
                "issued_by": issued_by,
                "status": new_status,
                "variance": variance,
                "issue_id": planned_issue_id,
            },
        )
        await db.commit()

        _log.info(
            "mrp.material_issue.executed",
            planned_qty=planned_qty,
            actual_qty=actual_qty,
            variance=variance,
            status=new_status,
        )

        return PlannedIssueInfo(
            id=str(row["id"]),
            production_suggestion_id=str(row["production_suggestion_id"]),
            ingredient_id=str(row["ingredient_id"]),
            ingredient_name=row["ingredient_name"],
            planned_qty=planned_qty,
            actual_qty=actual_qty,
            unit=row["unit"] or "",
            issued_at=_now_iso(),
            issued_by=issued_by,
            status=new_status,
            variance_qty=variance,
        )

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  9. 查询接口
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    async def get_demand_lines(
        self,
        tenant_id: str,
        plan_id: str,
        db: AsyncSession,
        page: int = 1,
        size: int = 50,
    ) -> Dict[str, Any]:
        """获取需求行列表"""
        await self._set_tenant(db, tenant_id)

        count_result = await db.execute(
            text("""
                SELECT COUNT(*) FROM mrp_demand_lines
                WHERE plan_id = :plan_id AND is_deleted = false
            """),
            {"plan_id": plan_id},
        )
        total = count_result.scalar() or 0

        result = await db.execute(
            text("""
                SELECT id, plan_id, ingredient_id, ingredient_name, unit,
                       forecast_demand_qty, safety_stock_qty, current_stock_qty,
                       in_transit_qty, net_requirement_qty, source
                FROM mrp_demand_lines
                WHERE plan_id = :plan_id AND is_deleted = false
                ORDER BY net_requirement_qty DESC
                LIMIT :limit OFFSET :offset
            """),
            {"plan_id": plan_id, "limit": size, "offset": (page - 1) * size},
        )
        rows = result.mappings().fetchall()

        items = [
            DemandLineInfo(
                id=str(r["id"]),
                plan_id=str(r["plan_id"]),
                ingredient_id=str(r["ingredient_id"]),
                ingredient_name=r["ingredient_name"],
                unit=r["unit"] or "",
                forecast_demand_qty=float(r["forecast_demand_qty"]),
                safety_stock_qty=float(r["safety_stock_qty"]),
                current_stock_qty=float(r["current_stock_qty"]),
                in_transit_qty=float(r["in_transit_qty"]),
                net_requirement_qty=float(r["net_requirement_qty"]),
                source=r["source"],
            ).model_dump()
            for r in rows
        ]
        return {"items": items, "total": total}

    async def get_production_suggestions(
        self,
        tenant_id: str,
        plan_id: str,
        db: AsyncSession,
        page: int = 1,
        size: int = 50,
    ) -> Dict[str, Any]:
        """获取生产建议列表"""
        await self._set_tenant(db, tenant_id)

        count_result = await db.execute(
            text("""
                SELECT COUNT(*) FROM mrp_production_suggestions
                WHERE plan_id = :plan_id AND is_deleted = false
            """),
            {"plan_id": plan_id},
        )
        total = count_result.scalar() or 0

        result = await db.execute(
            text("""
                SELECT id, plan_id, product_id, product_name, suggested_qty, unit,
                       bom_id, required_date, priority, status
                FROM mrp_production_suggestions
                WHERE plan_id = :plan_id AND is_deleted = false
                ORDER BY
                    CASE priority
                        WHEN 'urgent' THEN 1 WHEN 'high' THEN 2
                        WHEN 'medium' THEN 3 ELSE 4
                    END,
                    required_date ASC
                LIMIT :limit OFFSET :offset
            """),
            {"plan_id": plan_id, "limit": size, "offset": (page - 1) * size},
        )
        rows = result.mappings().fetchall()

        items = [
            ProductionSuggestionInfo(
                id=str(r["id"]),
                plan_id=str(r["plan_id"]),
                product_id=str(r["product_id"]),
                product_name=r["product_name"],
                suggested_qty=float(r["suggested_qty"]),
                unit=r["unit"] or "",
                bom_id=str(r["bom_id"]) if r["bom_id"] else None,
                required_date=r["required_date"],
                priority=r["priority"],
                status=r["status"],
            ).model_dump()
            for r in rows
        ]
        return {"items": items, "total": total}

    async def get_procurement_suggestions(
        self,
        tenant_id: str,
        plan_id: str,
        db: AsyncSession,
        page: int = 1,
        size: int = 50,
    ) -> Dict[str, Any]:
        """获取采购建议列表"""
        await self._set_tenant(db, tenant_id)

        count_result = await db.execute(
            text("""
                SELECT COUNT(*) FROM mrp_procurement_suggestions
                WHERE plan_id = :plan_id AND is_deleted = false
            """),
            {"plan_id": plan_id},
        )
        total = count_result.scalar() or 0

        result = await db.execute(
            text("""
                SELECT id, plan_id, ingredient_id, ingredient_name, suggested_qty,
                       unit, supplier_id, supplier_name, estimated_cost_fen,
                       required_date, lead_time_days, status, purchase_order_id
                FROM mrp_procurement_suggestions
                WHERE plan_id = :plan_id AND is_deleted = false
                ORDER BY estimated_cost_fen DESC
                LIMIT :limit OFFSET :offset
            """),
            {"plan_id": plan_id, "limit": size, "offset": (page - 1) * size},
        )
        rows = result.mappings().fetchall()

        items = [
            ProcurementSuggestionInfo(
                id=str(r["id"]),
                plan_id=str(r["plan_id"]),
                ingredient_id=str(r["ingredient_id"]),
                ingredient_name=r["ingredient_name"],
                suggested_qty=float(r["suggested_qty"]),
                unit=r["unit"] or "",
                supplier_id=str(r["supplier_id"]) if r["supplier_id"] else None,
                supplier_name=r["supplier_name"],
                estimated_cost_fen=int(r["estimated_cost_fen"]),
                required_date=r["required_date"],
                lead_time_days=int(r["lead_time_days"]),
                status=r["status"],
                purchase_order_id=str(r["purchase_order_id"]) if r["purchase_order_id"] else None,
            ).model_dump()
            for r in rows
        ]
        return {"items": items, "total": total}

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  10. 计划总览
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    async def get_plan_summary(
        self,
        tenant_id: str,
        plan_id: str,
        db: AsyncSession,
    ) -> PlanSummary:
        """计划总览：需求/生产/采购/领料汇总"""
        await self._set_tenant(db, tenant_id)

        plan = await self.get_plan(tenant_id, plan_id, db)

        # 需求行汇总
        demand_result = await db.execute(
            text("""
                SELECT
                    COUNT(*) AS cnt,
                    COALESCE(SUM(forecast_demand_qty), 0) AS total_forecast,
                    COALESCE(SUM(net_requirement_qty), 0) AS total_net
                FROM mrp_demand_lines
                WHERE plan_id = :plan_id AND is_deleted = false
            """),
            {"plan_id": plan_id},
        )
        d = demand_result.mappings().fetchone()

        # 生产建议汇总
        prod_result = await db.execute(
            text("""
                SELECT
                    COUNT(*) AS cnt,
                    COUNT(*) FILTER (WHERE status = 'completed') AS completed
                FROM mrp_production_suggestions
                WHERE plan_id = :plan_id AND is_deleted = false
            """),
            {"plan_id": plan_id},
        )
        p = prod_result.mappings().fetchone()

        # 采购建议汇总
        proc_result = await db.execute(
            text("""
                SELECT
                    COUNT(*) AS cnt,
                    COUNT(*) FILTER (WHERE status = 'ordered') AS ordered,
                    COALESCE(SUM(estimated_cost_fen), 0) AS total_cost
                FROM mrp_procurement_suggestions
                WHERE plan_id = :plan_id AND is_deleted = false
            """),
            {"plan_id": plan_id},
        )
        pr = proc_result.mappings().fetchone()

        # 领料汇总
        issue_result = await db.execute(
            text("""
                SELECT
                    COUNT(*) AS cnt,
                    COUNT(*) FILTER (WHERE status = 'issued') AS issued
                FROM mrp_planned_issues
                WHERE production_suggestion_id IN (
                    SELECT id FROM mrp_production_suggestions WHERE plan_id = :plan_id
                )
                AND is_deleted = false
            """),
            {"plan_id": plan_id},
        )
        i = issue_result.mappings().fetchone()

        return PlanSummary(
            plan=plan,
            demand_lines_count=int(d["cnt"]),
            total_forecast_demand_qty=float(d["total_forecast"]),
            total_net_requirement_qty=float(d["total_net"]),
            production_suggestions_count=int(p["cnt"]),
            production_completed_count=int(p["completed"]),
            procurement_suggestions_count=int(pr["cnt"]),
            procurement_ordered_count=int(pr["ordered"]),
            total_estimated_cost_fen=int(pr["total_cost"]),
            planned_issues_count=int(i["cnt"]),
            issued_count=int(i["issued"]),
        )

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  11. 差异报告
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    async def get_variance_report(
        self,
        tenant_id: str,
        plan_id: str,
        db: AsyncSession,
    ) -> VarianceReport:
        """计划vs实际差异报告

        统计所有已执行领料的计划量vs实际量差异。
        """
        await self._set_tenant(db, tenant_id)

        result = await db.execute(
            text("""
                SELECT
                    pi.ingredient_id,
                    pi.ingredient_name,
                    SUM(pi.planned_qty) AS total_planned,
                    SUM(COALESCE(pi.actual_qty, 0)) AS total_actual
                FROM mrp_planned_issues pi
                JOIN mrp_production_suggestions ps ON ps.id = pi.production_suggestion_id
                WHERE ps.plan_id = :plan_id
                  AND pi.status IN ('issued', 'partial')
                  AND pi.is_deleted = false
                GROUP BY pi.ingredient_id, pi.ingredient_name
                ORDER BY ABS(SUM(COALESCE(pi.actual_qty, 0)) - SUM(pi.planned_qty)) DESC
            """),
            {"plan_id": plan_id},
        )
        rows = result.mappings().fetchall()

        items: List[VarianceItem] = []
        total_planned = 0.0
        total_actual = 0.0

        for row in rows:
            planned = float(row["total_planned"])
            actual = float(row["total_actual"])
            variance = round(actual - planned, 3)
            variance_pct = round((variance / planned * 100) if planned > 0 else 0, 2)

            total_planned += planned
            total_actual += actual

            items.append(VarianceItem(
                ingredient_id=str(row["ingredient_id"]),
                ingredient_name=row["ingredient_name"],
                planned_qty=planned,
                actual_qty=actual,
                variance_qty=variance,
                variance_pct=variance_pct,
            ))

        overall_pct = round(
            ((total_actual - total_planned) / total_planned * 100) if total_planned > 0 else 0,
            2,
        )

        return VarianceReport(
            plan_id=plan_id,
            items=items,
            total_planned=round(total_planned, 3),
            total_actual=round(total_actual, 3),
            overall_variance_pct=overall_pct,
        )
