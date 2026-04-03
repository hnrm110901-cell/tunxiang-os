"""自动采购推荐 Agent

核心逻辑：
  1. 获取门店所有活跃原料
  2. 计算日均消耗（优先出库流水，历史不足时BOM反推）
  3. 安全库存 = 日均消耗 × (采购周期 + 安全天数)
  4. 建议采购量 = max(0, 安全库存 - 当前库存)
  5. 建议量 > 0 时：评分选最优供应商
  6. 按紧急程度排序（urgent优先）
  7. 建议单状态 = draft，需人工确认后转正式申购

供应商评分公式：准期率×0.5 + 质量合格率×0.3 + 价格竞争力×0.2

金额单位：分（fen）。
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import structlog
from pydantic import BaseModel, Field

from .demand_forecast import DemandForecastService

log = structlog.get_logger(__name__)

# 默认配置常量
DEFAULT_SAFETY_DAYS = 3          # 安全天数
DEFAULT_REORDER_CYCLE_DAYS = 2   # 默认采购周期（天）
DEFAULT_URGENT_THRESHOLD = 3     # 紧急预警阈值（天）

# 供应商评分权重
SCORE_WEIGHT_ON_TIME = 0.5
SCORE_WEIGHT_QUALITY = 0.3
SCORE_WEIGHT_PRICE = 0.2


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _gen_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  数据模型
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class ProcurementRecommendation(BaseModel):
    """单条采购建议"""

    recommendation_id: str
    ingredient_id: str
    ingredient_name: str
    current_qty: float
    daily_consumption: float
    safety_stock: float
    recommended_qty: float = Field(ge=0)
    unit: str
    unit_price_fen: int = Field(ge=0)
    estimated_cost_fen: int = Field(ge=0)
    supplier_id: Optional[str] = None
    supplier_name: Optional[str] = None
    supplier_score: Optional[float] = None
    is_urgent: bool
    days_remaining: Optional[float] = None   # 按日均消耗，还能用多少天
    status: str = "draft"                    # draft | applied
    store_id: str
    tenant_id: str
    created_at: str = Field(default_factory=_now_iso)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  主服务
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class AutoProcurementService:
    """自动采购推荐 Agent

    Args:
        safety_days: 安全天数（默认3天）
        urgent_threshold_days: 紧急预警阈值（默认3天用量）
    """

    SAFETY_DAYS = DEFAULT_SAFETY_DAYS
    URGENT_THRESHOLD = DEFAULT_URGENT_THRESHOLD

    def __init__(
        self,
        safety_days: int = DEFAULT_SAFETY_DAYS,
        urgent_threshold_days: int = DEFAULT_URGENT_THRESHOLD,
    ) -> None:
        self.safety_days = safety_days
        self.urgent_threshold_days = urgent_threshold_days
        self._forecast_svc = DemandForecastService()

    # ──────────────────────────────────────────────────────
    #  纯计算方法（无IO，便于测试）
    # ──────────────────────────────────────────────────────

    def calc_safety_stock(
        self,
        daily_consumption: float,
        reorder_cycle_days: int = DEFAULT_REORDER_CYCLE_DAYS,
    ) -> float:
        """计算安全库存

        公式：日均消耗 × (采购周期 + 安全天数)
        """
        return daily_consumption * (reorder_cycle_days + self.safety_days)

    def calc_recommended_quantity(
        self,
        safety_stock: float,
        current_qty: float,
    ) -> float:
        """计算建议采购量

        建议量 = max(0, 安全库存 - 当前库存)
        库存充足时返回0，不建议采购。
        """
        return max(0.0, safety_stock - current_qty)

    def is_urgent(
        self,
        daily_consumption: float,
        current_qty: float,
    ) -> bool:
        """判断是否需要紧急采购

        库存低于 urgent_threshold_days × 日均消耗 时标记urgent。
        零消耗时永远不标记urgent（避免误报）。
        """
        if daily_consumption <= 0:
            return False
        days_remaining = current_qty / daily_consumption
        return days_remaining < self.urgent_threshold_days

    def calc_supplier_score(
        self,
        on_time_rate: float,
        quality_rate: float,
        price_score: float,
    ) -> float:
        """计算供应商综合评分

        公式：准期率×0.5 + 质量合格率×0.3 + 价格竞争力×0.2

        Args:
            on_time_rate: 准期率（0~1）
            quality_rate: 质量合格率（0~1）
            price_score: 价格竞争力评分（0~1，越低价格越高分）

        Returns:
            综合评分（0~1）
        """
        return (
            on_time_rate * SCORE_WEIGHT_ON_TIME
            + quality_rate * SCORE_WEIGHT_QUALITY
            + price_score * SCORE_WEIGHT_PRICE
        )

    # ──────────────────────────────────────────────────────
    #  供应商选优
    # ──────────────────────────────────────────────────────

    async def select_best_supplier(
        self,
        suppliers: list[dict],
        ingredient_id: str,
        tenant_id: str,
        db: Any,
    ) -> Optional[dict]:
        """从候选供应商列表中选出综合评分最高的

        Args:
            suppliers: 供应商列表，每项包含 supplier_id, on_time_rate,
                       quality_rate, price_score
            ingredient_id: 原料ID（用于DB查询时按原料过滤）
            tenant_id: 租户ID
            db: 数据库会话（None时使用suppliers列表中的数据）

        Returns:
            评分最高的供应商字典，无候选时返回None
        """
        if not suppliers:
            return None

        if db is not None:
            # 生产模式：从DB补充历史统计数据
            enriched = await self._enrich_suppliers_from_db(
                suppliers, ingredient_id, tenant_id, db
            )
        else:
            enriched = suppliers

        scored = []
        for sup in enriched:
            score = self.calc_supplier_score(
                on_time_rate=float(sup.get("on_time_rate", 0)),
                quality_rate=float(sup.get("quality_rate", 0)),
                price_score=float(sup.get("price_score", 0)),
            )
            scored.append({**sup, "_score": score})

        best = max(scored, key=lambda s: s["_score"])
        return best

    async def _enrich_suppliers_from_db(
        self,
        suppliers: list[dict],
        ingredient_id: str,
        tenant_id: str,
        db: Any,
    ) -> list[dict]:
        """从DB历史收货记录补充供应商评分数据

        从 ingredient_transactions 中统计：
        - 准期率：按时到货次数 / 总到货次数
        - 质量合格率：pass次数 / 总次数
        若无历史数据，保留suppliers列表中的原始值（或默认0）。
        """
        enriched = []
        for sup in suppliers:
            supplier_id = sup.get("supplier_id", "")
            try:
                score_data = await self.get_supplier_score(
                    supplier_id=supplier_id,
                    ingredient_id=ingredient_id,
                    tenant_id=tenant_id,
                    db=db,
                )
                merged = {
                    **sup,
                    "on_time_rate": score_data.get("on_time_rate", sup.get("on_time_rate", 0)),
                    "quality_rate": score_data.get("quality_rate", sup.get("quality_rate", 0)),
                    "price_score": score_data.get("price_score", sup.get("price_score", 0)),
                }
            except Exception:  # noqa: BLE001 — 评分不可用时保留原数据
                merged = sup
            enriched.append(merged)
        return enriched

    async def get_supplier_score(
        self,
        supplier_id: str,
        ingredient_id: str,
        tenant_id: str,
        db: Any,
    ) -> dict:
        """查询供应商历史评分数据

        从 receiving_records 统计：
        - on_time_rate: 准期率
        - quality_rate: 质量合格率
        - price_score: 价格竞争力（当前实现为0.5占位，实际由比价逻辑填充）

        Returns:
            {"on_time_rate": float, "quality_rate": float, "price_score": float,
             "total_deliveries": int}
        """
        if db is None:
            return {"on_time_rate": 0.0, "quality_rate": 0.0, "price_score": 0.5, "total_deliveries": 0}

        try:
            from sqlalchemy import text

            # 查询收货记录中该供应商对该原料的历史数据
            # 注：实际表结构依赖receiving_records表的具体字段
            # 此处使用raw SQL保持灵活性
            sql = text("""
                SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN on_time = TRUE THEN 1 ELSE 0 END) AS on_time_count,
                    SUM(CASE WHEN quality = 'pass' THEN 1 ELSE 0 END) AS quality_count
                FROM receiving_records
                WHERE supplier_id = :supplier_id
                  AND ingredient_id = :ingredient_id
                  AND tenant_id = :tenant_id
                  AND is_deleted = FALSE
            """)
            result = await db.execute(sql, {
                "supplier_id": supplier_id,
                "ingredient_id": ingredient_id,
                "tenant_id": tenant_id,
            })
            row = result.fetchone()
            total = int(row.total or 0) if row else 0
            if total == 0:
                return {"on_time_rate": 0.0, "quality_rate": 0.0, "price_score": 0.5, "total_deliveries": 0}

            on_time_rate = int(row.on_time_count or 0) / total
            quality_rate = int(row.quality_count or 0) / total

            log.info(
                "auto_procurement.supplier_score",
                supplier_id=supplier_id,
                ingredient_id=ingredient_id,
                total_deliveries=total,
                on_time_rate=round(on_time_rate, 3),
                quality_rate=round(quality_rate, 3),
                tenant_id=tenant_id,
            )
            return {
                "on_time_rate": on_time_rate,
                "quality_rate": quality_rate,
                "price_score": 0.5,   # 占位：由外部比价逻辑填入
                "total_deliveries": total,
            }
        except Exception:  # noqa: BLE001 — 表不存在等情况静默返回默认值
            return {"on_time_rate": 0.0, "quality_rate": 0.0, "price_score": 0.5, "total_deliveries": 0}

    # ──────────────────────────────────────────────────────
    #  核心：生成采购建议（生产模式）
    # ──────────────────────────────────────────────────────

    async def generate_recommendations(
        self,
        store_id: str,
        tenant_id: str,
        db: Any,
        reorder_cycle_days: int = DEFAULT_REORDER_CYCLE_DAYS,
        forecast_days: int = 7,
    ) -> list[ProcurementRecommendation]:
        """为门店生成采购建议（生产模式，依赖DB）

        流程：
          1. 从DB获取该门店所有活跃原料
          2. 对每种原料预测未来consumption
          3. 计算安全库存和建议采购量
          4. 建议量>0时，查找最优供应商
          5. 按紧急程度排序

        Args:
            store_id: 门店ID
            tenant_id: 租户ID
            db: 数据库会话
            reorder_cycle_days: 采购周期（天）
            forecast_days: 预测天数

        Returns:
            采购建议列表（仅含需要采购的原料，按urgency排序）
        """
        import uuid as _uuid_mod

        from sqlalchemy import select, text

        from shared.ontology.src.entities import Ingredient

        def _uuid(val: str) -> _uuid_mod.UUID:
            return _uuid_mod.UUID(str(val))

        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": tenant_id},
        )

        ing_q = (
            select(Ingredient)
            .where(
                Ingredient.tenant_id == _uuid(tenant_id),
                Ingredient.store_id == _uuid(store_id),
                Ingredient.is_deleted == False,  # noqa: E712
            )
        )
        result = await db.execute(ing_q)
        ingredients = result.scalars().all()

        recommendations: list[ProcurementRecommendation] = []

        for ing in ingredients:
            ingredient_id = str(ing.id)
            current_qty = float(ing.current_quantity or 0)
            unit_price_fen = int(ing.unit_price_fen or 0)

            daily = await self._forecast_svc.get_daily_consumption(
                ingredient_id=ingredient_id,
                store_id=store_id,
                days=forecast_days,
                tenant_id=tenant_id,
                db=db,
            )

            safety_stock = self.calc_safety_stock(daily, reorder_cycle_days)
            # 也参考原料自身min_quantity设置
            effective_safety = max(safety_stock, float(ing.min_quantity or 0))
            recommended_qty = self.calc_recommended_quantity(effective_safety, current_qty)

            if recommended_qty <= 0:
                continue

            urgent = self.is_urgent(daily, current_qty)
            days_remaining = (current_qty / daily) if daily > 0 else None

            # 查找最优供应商（当前从ingredients表获取已配置供应商）
            supplier_id: Optional[str] = None
            supplier_name: Optional[str] = None
            supplier_score: Optional[float] = None

            if ing.supplier_name:
                supplier_name = ing.supplier_name
                # 尝试从历史获取评分
                try:
                    score_data = await self.get_supplier_score("", ingredient_id, tenant_id, db)
                    supplier_score = self.calc_supplier_score(
                        score_data["on_time_rate"],
                        score_data["quality_rate"],
                        score_data["price_score"],
                    )
                except Exception:  # noqa: BLE001
                    pass

            estimated_cost_fen = int(recommended_qty * unit_price_fen)

            rec = ProcurementRecommendation(
                recommendation_id=_gen_id("rec"),
                ingredient_id=ingredient_id,
                ingredient_name=ing.ingredient_name,
                current_qty=current_qty,
                daily_consumption=round(daily, 4),
                safety_stock=round(effective_safety, 2),
                recommended_qty=round(recommended_qty, 2),
                unit=ing.unit,
                unit_price_fen=unit_price_fen,
                estimated_cost_fen=estimated_cost_fen,
                supplier_id=supplier_id,
                supplier_name=supplier_name,
                supplier_score=supplier_score,
                is_urgent=urgent,
                days_remaining=round(days_remaining, 1) if days_remaining is not None else None,
                status="draft",
                store_id=store_id,
                tenant_id=tenant_id,
            )
            recommendations.append(rec)

        # urgent排前面
        recommendations.sort(key=lambda r: (0 if r.is_urgent else 1))

        log.info(
            "auto_procurement.generate_recommendations",
            store_id=store_id,
            tenant_id=tenant_id,
            total=len(recommendations),
            urgent=sum(1 for r in recommendations if r.is_urgent),
        )
        return recommendations

    # ──────────────────────────────────────────────────────
    #  测试辅助：Mock模式（无需DB）
    # ──────────────────────────────────────────────────────

    async def generate_recommendations_from_mock(
        self,
        mock_ingredients: list[dict],
        store_id: str,
        tenant_id: str,
        db: Any,
    ) -> list[ProcurementRecommendation]:
        """从mock数据生成采购建议（测试用）

        每条mock原料需包含：
          ingredient_id, ingredient_name, current_qty, unit, unit_price_fen,
          _mock_daily, _mock_supplier（{supplier_id, supplier_name}）,
          reorder_cycle_days
        """
        recommendations: list[ProcurementRecommendation] = []

        for ing in mock_ingredients:
            current_qty = float(ing["current_qty"])
            daily = float(ing["_mock_daily"])
            unit_price_fen = int(ing.get("unit_price_fen", 0))
            reorder_cycle_days = int(ing.get("reorder_cycle_days", DEFAULT_REORDER_CYCLE_DAYS))

            safety_stock = self.calc_safety_stock(daily, reorder_cycle_days)
            recommended_qty = self.calc_recommended_quantity(safety_stock, current_qty)

            if recommended_qty <= 0:
                continue

            urgent = self.is_urgent(daily, current_qty)
            days_remaining = (current_qty / daily) if daily > 0 else None
            estimated_cost_fen = int(recommended_qty * unit_price_fen)

            mock_sup = ing.get("_mock_supplier") or {}
            rec = ProcurementRecommendation(
                recommendation_id=_gen_id("rec"),
                ingredient_id=ing["ingredient_id"],
                ingredient_name=ing["ingredient_name"],
                current_qty=current_qty,
                daily_consumption=round(daily, 4),
                safety_stock=round(safety_stock, 2),
                recommended_qty=round(recommended_qty, 2),
                unit=ing.get("unit", "kg"),
                unit_price_fen=unit_price_fen,
                estimated_cost_fen=estimated_cost_fen,
                supplier_id=mock_sup.get("supplier_id"),
                supplier_name=mock_sup.get("supplier_name"),
                supplier_score=None,
                is_urgent=urgent,
                days_remaining=round(days_remaining, 1) if days_remaining is not None else None,
                status="draft",
                store_id=store_id,
                tenant_id=tenant_id,
            )
            recommendations.append(rec)

        # urgent排前面
        recommendations.sort(key=lambda r: (0 if r.is_urgent else 1))

        log.debug(
            "auto_procurement.generate_recommendations_from_mock",
            store_id=store_id,
            tenant_id=tenant_id,
            total=len(recommendations),
        )
        return recommendations

    # ──────────────────────────────────────────────────────
    #  将建议转为正式申购单（需人工触发）
    # ──────────────────────────────────────────────────────

    async def create_requisition_from_recommendations(
        self,
        recommendations: list[ProcurementRecommendation],
        store_id: str,
        tenant_id: str,
        db: Any,
        requester_id: str = "auto_procurement_agent",
    ) -> dict:
        """将采购建议单转为正式申购单（需人工确认触发）

        调用现有 requisition 服务的 create_requisition 逻辑，
        保留完整审批流程（不自动提交审批）。

        Args:
            recommendations: 采购建议列表（不可为空）
            store_id: 门店ID
            tenant_id: 租户ID
            db: 数据库会话
            requester_id: 申请人ID（默认标注为Agent）

        Returns:
            申购单字典（status = draft，等待人工提交审批）

        Raises:
            ValueError: recommendations为空时
        """
        if not recommendations:
            raise ValueError("至少一项采购建议才能转为申购单")

        items = [
            {
                "ingredient_id": rec.ingredient_id,
                "name": rec.ingredient_name,
                "quantity": rec.recommended_qty,
                "unit": rec.unit,
                "estimated_price_fen": rec.unit_price_fen,
            }
            for rec in recommendations
        ]

        total_fen = sum(rec.estimated_cost_fen for rec in recommendations)

        if db is not None:
            # 生产模式：调用现有申购服务
            try:
                from .requisition import create_requisition
                result = await create_requisition(
                    store_id=store_id,
                    items=items,
                    requester_id=requester_id,
                    tenant_id=tenant_id,
                    db=db,
                )
                result["source"] = "auto_procurement_agent"
                result["recommendation_ids"] = [r.recommendation_id for r in recommendations]
                return result
            except ImportError:
                pass  # 测试环境无此依赖，继续走mock路径

        # 测试模式 / 备用路径：直接生成申购单结构
        requisition_id = _gen_id("req")
        result = {
            "requisition_id": requisition_id,
            "store_id": store_id,
            "tenant_id": tenant_id,
            "requester_id": requester_id,
            "status": "draft",
            "item_count": len(items),
            "items": items,
            "total_estimated_fen": total_fen,
            "source": "auto_procurement_agent",
            "recommendation_ids": [r.recommendation_id for r in recommendations],
            "created_at": _now_iso(),
        }

        log.info(
            "auto_procurement.create_requisition",
            requisition_id=requisition_id,
            store_id=store_id,
            tenant_id=tenant_id,
            item_count=len(items),
            total_estimated_fen=total_fen,
            urgent_count=sum(1 for r in recommendations if r.is_urgent),
        )
        return result
