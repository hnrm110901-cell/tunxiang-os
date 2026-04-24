"""智能储值服务 — 推荐生成 + 接受/拒绝 + 规则管理 + 统计

核心逻辑：根据客单价 × 倍数计算多档储值推荐。
例：客单价 88 元 → 推荐 200/300/500 三档，每档对应不同赠送比例。
金额单位：分（fen）。
"""

import json
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()


class SmartRechargeService:
    """智能储值推荐服务"""

    # ── 生成推荐 ─────────────────────────────────────────────

    @staticmethod
    async def generate_recommendation(
        db: AsyncSession,
        tenant_id: str,
        *,
        store_id: str,
        customer_id: Optional[str] = None,
        order_id: str,
        order_amount_fen: int,
        employee_id: Optional[str] = None,
    ) -> dict:
        """根据订单金额生成多档储值推荐。

        1. 查找门店/品牌下生效的储值规则（按 priority 排序）
        2. 根据 multiplier_tiers 计算推荐档位
        3. 写入 smart_recharge_recommendations 表
        """
        # 1) 获取生效规则
        today = date.today()
        rules_result = await db.execute(
            text("""
                SELECT id, rule_name, multiplier_tiers, bonus_type,
                       bonus_value, min_recharge_fen, max_recharge_fen,
                       coupon_template_id
                FROM smart_recharge_rules
                WHERE tenant_id = :tenant_id
                  AND (store_id = :store_id OR store_id IS NULL)
                  AND is_active = TRUE
                  AND effective_from <= :today
                  AND (effective_until IS NULL OR effective_until >= :today)
                  AND is_deleted = FALSE
                ORDER BY priority DESC, store_id NULLS LAST
                LIMIT 1
            """),
            {"tenant_id": tenant_id, "store_id": store_id, "today": today},
        )
        rule = rules_result.fetchone()

        if not rule:
            # 无可用规则，使用默认倍数
            tiers = _default_tiers(order_amount_fen)
        else:
            tiers = _calculate_tiers(
                order_amount_fen=order_amount_fen,
                multiplier_tiers=rule.multiplier_tiers,
                bonus_type=rule.bonus_type,
                bonus_value=float(rule.bonus_value) if rule.bonus_value else 0,
                min_fen=rule.min_recharge_fen or 0,
                max_fen=rule.max_recharge_fen or 999900,
            )

        # 2) 写入推荐记录
        rec_id = str(uuid.uuid4())
        await db.execute(
            text("""
                INSERT INTO smart_recharge_recommendations (
                    tenant_id, id, store_id, customer_id, order_id,
                    order_amount_fen, recommended_tiers, employee_id
                ) VALUES (
                    :tenant_id, :id, :store_id, :customer_id, :order_id,
                    :order_amount_fen, :recommended_tiers::JSONB, :employee_id
                )
            """),
            {
                "tenant_id": tenant_id,
                "id": rec_id,
                "store_id": store_id,
                "customer_id": customer_id,
                "order_id": order_id,
                "order_amount_fen": order_amount_fen,
                "recommended_tiers": json.dumps(tiers),
                "employee_id": employee_id,
            },
        )
        await db.commit()

        logger.info(
            "smart_recharge_recommended",
            rec_id=rec_id,
            order_amount_fen=order_amount_fen,
            tier_count=len(tiers),
        )
        return {
            "id": rec_id,
            "order_amount_fen": order_amount_fen,
            "recommended_tiers": tiers,
            "status": "recommended",
        }

    # ── 接受推荐 ─────────────────────────────────────────────

    @staticmethod
    async def accept_recommendation(
        db: AsyncSession,
        tenant_id: str,
        *,
        recommendation_id: str,
        selected_tier: dict,
        recharge_amount_fen: int,
        bonus_amount_fen: int = 0,
    ) -> dict:
        """客户接受某一档储值推荐"""
        await db.execute(
            text("""
                UPDATE smart_recharge_recommendations
                SET selected_tier       = :selected_tier::JSONB,
                    recharge_amount_fen = :recharge_amount_fen,
                    bonus_amount_fen    = :bonus_amount_fen,
                    status              = 'accepted',
                    decided_at          = now(),
                    updated_at          = now()
                WHERE tenant_id = :tenant_id
                  AND id = :recommendation_id
                  AND status = 'recommended'
                  AND is_deleted = FALSE
            """),
            {
                "tenant_id": tenant_id,
                "recommendation_id": recommendation_id,
                "selected_tier": json.dumps(selected_tier),
                "recharge_amount_fen": recharge_amount_fen,
                "bonus_amount_fen": bonus_amount_fen,
            },
        )
        await db.commit()
        logger.info(
            "smart_recharge_accepted",
            recommendation_id=recommendation_id,
            recharge_amount_fen=recharge_amount_fen,
        )
        return {"id": recommendation_id, "status": "accepted", "recharge_amount_fen": recharge_amount_fen}

    # ── 拒绝推荐 ─────────────────────────────────────────────

    @staticmethod
    async def decline_recommendation(
        db: AsyncSession,
        tenant_id: str,
        *,
        recommendation_id: str,
    ) -> dict:
        """客户拒绝储值推荐"""
        await db.execute(
            text("""
                UPDATE smart_recharge_recommendations
                SET status     = 'declined',
                    decided_at = now(),
                    updated_at = now()
                WHERE tenant_id = :tenant_id
                  AND id = :recommendation_id
                  AND status = 'recommended'
                  AND is_deleted = FALSE
            """),
            {"tenant_id": tenant_id, "recommendation_id": recommendation_id},
        )
        await db.commit()
        logger.info("smart_recharge_declined", recommendation_id=recommendation_id)
        return {"id": recommendation_id, "status": "declined"}

    # ── 推荐列表 ─────────────────────────────────────────────

    @staticmethod
    async def list_recommendations(
        db: AsyncSession,
        tenant_id: str,
        *,
        store_id: str,
        status: Optional[str] = None,
        customer_id: Optional[str] = None,
        page: int = 1,
        size: int = 20,
    ) -> dict:
        """列出储值推荐记录（可按状态/客户过滤）"""
        conditions = ["tenant_id = :tenant_id", "store_id = :store_id", "is_deleted = FALSE"]
        params: dict = {"tenant_id": tenant_id, "store_id": store_id}

        if status:
            conditions.append("status = :status")
            params["status"] = status
        if customer_id:
            conditions.append("customer_id = :customer_id")
            params["customer_id"] = customer_id

        where = " AND ".join(conditions)

        count_result = await db.execute(
            text(f"SELECT COUNT(*) FROM smart_recharge_recommendations WHERE {where}"),
            params,
        )
        total = count_result.scalar() or 0

        offset = (page - 1) * size
        params["limit"] = size
        params["offset"] = offset
        items_result = await db.execute(
            text(f"""
                SELECT id, customer_id, order_id, order_amount_fen,
                       recommended_tiers, selected_tier,
                       recharge_amount_fen, bonus_amount_fen,
                       status, recommended_at, decided_at, employee_id
                FROM smart_recharge_recommendations
                WHERE {where}
                ORDER BY recommended_at DESC
                LIMIT :limit OFFSET :offset
            """),
            params,
        )
        rows = items_result.fetchall()
        items = [
            {
                "id": str(r.id),
                "customer_id": str(r.customer_id) if r.customer_id else None,
                "order_id": str(r.order_id),
                "order_amount_fen": r.order_amount_fen,
                "recommended_tiers": r.recommended_tiers,
                "selected_tier": r.selected_tier,
                "recharge_amount_fen": r.recharge_amount_fen,
                "bonus_amount_fen": r.bonus_amount_fen,
                "status": r.status,
                "recommended_at": r.recommended_at.isoformat() if r.recommended_at else None,
                "decided_at": r.decided_at.isoformat() if r.decided_at else None,
                "employee_id": str(r.employee_id) if r.employee_id else None,
            }
            for r in rows
        ]
        return {"items": items, "total": total, "page": page, "size": size}

    # ── 统计 ─────────────────────────────────────────────────

    @staticmethod
    async def get_stats(
        db: AsyncSession,
        tenant_id: str,
        *,
        store_id: str,
        start_date: date,
        end_date: date,
    ) -> dict:
        """储值推荐转化统计"""
        result = await db.execute(
            text("""
                SELECT
                    COUNT(*)                                                AS total_recommendations,
                    COUNT(*) FILTER (WHERE status = 'accepted')            AS accepted_count,
                    COUNT(*) FILTER (WHERE status = 'declined')            AS declined_count,
                    COUNT(*) FILTER (WHERE status = 'expired')             AS expired_count,
                    COALESCE(SUM(recharge_amount_fen) FILTER (WHERE status = 'accepted'), 0) AS total_recharge_fen,
                    COALESCE(SUM(bonus_amount_fen) FILTER (WHERE status = 'accepted'), 0)    AS total_bonus_fen,
                    COALESCE(AVG(order_amount_fen), 0)                     AS avg_order_amount_fen
                FROM smart_recharge_recommendations
                WHERE tenant_id = :tenant_id
                  AND store_id  = :store_id
                  AND recommended_at::DATE BETWEEN :start_date AND :end_date
                  AND is_deleted = FALSE
            """),
            {
                "tenant_id": tenant_id,
                "store_id": store_id,
                "start_date": start_date,
                "end_date": end_date,
            },
        )
        row = result.fetchone()
        total = row.total_recommendations if row else 0
        accepted = row.accepted_count if row else 0
        conversion_rate = round(accepted / total * 100, 2) if total > 0 else 0

        return {
            "total_recommendations": total,
            "accepted_count": accepted,
            "declined_count": row.declined_count if row else 0,
            "expired_count": row.expired_count if row else 0,
            "conversion_rate": conversion_rate,
            "total_recharge_fen": row.total_recharge_fen if row else 0,
            "total_bonus_fen": row.total_bonus_fen if row else 0,
            "avg_order_amount_fen": int(row.avg_order_amount_fen) if row else 0,
        }

    # ── 规则 CRUD ────────────────────────────────────────────

    @staticmethod
    async def create_rule(
        db: AsyncSession,
        tenant_id: str,
        *,
        store_id: Optional[str] = None,
        brand_id: Optional[str] = None,
        rule_name: str,
        multiplier_tiers: list,
        bonus_type: str = "percentage",
        bonus_value: float = 0,
        min_recharge_fen: int = 0,
        max_recharge_fen: int = 999900,
        coupon_template_id: Optional[str] = None,
        effective_from: date = None,
        effective_until: Optional[date] = None,
        priority: int = 0,
    ) -> dict:
        """创建智能储值规则"""
        rule_id = str(uuid.uuid4())
        if effective_from is None:
            effective_from = date.today()

        await db.execute(
            text("""
                INSERT INTO smart_recharge_rules (
                    tenant_id, id, store_id, brand_id, rule_name,
                    multiplier_tiers, bonus_type, bonus_value,
                    min_recharge_fen, max_recharge_fen, coupon_template_id,
                    effective_from, effective_until, priority
                ) VALUES (
                    :tenant_id, :id, :store_id, :brand_id, :rule_name,
                    :multiplier_tiers::JSONB, :bonus_type, :bonus_value,
                    :min_recharge_fen, :max_recharge_fen, :coupon_template_id,
                    :effective_from, :effective_until, :priority
                )
            """),
            {
                "tenant_id": tenant_id,
                "id": rule_id,
                "store_id": store_id,
                "brand_id": brand_id,
                "rule_name": rule_name,
                "multiplier_tiers": json.dumps(multiplier_tiers),
                "bonus_type": bonus_type,
                "bonus_value": bonus_value,
                "min_recharge_fen": min_recharge_fen,
                "max_recharge_fen": max_recharge_fen,
                "coupon_template_id": coupon_template_id,
                "effective_from": effective_from,
                "effective_until": effective_until,
                "priority": priority,
            },
        )
        await db.commit()
        logger.info("smart_recharge_rule_created", rule_id=rule_id, name=rule_name)
        return {"id": rule_id, "rule_name": rule_name}

    @staticmethod
    async def update_rule(
        db: AsyncSession,
        tenant_id: str,
        *,
        rule_id: str,
        rule_name: Optional[str] = None,
        is_active: Optional[bool] = None,
        multiplier_tiers: Optional[list] = None,
        bonus_type: Optional[str] = None,
        bonus_value: Optional[float] = None,
        effective_until: Optional[date] = None,
        priority: Optional[int] = None,
    ) -> dict:
        """更新储值规则"""
        sets: list[str] = ["updated_at = now()"]
        params: dict = {"tenant_id": tenant_id, "rule_id": rule_id}

        if rule_name is not None:
            sets.append("rule_name = :rule_name")
            params["rule_name"] = rule_name
        if is_active is not None:
            sets.append("is_active = :is_active")
            params["is_active"] = is_active
        if multiplier_tiers is not None:
            sets.append("multiplier_tiers = :multiplier_tiers::JSONB")
            params["multiplier_tiers"] = json.dumps(multiplier_tiers)
        if bonus_type is not None:
            sets.append("bonus_type = :bonus_type")
            params["bonus_type"] = bonus_type
        if bonus_value is not None:
            sets.append("bonus_value = :bonus_value")
            params["bonus_value"] = bonus_value
        if effective_until is not None:
            sets.append("effective_until = :effective_until")
            params["effective_until"] = effective_until
        if priority is not None:
            sets.append("priority = :priority")
            params["priority"] = priority

        await db.execute(
            text(f"""
                UPDATE smart_recharge_rules
                SET {', '.join(sets)}
                WHERE tenant_id = :tenant_id AND id = :rule_id AND is_deleted = FALSE
            """),
            params,
        )
        await db.commit()
        logger.info("smart_recharge_rule_updated", rule_id=rule_id)
        return {"id": rule_id, "updated": True}

    @staticmethod
    async def get_rule(db: AsyncSession, tenant_id: str, rule_id: str) -> Optional[dict]:
        """获取单个规则"""
        result = await db.execute(
            text("""
                SELECT id, store_id, brand_id, rule_name, is_active,
                       multiplier_tiers, bonus_type, bonus_value,
                       min_recharge_fen, max_recharge_fen, coupon_template_id,
                       effective_from, effective_until, priority, created_at
                FROM smart_recharge_rules
                WHERE tenant_id = :tenant_id AND id = :rule_id AND is_deleted = FALSE
            """),
            {"tenant_id": tenant_id, "rule_id": rule_id},
        )
        row = result.fetchone()
        if not row:
            return None
        return {
            "id": str(row.id),
            "store_id": str(row.store_id) if row.store_id else None,
            "brand_id": str(row.brand_id) if row.brand_id else None,
            "rule_name": row.rule_name,
            "is_active": row.is_active,
            "multiplier_tiers": row.multiplier_tiers,
            "bonus_type": row.bonus_type,
            "bonus_value": float(row.bonus_value) if row.bonus_value else 0,
            "min_recharge_fen": row.min_recharge_fen,
            "max_recharge_fen": row.max_recharge_fen,
            "coupon_template_id": str(row.coupon_template_id) if row.coupon_template_id else None,
            "effective_from": str(row.effective_from),
            "effective_until": str(row.effective_until) if row.effective_until else None,
            "priority": row.priority,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }

    @staticmethod
    async def list_rules(
        db: AsyncSession,
        tenant_id: str,
        *,
        store_id: Optional[str] = None,
        is_active: Optional[bool] = None,
        page: int = 1,
        size: int = 20,
    ) -> dict:
        """列出储值规则"""
        conditions = ["tenant_id = :tenant_id", "is_deleted = FALSE"]
        params: dict = {"tenant_id": tenant_id}

        if store_id:
            conditions.append("(store_id = :store_id OR store_id IS NULL)")
            params["store_id"] = store_id
        if is_active is not None:
            conditions.append("is_active = :is_active")
            params["is_active"] = is_active

        where = " AND ".join(conditions)

        count_result = await db.execute(text(f"SELECT COUNT(*) FROM smart_recharge_rules WHERE {where}"), params)
        total = count_result.scalar() or 0

        offset = (page - 1) * size
        params["limit"] = size
        params["offset"] = offset
        items_result = await db.execute(
            text(f"""
                SELECT id, store_id, brand_id, rule_name, is_active,
                       bonus_type, bonus_value, priority,
                       effective_from, effective_until, created_at
                FROM smart_recharge_rules
                WHERE {where}
                ORDER BY priority DESC, created_at DESC
                LIMIT :limit OFFSET :offset
            """),
            params,
        )
        rows = items_result.fetchall()
        items = [
            {
                "id": str(r.id),
                "store_id": str(r.store_id) if r.store_id else None,
                "brand_id": str(r.brand_id) if r.brand_id else None,
                "rule_name": r.rule_name,
                "is_active": r.is_active,
                "bonus_type": r.bonus_type,
                "bonus_value": float(r.bonus_value) if r.bonus_value else 0,
                "priority": r.priority,
                "effective_from": str(r.effective_from),
                "effective_until": str(r.effective_until) if r.effective_until else None,
            }
            for r in rows
        ]
        return {"items": items, "total": total, "page": page, "size": size}

    @staticmethod
    async def delete_rule(db: AsyncSession, tenant_id: str, rule_id: str) -> dict:
        """软删除规则"""
        await db.execute(
            text("""
                UPDATE smart_recharge_rules
                SET is_deleted = TRUE, updated_at = now()
                WHERE tenant_id = :tenant_id AND id = :rule_id
            """),
            {"tenant_id": tenant_id, "rule_id": rule_id},
        )
        await db.commit()
        logger.info("smart_recharge_rule_deleted", rule_id=rule_id)
        return {"id": rule_id, "deleted": True}


