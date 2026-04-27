"""优惠策略引擎 — 核心不是发券，而是利益结构设计

从「发优惠券」升级到「设计利益结构」：
- 每个优惠都有明确的业务目标（拉新/复购/提频/提客单价）
- 毛利底线硬约束（三条硬约束之一）
- 自动计算 ROI 预估

金额单位：分(fen)

v144 DB 化：移除内存存储，改为 async SQLAlchemy + offers/offer_redemptions 表
"""

import json
import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# OfferEngine
# ---------------------------------------------------------------------------


class OfferEngine:
    """优惠策略引擎 — 核心不是发券，而是利益结构设计"""

    OFFER_TYPES = [
        "new_customer_trial",  # 新客体验
        "first_addon",  # 首单加购
        "second_visit",  # 二次到店
        "birthday_reward",  # 生日礼遇
        "stored_value_bonus",  # 储值赠送
        "banquet_inquiry_gift",  # 宴会咨询礼
        "referral_reward",  # 老带新奖励
        "new_dish_trial",  # 新品尝鲜
        "off_peak_traffic",  # 闲时引流
    ]

    # 各优惠类型的默认参数
    _TYPE_DEFAULTS: dict[str, dict] = {
        "new_customer_trial": {
            "description": "新客首单体验优惠",
            "typical_discount_pct": 15,
            "typical_validity_days": 7,
            "goal": "acquisition",
        },
        "first_addon": {
            "description": "首单加购优惠（满减/加价换购）",
            "typical_discount_pct": 10,
            "typical_validity_days": 1,
            "goal": "aov_lift",
        },
        "second_visit": {
            "description": "二次到店优惠券",
            "typical_discount_pct": 20,
            "typical_validity_days": 14,
            "goal": "retention",
        },
        "birthday_reward": {
            "description": "生日专属礼遇",
            "typical_discount_pct": 25,
            "typical_validity_days": 7,
            "goal": "loyalty",
        },
        "stored_value_bonus": {
            "description": "储值赠送额",
            "typical_discount_pct": 10,
            "typical_validity_days": 365,
            "goal": "lock_in",
        },
        "banquet_inquiry_gift": {
            "description": "宴会咨询到店礼",
            "typical_discount_pct": 5,
            "typical_validity_days": 30,
            "goal": "conversion",
        },
        "referral_reward": {
            "description": "老带新双向奖励",
            "typical_discount_pct": 15,
            "typical_validity_days": 30,
            "goal": "acquisition",
        },
        "new_dish_trial": {
            "description": "新品限时尝鲜价",
            "typical_discount_pct": 20,
            "typical_validity_days": 14,
            "goal": "trial",
        },
        "off_peak_traffic": {
            "description": "闲时到店优惠",
            "typical_discount_pct": 15,
            "typical_validity_days": 30,
            "goal": "traffic",
        },
    }

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    async def _set_tenant(self, db: AsyncSession, tenant_id: str) -> None:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": tenant_id},
        )

    def _row_to_dict(self, row) -> dict:
        def _j(v) -> object:
            if v is None:
                return None
            return v if isinstance(v, (dict, list)) else json.loads(v)

        return {
            "offer_id": str(row.id),
            "name": row.name,
            "offer_type": row.offer_type,
            "description": row.description,
            "goal": row.goal,
            "discount_rules": _j(row.discount_rules),
            "validity_days": row.validity_days,
            "target_segments": _j(row.target_segments) or [],
            "applicable_stores": _j(row.applicable_stores) or [],
            "time_slots": _j(row.time_slots) or [],
            "margin_floor": float(row.margin_floor),
            "max_per_user": row.max_per_user,
            "status": row.status,
            "stats": {
                "issued_count": row.issued_count,
                "redeemed_count": row.redeemed_count,
                "total_discount_fen": row.total_discount_fen,
            },
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    async def create_offer(
        self,
        name: str,
        offer_type: str,
        discount_rules: dict,
        validity_days: int,
        target_segments: list[str],
        stores: list[str],
        time_slots: list[dict],
        margin_floor: float,
        *,
        tenant_id: str,
        db: AsyncSession,
        max_per_user: int = 1,
    ) -> dict:
        """创建优惠策略，INSERT into offers

        Args:
            name: 优惠名称
            offer_type: 优惠类型（OFFER_TYPES 之一）
            discount_rules: 优惠规则
                {"type": "fixed_amount", "amount_fen": 2000} 或
                {"type": "percentage", "pct": 15} 或
                {"type": "threshold", "threshold_fen": 10000, "reduce_fen": 1500}
            validity_days: 有效天数
            target_segments: 目标分群ID列表
            stores: 适用门店ID列表（空列表=全部门店）
            time_slots: 适用时段 [{"start": "14:00", "end": "17:00", "weekdays": [1,2,3,4,5]}]
            margin_floor: 毛利底线（百分比，如 0.45 表示45%）
            tenant_id: 租户ID
            db: 数据库会话
            max_per_user: 每用户最大使用次数
        """
        if offer_type not in self.OFFER_TYPES:
            return {"error": f"不支持的优惠类型: {offer_type}"}

        await self._set_tenant(db, tenant_id)
        tid = uuid.UUID(tenant_id)
        type_defaults = self._TYPE_DEFAULTS.get(offer_type, {})
        now = datetime.now(timezone.utc)
        new_id = uuid.uuid4()

        await db.execute(
            text("""
                INSERT INTO offers
                    (id, tenant_id, name, offer_type, description, goal,
                     discount_rules, validity_days, target_segments,
                     applicable_stores, time_slots, margin_floor, max_per_user,
                     status, issued_count, redeemed_count, total_discount_fen,
                     created_at, updated_at)
                VALUES
                    (:id, :tid, :name, :offer_type, :description, :goal,
                     :discount_rules::jsonb, :validity_days, :target_segments::jsonb,
                     :stores::jsonb, :time_slots::jsonb, :margin_floor, :max_per_user,
                     'active', 0, 0, 0,
                     :now, :now)
            """),
            {
                "id": new_id,
                "tid": tid,
                "name": name,
                "offer_type": offer_type,
                "description": type_defaults.get("description", ""),
                "goal": type_defaults.get("goal", "general"),
                "discount_rules": json.dumps(discount_rules),
                "validity_days": validity_days,
                "target_segments": json.dumps(target_segments),
                "stores": json.dumps(stores),
                "time_slots": json.dumps(time_slots),
                "margin_floor": margin_floor,
                "max_per_user": max_per_user,
                "now": now,
            },
        )
        await db.commit()

        logger.info(
            "offer_engine.create_offer",
            offer_id=str(new_id),
            offer_type=offer_type,
            tenant_id=tenant_id,
        )
        return {
            "offer_id": str(new_id),
            "name": name,
            "offer_type": offer_type,
            "description": type_defaults.get("description", ""),
            "goal": type_defaults.get("goal", "general"),
            "discount_rules": discount_rules,
            "validity_days": validity_days,
            "target_segments": target_segments,
            "stores": stores,
            "time_slots": time_slots,
            "margin_floor": margin_floor,
            "max_per_user": max_per_user,
            "status": "active",
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "stats": {"issued_count": 0, "redeemed_count": 0, "total_discount_fen": 0},
        }

    async def get_offer(
        self,
        offer_id: str,
        *,
        tenant_id: str,
        db: AsyncSession,
    ) -> dict:
        """查询单条优惠策略，SELECT from offers"""
        await self._set_tenant(db, tenant_id)
        tid = uuid.UUID(tenant_id)
        oid = uuid.UUID(offer_id)

        result = await db.execute(
            text("""
                SELECT id, name, offer_type, description, goal,
                       discount_rules, validity_days, target_segments,
                       applicable_stores, time_slots, margin_floor, max_per_user,
                       status, issued_count, redeemed_count, total_discount_fen,
                       created_at, updated_at
                FROM offers
                WHERE id = :oid AND tenant_id = :tid AND is_deleted = false
                LIMIT 1
            """),
            {"oid": oid, "tid": tid},
        )
        row = result.fetchone()
        if not row:
            return {"error": f"优惠不存在: {offer_id}"}
        return self._row_to_dict(row)

    async def list_offers(
        self,
        status: Optional[str] = None,
        goal: Optional[str] = None,
        *,
        tenant_id: str,
        db: AsyncSession,
    ) -> list[dict]:
        """查询优惠策略列表，SELECT from offers（支持 status/goal 过滤）"""
        await self._set_tenant(db, tenant_id)
        tid = uuid.UUID(tenant_id)

        where_parts = ["tenant_id = :tid", "is_deleted = false"]
        params: dict = {"tid": tid}

        if status:
            where_parts.append("status = :status")
            params["status"] = status
        if goal:
            where_parts.append("goal = :goal")
            params["goal"] = goal

        where_clause = " AND ".join(where_parts)
        result = await db.execute(
            text(f"""
                SELECT id, name, offer_type, description, goal,
                       discount_rules, validity_days, target_segments,
                       applicable_stores, time_slots, margin_floor, max_per_user,
                       status, issued_count, redeemed_count, total_discount_fen,
                       created_at, updated_at
                FROM offers
                WHERE {where_clause}
                ORDER BY created_at DESC
            """),
            params,
        )
        rows = result.fetchall()
        return [self._row_to_dict(r) for r in rows]

    async def redeem_offer(
        self,
        offer_id: str,
        member_id: str,
        order_id: Optional[str],
        discount_fen: int,
        *,
        tenant_id: str,
        db: AsyncSession,
        order_total_fen: int = 0,
    ) -> dict:
        """核销优惠，INSERT into offer_redemptions + UPDATE offers.redeemed_count"""
        await self._set_tenant(db, tenant_id)
        tid = uuid.UUID(tenant_id)
        oid = uuid.UUID(offer_id)
        mid = uuid.UUID(member_id)
        order_uuid: Optional[uuid.UUID] = None
        if order_id:
            try:
                order_uuid = uuid.UUID(order_id)
            except ValueError:
                pass

        # 检查优惠是否存在
        offer_result = await db.execute(
            text("""
                SELECT id, status, max_per_user FROM offers
                WHERE id = :oid AND tenant_id = :tid AND is_deleted = false
                LIMIT 1
            """),
            {"oid": oid, "tid": tid},
        )
        offer_row = offer_result.fetchone()
        if not offer_row:
            return {"error": f"优惠不存在: {offer_id}"}
        if offer_row.status != "active":
            return {"error": f"优惠已{offer_row.status}"}

        # 检查用户使用次数
        count_result = await db.execute(
            text("""
                SELECT COUNT(*) FROM offer_redemptions
                WHERE tenant_id = :tid AND offer_id = :oid
                  AND customer_id = :mid AND is_deleted = false
            """),
            {"tid": tid, "oid": oid, "mid": mid},
        )
        used_count = count_result.scalar() or 0
        if used_count >= offer_row.max_per_user:
            return {"error": "已达使用上限"}

        now = datetime.now(timezone.utc)
        redemption_id = uuid.uuid4()

        await db.execute(
            text("""
                INSERT INTO offer_redemptions
                    (id, tenant_id, offer_id, customer_id, order_id,
                     order_total_fen, discount_fen, redeemed_at, created_at)
                VALUES
                    (:id, :tid, :oid, :mid, :order_id,
                     :order_total_fen, :discount_fen, :now, :now)
            """),
            {
                "id": redemption_id,
                "tid": tid,
                "oid": oid,
                "mid": mid,
                "order_id": order_uuid,
                "order_total_fen": order_total_fen,
                "discount_fen": discount_fen,
                "now": now,
            },
        )

        # 更新 offers 聚合统计
        await db.execute(
            text("""
                UPDATE offers
                SET redeemed_count = redeemed_count + 1,
                    total_discount_fen = total_discount_fen + :discount_fen,
                    updated_at = :now
                WHERE id = :oid AND tenant_id = :tid
            """),
            {"discount_fen": discount_fen, "now": now, "oid": oid, "tid": tid},
        )
        await db.commit()

        logger.info(
            "offer_engine.redeem_offer",
            redemption_id=str(redemption_id),
            offer_id=offer_id,
            member_id=member_id,
            discount_fen=discount_fen,
            tenant_id=tenant_id,
        )
        return {
            "redemption_id": str(redemption_id),
            "offer_id": offer_id,
            "member_id": member_id,
            "order_id": order_id,
            "discount_fen": discount_fen,
            "order_total_fen": order_total_fen,
            "redeemed_at": now.isoformat(),
        }

    async def get_offer_stats(
        self,
        offer_id: str,
        *,
        tenant_id: str,
        db: AsyncSession,
    ) -> dict:
        """聚合统计优惠效果：核销率、总优惠金额、归因收入、利润贡献"""
        await self._set_tenant(db, tenant_id)
        tid = uuid.UUID(tenant_id)
        oid = uuid.UUID(offer_id)

        offer_result = await db.execute(
            text("""
                SELECT id, name, offer_type, issued_count, redeemed_count, total_discount_fen
                FROM offers
                WHERE id = :oid AND tenant_id = :tid AND is_deleted = false
                LIMIT 1
            """),
            {"oid": oid, "tid": tid},
        )
        offer_row = offer_result.fetchone()
        if not offer_row:
            return {"error": f"优惠不存在: {offer_id}"}

        redemption_result = await db.execute(
            text("""
                SELECT COUNT(*) AS cnt,
                       COALESCE(SUM(order_total_fen), 0) AS total_revenue,
                       COALESCE(SUM(discount_fen), 0) AS total_discount
                FROM offer_redemptions
                WHERE tenant_id = :tid AND offer_id = :oid AND is_deleted = false
            """),
            {"tid": tid, "oid": oid},
        )
        r = redemption_result.fetchone()
        actual_redeemed = int(r.cnt) if r else 0
        total_revenue_fen = int(r.total_revenue) if r else 0
        actual_discount_fen = int(r.total_discount) if r else 0

        issued = offer_row.issued_count
        redeemed = actual_redeemed or offer_row.redeemed_count
        redemption_rate = redeemed / max(1, issued)
        revenue_per_redemption = total_revenue_fen // max(1, redeemed) if total_revenue_fen else 0
        profit_contribution_fen = total_revenue_fen - actual_discount_fen

        return {
            "offer_id": offer_id,
            "offer_name": offer_row.name,
            "offer_type": offer_row.offer_type,
            "issued_count": issued,
            "redeemed_count": redeemed,
            "redemption_rate": round(redemption_rate, 4),
            "total_discount_fen": actual_discount_fen or offer_row.total_discount_fen,
            "total_discount_yuan": round((actual_discount_fen or offer_row.total_discount_fen) / 100, 2),
            "total_revenue_fen": total_revenue_fen,
            "total_revenue_yuan": round(total_revenue_fen / 100, 2),
            "revenue_per_redemption_fen": revenue_per_redemption,
            "profit_contribution_fen": profit_contribution_fen,
            "profit_contribution_yuan": round(profit_contribution_fen / 100, 2),
        }

    # ------------------------------------------------------------------
    # 纯业务逻辑（不依赖存储，保留原有算法）
    # ------------------------------------------------------------------

    def calculate_offer_cost(self, discount_rules: dict) -> dict:
        """计算优惠的预估成本和 ROI（纯计算，不读写 DB）

        Args:
            discount_rules: 已从 DB 取出的 discount_rules 字典
        """
        rule_type = discount_rules.get("type", "")
        estimated_redemption_count = 100  # 预估核销数
        avg_order_fen = 12000  # 平均客单价 120元

        if rule_type == "fixed_amount":
            per_discount_fen = discount_rules.get("amount_fen", 0)
        elif rule_type == "percentage":
            pct = discount_rules.get("pct", 0)
            per_discount_fen = int(avg_order_fen * pct / 100)
        elif rule_type == "threshold":
            per_discount_fen = discount_rules.get("reduce_fen", 0)
        else:
            per_discount_fen = 0

        projected_cost_fen = per_discount_fen * estimated_redemption_count
        projected_revenue_lift_fen = int(avg_order_fen * 1.5 * estimated_redemption_count)
        projected_roi = (
            round(projected_revenue_lift_fen / max(1, projected_cost_fen), 2) if projected_cost_fen > 0 else 0
        )

        return {
            "estimated_redemption_count": estimated_redemption_count,
            "per_discount_fen": per_discount_fen,
            "projected_cost_fen": projected_cost_fen,
            "projected_cost_yuan": round(projected_cost_fen / 100, 2),
            "projected_revenue_lift_fen": projected_revenue_lift_fen,
            "projected_revenue_lift_yuan": round(projected_revenue_lift_fen / 100, 2),
            "projected_roi": projected_roi,
        }

    def check_margin_compliance(self, margin_floor: float, order_data: dict) -> dict:
        """毛利合规检查 — 三条硬约束之一（纯计算，不读写 DB）

        Args:
            margin_floor: 毛利底线（已从 DB 取出）
            order_data: {"total_fen": 15000, "cost_fen": 6000, "discount_fen": 2000}
        """
        total_fen = order_data.get("total_fen", 0)
        cost_fen = order_data.get("cost_fen", 0)
        discount_fen = order_data.get("discount_fen", 0)

        revenue_after_discount = total_fen - discount_fen
        if revenue_after_discount <= 0:
            return {
                "compliant": False,
                "reason": "优惠后收入为零或负数",
                "margin_rate": 0.0,
                "margin_floor": margin_floor,
            }

        margin_rate = (revenue_after_discount - cost_fen) / revenue_after_discount
        compliant = margin_rate >= margin_floor

        return {
            "compliant": compliant,
            "margin_rate": round(margin_rate, 4),
            "margin_floor": margin_floor,
            "revenue_after_discount_fen": revenue_after_discount,
            "cost_fen": cost_fen,
            "profit_fen": revenue_after_discount - cost_fen,
            "reason": "" if compliant else f"毛利率 {margin_rate:.1%} 低于底线 {margin_floor:.1%}",
        }

    def recommend_offer_for_segment(self, segment_id: str) -> list[dict]:
        """AI 推荐：为特定人群推荐优惠策略（纯内存配置，不读写 DB）"""
        segment_offer_map: dict[str, list[dict]] = {
            "new_customer": [
                {
                    "offer_type": "new_customer_trial",
                    "name": "新客首单立减20元",
                    "discount_rules": {"type": "fixed_amount", "amount_fen": 2000},
                    "reason": "降低新客首单门槛，提高转化率",
                    "expected_roi": 3.5,
                },
            ],
            "first_no_repeat": [
                {
                    "offer_type": "second_visit",
                    "name": "二次到店享8折",
                    "discount_rules": {"type": "percentage", "pct": 20},
                    "reason": "首单未复购客户需要强激励驱动第二次消费",
                    "expected_roi": 2.8,
                },
            ],
            "dormant": [
                {
                    "offer_type": "second_visit",
                    "name": "老客回归礼-满100减30",
                    "discount_rules": {"type": "threshold", "threshold_fen": 10000, "reduce_fen": 3000},
                    "reason": "沉睡客需要较大力度召回",
                    "expected_roi": 2.2,
                },
            ],
            "high_frequency": [
                {
                    "offer_type": "stored_value_bonus",
                    "name": "充500送80",
                    "discount_rules": {"type": "stored_value", "charge_fen": 50000, "bonus_fen": 8000},
                    "reason": "高频客户适合用储值锁客，提高粘性",
                    "expected_roi": 4.5,
                },
            ],
            "high_value_banquet": [
                {
                    "offer_type": "banquet_inquiry_gift",
                    "name": "宴会预订享专属管家服务",
                    "discount_rules": {"type": "service_upgrade", "description": "专属管家+赠送果盘"},
                    "reason": "高价值客户重服务不重折扣",
                    "expected_roi": 6.0,
                },
            ],
            "price_sensitive": [
                {
                    "offer_type": "off_peak_traffic",
                    "name": "工作日午市套餐特惠",
                    "discount_rules": {"type": "fixed_amount", "amount_fen": 1500},
                    "reason": "引导闲时消费，不影响高峰利润",
                    "expected_roi": 3.0,
                },
            ],
        }

        recommendations = segment_offer_map.get(segment_id, [])
        if not recommendations:
            recommendations = [
                {
                    "offer_type": "new_dish_trial",
                    "name": "新品尝鲜券-满80减15",
                    "discount_rules": {"type": "threshold", "threshold_fen": 8000, "reduce_fen": 1500},
                    "reason": "新品试吃提升菜品覆盖面",
                    "expected_roi": 2.5,
                },
            ]

        return recommendations
