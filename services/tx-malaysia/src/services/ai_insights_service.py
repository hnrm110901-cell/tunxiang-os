"""马来西亚 AI 业务洞察服务 — Phase 3 Sprint 3.3

AI 驱动的业务优化建议，针对马来西亚餐饮市场特点：
  - 食材浪费减少建议（基于 malaysia_ingredients.py 季节性数据）
  - 人力排班优化（遵循马来西亚 Employment Act）
  - Halal 供应链合规检查
  - 定价优化建议（结合食材成本趋势、SST 影响）

这是分析/占位服务 — 真实的 AI 推理需要集成 Claude API。
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from services.tx_agent.src.config.malaysia_holidays import (
    get_high_impact_periods,
    get_holidays_by_year,
    get_holiday_by_name,
)
from services.tx_agent.src.config.malaysia_cuisine_profiles import (
    CUISINE_PROFILES,
    get_cuisine_by_state,
    get_cuisine_profile,
    MALAYSIA_MEAL_PERIODS,
)
from services.tx_agent.src.config.malaysia_ingredients import (
    MALAYSIA_INGREDIENTS,
    get_ingredient,
    get_perishable_ingredients,
    get_halal_certified_ingredients,
)

logger = structlog.get_logger(__name__)

# ─── 马来西亚劳工法参数 ─────────────────────────────────────────

EMPLOYMENT_ACT_MAX_HOURS_PER_WEEK = 45  # 《1955年雇佣法》第60A条：每周最多45小时
EMPLOYMENT_ACT_MAX_OT_PER_MONTH = 104  # 每月最多加班104小时
EMPLOYMENT_ACT_OT_RATE_WEEKDAY = 1.5  # 平日加班1.5倍
EMPLOYMENT_ACT_OT_RATE_REST_DAY = 2.0  # 休息日加班2.0倍
EMPLOYMENT_ACT_OT_RATE_PUBLIC_HOLIDAY = 3.0  # 公共假日加班3.0倍

# 默认时段人力需求系数
STAFFING_FACTORS: dict[str, float] = {
    "breakfast": 0.3,
    "lunch": 0.8,
    "afternoon_tea": 0.2,
    "dinner": 1.0,
    "supper": 0.15,
}

# 浪费严重程度阈值（相对于月均用量）
WASTE_SEVERE_THRESHOLD = 0.30  # 浪费超30%月用量 → severe
WASTE_MODERATE_THRESHOLD = 0.15  # 浪费超15%月用量 → moderate


class AIInsightsService:
    """马来西亚 AI 业务洞察服务

    提供基于数据的智能化建议，覆盖食材管理、人力配置、合规检查和定价。

    注意：当前为分析占位版本，使用规则引擎和配置数据。
    真实 AI 集成需对接 Claude API 实现深度推理。

    用法：
        svc = AIInsightsService()
        recs = await svc.get_waste_reduction_recommendations(tenant_id, store_id, db)
    """

    # ═══════════════════════════════════════════════════════════════
    # 食材浪费减少建议
    # ═══════════════════════════════════════════════════════════════

    async def get_waste_reduction_recommendations(
        self,
        tenant_id: str,
        store_id: str,
        db: AsyncSession,
    ) -> list[dict[str, Any]]:
        """AI 食材浪费减少建议

        基于库存消耗记录和食材配置数据分析：
          - 特定食材的过量库存警告
          - 基于销量模式的份量调整建议
          - 针对浪费减少的菜单工程（使用菜系资料）

        Args:
            tenant_id: 商户 UUID.
            store_id: 门店 UUID.
            db: 数据库会话.

        Returns:
            [
                {
                    recommendation_type: "overstock" | "portion_adjustment" | "menu_engineering",
                    ingredient_key: str,
                    ingredient_name_ms: str,
                    severity: "high" | "moderate" | "info",
                    current_waste_pct: float,
                    suggested_action: str,
                    estimated_savings_fen: int,
                    priority: int,  # 1=highest
                },
            ]
        """
        log = logger.bind(tenant_id=tenant_id, store_id=store_id)
        log.info("ai_insights.waste_reduction")

        recommendations: list[dict[str, Any]] = []

        # 获取店铺所在州（用于菜系匹配）
        store_info = await self._get_store_state(tenant_id, store_id, db)
        state = store_info.get("state", "")
        cuisine_mix = get_cuisine_by_state(state) if state else ["malay", "chinese", "indian"]

        # 获取最近 30 天的库存消耗数据
        try:
            waste_rows = await db.execute(
                text("""
                    SELECT
                        it.ingredient_name,
                        SUM(CASE WHEN it.transaction_type IN ('waste', 'spoilage')
                            THEN ABS(it.quantity) ELSE 0 END) AS wasted_qty,
                        SUM(CASE WHEN it.transaction_type = 'consumed'
                            THEN ABS(it.quantity) ELSE 0 END) AS consumed_qty,
                        SUM(CASE WHEN it.transaction_type = 'received'
                            THEN it.quantity ELSE 0 END) AS received_qty,
                        COUNT(*) AS transaction_count
                    FROM inventory_transactions it
                    WHERE it.tenant_id = :tid
                      AND it.store_id = :sid
                      AND it.created_at >= NOW() - INTERVAL '30 days'
                      AND it.is_deleted = FALSE
                    GROUP BY it.ingredient_name
                    HAVING SUM(CASE WHEN it.transaction_type IN ('waste', 'spoilage')
                        THEN ABS(it.quantity) ELSE 0 END) > 0
                    ORDER BY wasted_qty DESC
                """),
                {"tid": tenant_id, "sid": store_id},
            )
            waste_data = waste_rows.mappings().fetchall()
        except Exception as exc:
            log.warning("waste_data_query_failed", error=str(exc))
            waste_data = []

        # 如果没有数据库数据，使用 MALAYSIA_INGREDIENTS 配置数据生成默认建议
        if not waste_data:
            log.info("ai_insights.using_config_based_recommendations")
            recommendations = self._generate_config_based_waste_recs(cuisine_mix)
        else:
            # 基于数据库记录的浪费分析
            recommendations = self._analyze_waste_data(waste_data, cuisine_mix)

        # 为建议打分排序
        for i, rec in enumerate(recommendations):
            rec["priority"] = i + 1

        log.info(
            "ai_insights.waste_reduction_complete",
            recommendation_count=len(recommendations),
        )
        return recommendations

    # ═══════════════════════════════════════════════════════════════
    # 人力优化建议
    # ═══════════════════════════════════════════════════════════════

    async def get_labour_optimization(
        self,
        tenant_id: str,
        store_id: str,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """人力配置优化建议

        基于 Malaysia Employment Act 1955 合规分析：
          - 各日/时段预计人力需求
          - 合规检查（每周工时、加班上限）
          - 公共假日排班建议

        Args:
            tenant_id: 商户 UUID.
            store_id: 门店 UUID.
            db: 数据库会话.

        Returns:
            {
                store_id, store_name,
                staffing_predictions: [{ day_of_week, meal_period,
                    staff_needed, current_staff, gap }],
                compliance_check: {
                    max_hours_per_week: 45,
                    current_avg_hours: float,
                    overtime_month_hours: float,
                    is_compliant: bool,
                    violations: [str],
                },
                holiday_staffing_impact: [{ holiday_name, date,
                    staff_multiplier, suggested_action }],
                recommendations: [str],
            }
        """
        log = logger.bind(tenant_id=tenant_id, store_id=store_id)
        log.info("ai_insights.labour_optimization")

        store_info = await self._get_store_state(tenant_id, store_id, db)
        state = store_info.get("state", "")
        cuisine_mix = get_cuisine_by_state(state) if state else ["malay", "chinese", "indian"]

        # 获取最近营业数据推算人力需求
        try:
            sales_rows = await db.execute(
                text("""
                    SELECT
                        EXTRACT(DOW FROM order_time AT TIME ZONE 'Asia/Kuala_Lumpur') AS dow,
                        CASE
                            WHEN EXTRACT(HOUR FROM order_time AT TIME ZONE 'Asia/Kuala_Lumpur') BETWEEN 6 AND 11 THEN 'breakfast'
                            WHEN EXTRACT(HOUR FROM order_time AT TIME ZONE 'Asia/Kuala_Lumpur') BETWEEN 11 AND 15 THEN 'lunch'
                            WHEN EXTRACT(HOUR FROM order_time AT TIME ZONE 'Asia/Kuala_Lumpur') BETWEEN 15 AND 17 THEN 'afternoon_tea'
                            WHEN EXTRACT(HOUR FROM order_time AT TIME ZONE 'Asia/Kuala_Lumpur') BETWEEN 17 AND 22 THEN 'dinner'
                            ELSE 'supper'
                        END AS meal_period,
                        COUNT(*) AS order_count,
                        COALESCE(SUM(final_amount_fen), 0) AS revenue_fen
                    FROM orders
                    WHERE tenant_id = :tid
                      AND store_id = :sid
                      AND order_time >= NOW() - INTERVAL '30 days'
                      AND status IN ('completed', 'settled')
                      AND is_deleted = FALSE
                    GROUP BY dow, meal_period
                    ORDER BY dow, meal_period
                """),
                {"tid": tenant_id, "sid": store_id},
            )
            sales_data = sales_rows.mappings().fetchall()
        except Exception as exc:
            log.warning("sales_data_query_failed", error=str(exc))
            sales_data = []

        # 按星期日-时段构建需求预测
        staffing_predictions: list[dict[str, Any]] = []
        dow_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

        if sales_data:
            for row in sales_data:
                dow = int(row.get("dow", 0))
                period = row.get("meal_period", "dinner")
                order_count = int(row.get("order_count", 0) or 0)

                base_factor = STAFFING_FACTORS.get(period, 0.5)
                # 高峰期增加需求
                is_weekend = dow in (5, 6)
                weekend_boost = 1.3 if is_weekend else 1.0
                staff_needed = max(1, int(round(base_factor * weekend_boost * 3)))

                staffing_predictions.append({
                    "day_of_week": dow_names[dow],
                    "dow_index": dow,
                    "meal_period": period,
                    "order_count": order_count,
                    "staff_needed": staff_needed,
                    "current_staff": None,  # 需从排班表读取
                    "gap": None,
                })
        else:
            # 无数据时的默认排班建议
            for dow_idx in range(7):
                is_weekend = dow_idx in (5, 6)
                for period_name, factor in STAFFING_FACTORS.items():
                    weekend_boost = 1.3 if is_weekend else 1.0
                    staff_needed = max(1, int(round(factor * weekend_boost * 3)))
                    staffing_predictions.append({
                        "day_of_week": dow_names[dow_idx],
                        "dow_index": dow_idx,
                        "meal_period": period_name,
                        "order_count": 0,
                        "staff_needed": staff_needed,
                        "current_staff": None,
                        "gap": None,
                    })

        # 合规检查
        try:
            hours_row = await db.execute(
                text("""
                    SELECT
                        COALESCE(AVG(hours_worked), 0) AS avg_hours_per_week,
                        COALESCE(SUM(overtime_hours), 0) AS total_ot_month
                    FROM employee_shifts
                    WHERE tenant_id = :tid
                      AND store_id = :sid
                      AND shift_date >= DATE_TRUNC('month', NOW())
                      AND is_deleted = FALSE
                """),
                {"tid": tenant_id, "sid": store_id},
            )
            hr = hours_row.fetchone()
            avg_hours = float(hr.avg_hours_per_week) if hr else 35.0
            ot_hours = float(hr.total_ot_month) if hr else 20.0
        except Exception as exc:
            log.warning("hours_query_failed", error=str(exc))
            avg_hours = 35.0
            ot_hours = 20.0

        violations: list[str] = []
        if avg_hours > EMPLOYMENT_ACT_MAX_HOURS_PER_WEEK:
            violations.append(f"周均工时 {avg_hours:.1f}h 超过法定上限 {EMPLOYMENT_ACT_MAX_HOURS_PER_WEEK}h")
        if ot_hours > EMPLOYMENT_ACT_MAX_OT_PER_MONTH:
            violations.append(f"月加班 {ot_hours:.1f}h 超过法定上限 {EMPLOYMENT_ACT_MAX_OT_PER_MONTH}h")

        is_compliant = len(violations) == 0

        # 节假日人力需求影响
        today = date.today()
        year = today.year
        holiday_impacts: list[dict[str, Any]] = []
        for h in get_high_impact_periods(year):
            h_date = datetime.strptime(h["date"], "%Y-%m-%d").date()
            days_until = (h_date - today).days
            if 0 <= days_until <= 90:
                staff_mult = 1.0 + h.get("dine_in_boost", 0.0)
                holiday_impacts.append({
                    "holiday_name": h["name"],
                    "date": h["date"],
                    "days_until": days_until,
                    "staff_multiplier": round(staff_mult, 2),
                    "suggested_action": (
                        "增加班次" if staff_mult > 1.15
                        else "维持正常排班" if staff_mult > 0.95
                        else "减少排班"
                    ),
                })

        # 建议汇总
        recommendations: list[str] = []
        if not is_compliant:
            recommendations.extend(violations)
        if holiday_impacts:
            next_holiday = holiday_impacts[0]
            recommendations.append(
                f"下一个节假日 {next_holiday['holiday_name']}（{next_holiday['days_until']}天后），"
                f"人力需求系数 ×{next_holiday['staff_multiplier']}，建议提前排班"
            )
        recommendations.append(
            f"马来西亚雇佣法要求每周工时 ≤ {EMPLOYMENT_ACT_MAX_HOURS_PER_WEEK}h，"
            f"加班 ≤ {EMPLOYMENT_ACT_MAX_OT_PER_MONTH}h/月"
        )
        recommendations.append(
            "法定节假日（Hari Raya/CNY/Deepavali/Christmas等）加班费率3倍，"
            "建议优先使用自愿加班"
        )

        result = {
            "store_id": store_id,
            "store_name": store_info.get("store_name", ""),
            "staffing_predictions": staffing_predictions,
            "compliance_check": {
                "max_hours_per_week": EMPLOYMENT_ACT_MAX_HOURS_PER_WEEK,
                "current_avg_hours_per_week": round(avg_hours, 1),
                "overtime_month_hours": round(ot_hours, 1),
                "overtime_month_max": EMPLOYMENT_ACT_MAX_OT_PER_MONTH,
                "is_compliant": is_compliant,
                "violations": violations,
            },
            "holiday_staffing_impact": holiday_impacts,
            "recommendations": recommendations,
        }

        log.info(
            "ai_insights.labour_optimization_complete",
            is_compliant=is_compliant,
            holiday_count=len(holiday_impacts),
        )
        return result

    # ═══════════════════════════════════════════════════════════════
    # Halal 供应链合规检查
    # ═══════════════════════════════════════════════════════════════

    async def get_halal_compliance_check(
        self,
        tenant_id: str,
        store_id: str,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """Halal 供应链合规检查

        基于 JAKIM Halal 认证标准检查：
          - 食材库存中非 Halal 认证食材的占比和分布
          - 供应商 Halal 认证状态
          - 风险食材警告

        Args:
            tenant_id: 商户 UUID.
            store_id: 门店 UUID.
            db: 数据库会话.

        Returns:
            {
                store_id, store_name,
                overall_status: "compliant" | "warning" | "non_compliant",
                certified_ingredients: { count, pct },
                non_certified_ingredients: [{ ingredient_name, supplier, risk }],
                supplier_halal_status: [{ supplier_name, is_certified, last_audit_date }],
                warnings: [str],
                recommendations: [str],
            }
        """
        log = logger.bind(tenant_id=tenant_id, store_id=store_id)
        log.info("ai_insights.halal_compliance")

        store_info = await self._get_store_state(tenant_id, store_id, db)

        # 获取门店当前库存食材
        try:
            inv_rows = await db.execute(
                text("""
                    SELECT
                        i.ingredient_name,
                        i.current_quantity,
                        i.supplier_name,
                        i.halal_certified,
                        i.jakim_cert_ref,
                        i.last_halal_audit
                    FROM ingredients i
                    WHERE i.tenant_id = :tid
                      AND i.store_id = :sid
                      AND i.is_deleted = FALSE
                    ORDER BY i.current_quantity DESC
                """),
                {"tid": tenant_id, "sid": store_id},
            )
            inventory_data = inv_rows.mappings().fetchall()
        except Exception as exc:
            log.warning("inventory_query_failed", error=str(exc))
            inventory_data = []

        # 如果没有数据库数据，用 MALAYSIA_INGREDIENTS 配置数据分析
        if not inventory_data:
            return self._generate_config_halal_check(cuisine_mix=None)

        # 分析库存合规
        certified_count = 0
        non_certified: list[dict[str, Any]] = []
        supplier_set: dict[str, dict[str, Any]] = {}
        total_items = len(inventory_data)

        for item in inventory_data:
            ing_name = item.get("ingredient_name", "")
            is_cert = item.get("halal_certified", False)
            supplier = item.get("supplier_name", "unknown")

            if is_cert:
                certified_count += 1
            else:
                risk = "high" if item.get("current_quantity", 0) > 0 else "low"
                non_certified.append({
                    "ingredient_name": ing_name,
                    "supplier": supplier,
                    "quantity": float(item.get("current_quantity", 0) or 0),
                    "risk": risk,
                })

            if supplier:
                if supplier not in supplier_set:
                    supplier_set[supplier] = {
                        "supplier_name": supplier,
                        "is_certified": is_cert,
                        "last_audit_date": item.get("last_halal_audit"),
                    }
                if not is_cert:
                    supplier_set[supplier]["is_certified"] = False

        certified_pct = round(certified_count / max(total_items, 1) * 100, 1)
        supplier_list = list(supplier_set.values())

        # 评估整体状态
        if certified_pct >= 95 and len(non_certified) == 0:
            overall_status = "compliant"
        elif certified_pct >= 80:
            overall_status = "warning"
        else:
            overall_status = "non_compliant"

        warnings: list[str] = []
        recommendations: list[str] = []

        if non_certified:
            warnings.append(f"发现 {len(non_certified)} 种非 Halal 认证食材")
            for nc in non_certified[:3]:
                warnings.append(f"  - {nc['ingredient_name']}（供应商: {nc['supplier']}）")
            recommendations.append("立即联系 JAKIM 认证供应商替换非认证食材")
        if certified_pct < 100:
            recommendations.append(f"当前 Halal 认证占比 {certified_pct}%，目标 100%")
        recommendations.append("所有食材供应商应每 12 个月更新 JAKIM Halal 认证")
        if "chicken_whole" in [nc["ingredient_name"] for nc in non_certified]:
            recommendations.append(
                "鸡肉必须来自 JAKIM 认证供应商（推荐: CP, Leong Hup, Sri Ayamas）"
            )

        result = {
            "store_id": store_id,
            "store_name": store_info.get("store_name", ""),
            "overall_status": overall_status,
            "certified_ingredients": {
                "count": certified_count,
                "total": total_items,
                "percentage": certified_pct,
            },
            "non_certified_ingredients": non_certified,
            "supplier_halal_status": supplier_list,
            "warnings": warnings,
            "recommendations": recommendations,
        }

        log.info(
            "ai_insights.halal_compliance_complete",
            overall_status=overall_status,
            certified_pct=certified_pct,
        )
        return result

    # ═══════════════════════════════════════════════════════════════
    # 定价优化建议
    # ═══════════════════════════════════════════════════════════════

    async def get_pricing_recommendations(
        self,
        tenant_id: str,
        store_id: str,
        db: AsyncSession,
    ) -> list[dict[str, Any]]:
        """定价优化建议

        综合考虑：
          - 食材成本趋势（来自 MALAYSIA_INGREDIENTS.py 季节性价格波动）
          - 竞价对手价格参考
          - SST 税率影响（价内税/价外税策略）
          - 菜系利润模型

        Args:
            tenant_id: 商户 UUID.
            store_id: 门店 UUID.
            db: 数据库会话.

        Returns:
            [
                {
                    recommendation_type: "price_increase" | "price_decrease" | "menu_reposition",
                    dish_name: str,
                    cuisine_category: str,
                    current_price_fen: int,
                    suggested_price_fen: int,
                    rationale: str,
                    expected_margin_impact_pct: float,
                    risk_level: "low" | "medium" | "high",
                },
            ]
        """
        log = logger.bind(tenant_id=tenant_id, store_id=store_id)
        log.info("ai_insights.pricing_recommendations")

        # 获取门店菜系信息
        store_info = await self._get_store_state(tenant_id, store_id, db)
        state = store_info.get("state", "")
        cuisine_mix = get_cuisine_by_state(state) if state else ["malay", "chinese", "indian"]

        # 获取门店菜品数据
        try:
            dish_rows = await db.execute(
                text("""
                    SELECT
                        d.id AS dish_id,
                        d.name AS dish_name,
                        d.cuisine_category,
                        d.price_fen,
                        d.cost_fen,
                        d.sst_category,
                        COUNT(oi.id) AS order_count,
                        COALESCE(SUM(oi.amount_fen), 0) AS total_sales_fen
                    FROM dishes d
                    LEFT JOIN order_items oi ON oi.dish_id = d.id
                    LEFT JOIN orders o ON o.id = oi.order_id
                        AND o.tenant_id = :tid
                        AND o.status IN ('completed', 'settled')
                        AND o.is_deleted = FALSE
                    WHERE d.tenant_id = :tid
                      AND d.store_id = :sid
                      AND d.is_deleted = FALSE
                    GROUP BY d.id, d.name, d.cuisine_category, d.price_fen, d.cost_fen, d.sst_category
                    ORDER BY total_sales_fen DESC
                    LIMIT 30
                """),
                {"tid": tenant_id, "sid": store_id},
            )
            dish_data = dish_rows.mappings().fetchall()
        except Exception as exc:
            log.warning("dish_data_query_failed", error=str(exc))
            dish_data = []

        if not dish_data:
            return self._generate_config_based_pricing_recs(cuisine_mix)

        recommendations: list[dict[str, Any]] = []

        for dish in dish_data:
            dish_name = dish.get("dish_name", "")
            cuisine = dish.get("cuisine_category", cuisine_mix[0] if cuisine_mix else "fusion")
            price_fen = int(dish.get("price_fen", 0) or 0)
            cost_fen = int(dish.get("cost_fen", 0) or 0)
            sst_cat = dish.get("sst_category", "standard")
            order_count = int(dish.get("order_count", 0) or 0)

            if price_fen <= 0:
                continue

            margin_pct = (price_fen - cost_fen) / price_fen * 100 if price_fen > 0 else 0.0

            # 获取菜系标准均价
            profile = get_cuisine_profile(cuisine)
            avg_price_profile = profile.get("avg_spend_per_pax_fen", 2000) if profile else 2000

            # 分析季节性成本趋势（从食材配置数据判断）
            seasonal_cost_factor = self._get_seasonal_cost_factor(cuisine)

            # SST 影响分析：价内税模式
            sst_rate = 0.06 if sst_cat == "standard" else (0.08 if sst_cat == "specific" else 0.0)
            sst_impact = price_fen * sst_rate / (1 + sst_rate) if sst_rate > 0 else 0

            reason = ""
            rec_type = ""
            suggested_price = price_fen
            risk = "low"

            if margin_pct < 10 and seasonal_cost_factor > 1.05:
                reason = (
                    f"毛利率仅 {margin_pct:.1f}% 且食材成本上涨 {((seasonal_cost_factor - 1) * 100):.0f}%，"
                    f"SST 含税价需重新核算"
                )
                suggested_price = int(round(cost_fen * 1.35))  # 目标 35% 毛利
                rec_type = "price_increase"
                risk = "medium"
            elif margin_pct > 65 and order_count > 50:
                reason = (
                    f"高毛利（{margin_pct:.1f}%）畅销品，"
                    f"当前价格低于菜系均价（RM {avg_price_profile / 100:.0f}），可考虑小幅提价"
                )
                suggested_price = int(round(price_fen * 1.05))
                rec_type = "price_increase"
                risk = "low"
            elif margin_pct < 5 and order_count < 10:
                reason = f"低销量（{order_count}单）低毛利（{margin_pct:.1f}%），建议重新定位或下架"
                suggested_price = int(round(cost_fen * 1.25))
                rec_type = "menu_reposition"
                risk = "low"
            elif sst_rate > 0 and sst_impact > 0:
                reason = (
                    f"SST {int(sst_rate * 100)}% 含税影响约 RM {sst_impact / 100:.2f}，"
                    f"建议在菜单上明确标注含税价"
                )
                rec_type = "price_increase"
                suggested_price = price_fen
                risk = "low"

            if reason:
                recommendations.append({
                    "recommendation_type": rec_type,
                    "dish_name": dish_name,
                    "cuisine_category": cuisine,
                    "current_price_fen": price_fen,
                    "current_price_rm": round(price_fen / 100, 2),
                    "suggested_price_fen": suggested_price,
                    "suggested_price_rm": round(suggested_price / 100, 2),
                    "current_margin_pct": round(margin_pct, 1),
                    "expected_margin_impact_pct": round(
                        (suggested_price - cost_fen) / suggested_price * 100 - margin_pct, 1
                    ),
                    "rationale": reason,
                    "risk_level": risk,
                    "sst_category": sst_cat,
                    "sst_impact_fen": int(round(sst_impact)),
                })

        # 按优先级排序
        risk_order = {"high": 0, "medium": 1, "low": 2}
        recommendations.sort(key=lambda r: risk_order.get(r["risk_level"], 2))

        log.info(
            "ai_insights.pricing_recommendations_complete",
            recommendation_count=len(recommendations),
        )
        return recommendations

    # ─── Internal Helpers ──────────────────────────────────────────

    @staticmethod
    async def _get_store_state(
        tenant_id: str,
        store_id: str,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """获取门店基本信息（州、名称等）"""
        try:
            row = await db.execute(
                text("""
                    SELECT name, city, district, region
                    FROM stores
                    WHERE id = :sid AND tenant_id = :tid AND is_deleted = FALSE
                """),
                {"sid": store_id, "tid": tenant_id},
            )
            r = row.fetchone()
            if r:
                return {
                    "store_name": r.name or "",
                    "city": r.city or "",
                    "district": r.district or "",
                    "state": r.region or "",
                }
        except Exception as exc:
            logger.warning("store_state_fetch_failed", store_id=store_id, error=str(exc))
        return {"store_name": "", "city": "", "district": "", "state": ""}

    # ─── 基于配置数据的浪费建议生成器 ───────────────────────────

    def _generate_config_based_waste_recs(
        self,
        cuisine_mix: list[str],
    ) -> list[dict[str, Any]]:
        """基于 MALAYSIA_INGREDIENTS 配置数据的默认浪费减少建议"""
        recommendations: list[dict[str, Any]] = []
        perishable = get_perishable_ingredients()
        this_month = date.today().month

        for ing_key, ing_profile in sorted(perishable.items())[:8]:
            shelf_life = ing_profile.get("shelf_life_days", 7)
            is_perishable = ing_profile.get("is_perishable", False)
            storage = ing_profile.get("storage_type", "chilled")
            monthly_usage = ing_profile.get("typical_monthly_usage_g", 0) or ing_profile.get("typical_monthly_usage_kg", 0) or ing_profile.get("typical_monthly_usage_ml", 0) or 0

            # 季节价格波动分析
            price_factors = ing_profile.get("seasonal_price_fluctuation", {})
            current_factor = 1.0
            for season_key, factor in price_factors.items():
                months_range = season_key.split("-")
                if len(months_range) == 2:
                    try:
                        start_m = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
                                   "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}[months_range[0][:3]]
                        end_m = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
                                 "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}[months_range[1][:3]]
                        if start_m <= this_month <= end_m or (start_m > end_m and (this_month >= start_m or this_month <= end_m)):
                            current_factor = factor
                            break
                    except (KeyError, IndexError):
                        pass

            severity = "moderate" if current_factor > 1.08 else "info"
            if current_factor > 1.15:
                severity = "high"

            is_cuisine_relevant = any(
                ing_profile.get("category", "") in profile.get("common_ingredients", [])
                for cuisine in cuisine_mix
                for profile in [get_cuisine_profile(cuisine) or {}]
            )

            if is_cuisine_relevant or severity != "info":
                recommendations.append({
                    "recommendation_type": "overstock" if current_factor > 1.08 else "menu_engineering",
                    "ingredient_key": ing_key,
                    "ingredient_name_ms": ing_profile.get("local_names", {}).get("ms", ing_key),
                    "severity": severity,
                    "current_waste_pct": round((current_factor - 1.0) * 100, 1),
                    "suggested_action": (
                        f"建议减少 {ing_profile.get('local_names', {}).get('ms', ing_key)} 采购量，"
                        f"当前价格处于季节性高位（×{current_factor}），"
                        f"保质期 {shelf_life} 天，存储方式: {storage}"
                        if current_factor > 1.08
                        else f"监控 {ing_profile.get('local_names', {}).get('ms', ing_key)} 使用量，"
                             f"保质期 {shelf_life} 天"
                    ),
                    "estimated_savings_fen": int(monthly_usage * (current_factor - 1.0) * 10) if current_factor > 1.0 else 0,
                    "priority": 0,
                })

        return recommendations

    # ─── 基于实际消耗数据的浪费分析 ─────────────────────────

    @staticmethod
    def _analyze_waste_data(
        waste_data: list[dict[str, Any]],
        cuisine_mix: list[str],
    ) -> list[dict[str, Any]]:
        """分析实际库存消耗数据中的浪费模式"""
        recommendations: list[dict[str, Any]] = []

        for row in waste_data:
            ing_name = row.get("ingredient_name", "")
            wasted = float(row.get("wasted_qty", 0) or 0)
            consumed = float(row.get("consumed_qty", 0) or 0)
            received = float(row.get("received_qty", 0) or 0)

            total_usage = consumed + wasted
            waste_pct = wasted / max(total_usage, 1)

            if waste_pct >= WASTE_SEVERE_THRESHOLD:
                severity = "high"
                action = (
                    f"严重浪费：{ing_name} 浪费率 {waste_pct:.1%} "
                    f"（{wasted:.1f}/{total_usage:.1f}）。"
                    f"建议减少采购量、检查存储条件和份量标准"
                )
                savings = int(wasted * 10)  # 粗略估算
            elif waste_pct >= WASTE_MODERATE_THRESHOLD:
                severity = "moderate"
                action = (
                    f"{ing_name} 浪费率 {waste_pct:.1%}。"
                    f"建议优化库存周转和份量控制"
                )
                savings = int(wasted * 5)
            else:
                continue

            recommendations.append({
                "recommendation_type": "overstock" if received > consumed * 1.5 else "portion_adjustment",
                "ingredient_key": ing_name,
                "ingredient_name_ms": ing_name,
                "severity": severity,
                "current_waste_pct": round(waste_pct * 100, 1),
                "suggested_action": action,
                "estimated_savings_fen": savings,
                "priority": 0,
            })

        return recommendations

    # ─── 季节性成本因子 ────────────────────────────────────────

    def _get_seasonal_cost_factor(self, cuisine: str) -> float:
        """根据菜系和当前月份估算综合食材成本波动因子"""
        this_month = date.today().month
        profile = get_cuisine_profile(cuisine)
        if not profile:
            return 1.0

        common_ing = profile.get("common_ingredients", [])
        # 在 MALAYSIA_INGREDIENTS 中查找匹配的食材
        total_factor = 0.0
        match_count = 0

        for ing_key, ing_profile in MALAYSIA_INGREDIENTS.items():
            ing_name_ms = ing_profile.get("local_names", {}).get("ms", "").lower()
            if any(ci.lower() in ing_name_ms or ing_name_ms in ci.lower() for ci in common_ing):
                factors = ing_profile.get("seasonal_price_fluctuation", {})
                for season_key, factor in factors.items():
                    parts = season_key.split("-")
                    if len(parts) == 2:
                        try:
                            month_map = {
                                "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
                                "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
                            }
                            start_m = month_map.get(parts[0][:3], 1)
                            end_m = month_map.get(parts[1][:3], 12)
                            in_range = (start_m <= this_month <= end_m) if start_m <= end_m else (
                                this_month >= start_m or this_month <= end_m
                            )
                            if in_range:
                                total_factor += factor
                                match_count += 1
                                break
                        except (KeyError, IndexError):
                            pass

        return round(total_factor / max(match_count, 1), 4) if match_count > 0 else 1.0

    # ─── 基于配置的 Halal 检查 ───────────────────────────────

    def _generate_config_halal_check(
        self,
        cuisine_mix: list[str] | None,
    ) -> dict[str, Any]:
        """基于 MALAYSIA_INGREDIENTS 配置数据的默认 Halal 合规检查"""
        halal_ingredients = get_halal_certified_ingredients()
        all_ingredients = MALAYSIA_INGREDIENTS
        total = len(all_ingredients)
        certified = len(halal_ingredients)
        pct = round(certified / max(total, 1) * 100, 1)

        non_certified_list = [
            {
                "ingredient_name": k,
                "local_name_ms": v.get("local_names", {}).get("ms", k),
                "supplier": (v.get("typical_suppliers") or ["unknown"])[0],
                "risk": "high" if v.get("is_perishable", False) else "low",
            }
            for k, v in all_ingredients.items()
            if not v.get("halal_certified", False)
        ]

        overall_status = "compliant" if pct >= 95 else ("warning" if pct >= 80 else "non_compliant")

        return {
            "store_id": "",
            "store_name": "",
            "overall_status": overall_status,
            "note": "基于 Malaysia Ingredient Catalog 配置数据分析（非实时库存数据）",
            "certified_ingredients": {
                "count": certified,
                "total": total,
                "percentage": pct,
            },
            "non_certified_ingredients": non_certified_list[:5],
            "supplier_halal_status": [],
            "warnings": (
                [f"发现 {len(non_certified_list)} 种食材无 Halal 认证"]
                if non_certified_list else []
            ),
            "recommendations": [
                "确认所有食材供应商持有有效的 JAKIM Halal 认证",
                "对非认证食材建立替换计划",
                f"食材目录中 Halal 认证比例: {pct}%",
            ],
        }

    # ─── 基于配置的定价建议 ──────────────────────────────────

    def _generate_config_based_pricing_recs(
        self,
        cuisine_mix: list[str],
    ) -> list[dict[str, Any]]:
        """基于 CUISINE_PROFILES 配置数据的默认定价建议"""
        recommendations: list[dict[str, Any]] = []

        for cuisine in cuisine_mix:
            profile = get_cuisine_profile(cuisine)
            if not profile:
                continue

            avg_spend = profile.get("avg_spend_per_pax_fen", 2000)
            popular_dishes = profile.get("popular_dishes", [])[:3]

            for dish in popular_dishes:
                cost_factor = self._get_seasonal_cost_factor(cuisine)
                suggested_price = int(round(avg_spend * cost_factor))

                recommendations.append({
                    "recommendation_type": "price_increase" if cost_factor > 1.05 else "menu_reposition",
                    "dish_name": dish,
                    "cuisine_category": cuisine,
                    "current_price_fen": avg_spend,
                    "current_price_rm": round(avg_spend / 100, 2),
                    "suggested_price_fen": suggested_price,
                    "suggested_price_rm": round(suggested_price / 100, 2),
                    "current_margin_pct": 35.0,
                    "expected_margin_impact_pct": round((cost_factor - 1.0) * 100, 1),
                    "rationale": (
                        f"根据 {cuisine} 菜系客单价（RM {avg_spend / 100:.0f}）和"
                        f"季节性食材成本（×{cost_factor}）优化定价"
                    ),
                    "risk_level": "low",
                    "sst_category": "standard",
                    "sst_impact_fen": int(round(avg_spend * 0.06 / 1.06)),
                })

        return recommendations