# ── 内部辅助 ─────────────────────────────────────────────────

def _default_tiers(order_amount_fen: int) -> list[dict]:
    """默认倍数推荐：2x / 3x / 5x 客单价（取整到百元）"""
    tiers = []
    for multiplier in [2, 3, 5]:
        raw = order_amount_fen * multiplier
        # 向上取整到百元（10000分）
        rounded = ((raw + 9999) // 10000) * 10000
        bonus_rate = 5 + (multiplier - 2) * 3  # 5% / 8% / 14%
        bonus_fen = int(rounded * bonus_rate / 100)
        tiers.append({
            "multiplier": multiplier,
            "recharge_amount_fen": rounded,
            "bonus_amount_fen": bonus_fen,
            "bonus_rate_pct": bonus_rate,
            "label": f"充{rounded // 100}元 送{bonus_fen // 100}元",
        })
    return tiers


def _calculate_tiers(
    *,
    order_amount_fen: int,
    multiplier_tiers: list,
    bonus_type: str,
    bonus_value: float,
    min_fen: int,
    max_fen: int,
) -> list[dict]:
    """根据规则计算推荐档位"""
    tiers = []
    for tier in multiplier_tiers:
        multiplier = tier.get("multiplier", 2)
        raw = order_amount_fen * multiplier
        # 向上取整到百元
        rounded = ((raw + 9999) // 10000) * 10000
        rounded = max(min_fen, min(rounded, max_fen))

        tier_bonus_rate = tier.get("bonus_rate_pct", bonus_value)

        if bonus_type == "percentage":
            bonus_fen = int(rounded * tier_bonus_rate / 100)
        elif bonus_type == "fixed":
            bonus_fen = int(tier.get("fixed_bonus_fen", bonus_value * 100))
        else:
            bonus_fen = 0  # coupon 模式不计算金额赠送

        tiers.append({
            "multiplier": multiplier,
            "recharge_amount_fen": rounded,
            "bonus_amount_fen": bonus_fen,
            "bonus_rate_pct": tier_bonus_rate,
            "label": f"充{rounded // 100}元 送{bonus_fen // 100}元",
        })
    return tiers
