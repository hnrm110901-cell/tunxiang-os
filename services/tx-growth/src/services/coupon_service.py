"""微信商品券业务逻辑 — WP-1.2 商品券类型支持

管理微信商品券（product coupon）的创建、同步与管理。
商品券是微信支付营销体系中的一种优惠券类型，可与屯象优惠券联动。

与 wechat_pay_promotion_service 的关系：
  - PromotionService → 管理微信侧营销活动（摇优惠/商家名片/投放计划）
  - CouponService   → 管理商品券模板，通过投放计划下发
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.integrations.wechat_pay_promotion import get_wechat_pay_promotion_service

logger = structlog.get_logger(__name__)

# 商品券类型枚举
PRODUCT_COUPON_TYPES = {"cash", "discount", "exchange"}


class ProductCouponService:
    """微信商品券管理"""

    def __init__(self) -> None:
        self._sdk = get_wechat_pay_promotion_service()

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    # ─── CRUD ────────────────────────────────────────────────────────────

    async def create_coupon(
        self,
        tenant_id: str,
        name: str,
        coupon_type: str,
        db: AsyncSession,
        description: str = "",
        cash_amount_fen: int = 0,
        discount_rate: int = 0,
        min_order_fen: int = 0,
        total_quantity: int = 0,
        expiry_days: int = 30,
        start_date: date | None = None,
        end_date: date | None = None,
        wechat_sync: bool = True,
    ) -> dict[str, Any]:
        """创建商品券模板，可选同步至微信支付营销平台。

        coupon_type: cash（代金券）/ discount（折扣券）/ exchange（兑换券）
        """
        if coupon_type not in PRODUCT_COUPON_TYPES:
            raise ValueError(f"不支持的商品券类型: {coupon_type}")

        coupon_id = uuid.uuid4()
        now = self._now()
        sid = uuid.uuid4()

        await db.execute(
            text("""
                INSERT INTO coupons (id, tenant_id, name, description, coupon_type,
                                     cash_amount_fen, discount_rate, min_order_fen,
                                     total_quantity, claimed_count, expiry_days,
                                     start_date, end_date, is_active, created_at, updated_at)
                VALUES (:id, :tid, :name, :desc, :type,
                        :cash, :rate, :min_order,
                        :total, 0, :expiry,
                        :start, :end, true, :now, :now)
            """),
            {
                "id": coupon_id,
                "tid": uuid.UUID(tenant_id),
                "name": name,
                "desc": description,
                "type": coupon_type,
                "cash": cash_amount_fen,
                "rate": discount_rate,
                "min_order": min_order_fen,
                "total": total_quantity,
                "expiry": expiry_days,
                "start": start_date or date.today(),
                "end": end_date or date.today().replace(year=date.today().year + 1),
                "now": datetime.now(timezone.utc),
            },
        )

        wechat_activity_id: str | None = None
        if wechat_sync:
            try:
                wechat_activity_id = await self._sync_to_wechat(
                    tenant_id, str(coupon_id), name, coupon_type,
                    cash_amount_fen, discount_rate, total_quantity,
                )
            except Exception as exc:
                logger.warning("coupon.wechat_sync_failed", coupon_id=str(coupon_id), error=str(exc))

        return {
            "id": str(coupon_id),
            "name": name,
            "coupon_type": coupon_type,
            "wechat_activity_id": wechat_activity_id,
            "created_at": now,
        }

    async def _sync_to_wechat(
        self,
        tenant_id: str,
        coupon_id: str,
        name: str,
        coupon_type: str,
        cash_amount_fen: int,
        discount_rate: int,
        total_quantity: int,
    ) -> str:
        """同步商品券至微信支付营销平台。"""
        plan_name = f"商品券-{name}-{coupon_id[:8]}"
        result = await self._sdk.create_promotion_plan(
            plan_name=plan_name,
            description=f"屯象OS商品券自动同步: {name}",
            coupon_type=coupon_type,
            amount_fen=cash_amount_fen,
            discount_rate=discount_rate,
            total_quantity=total_quantity,
            tenant_id=tenant_id,
        )
        return result.get("activity_id", "")

    async def list_coupons(
        self,
        tenant_id: str,
        db: AsyncSession,
        coupon_type: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> dict[str, Any]:
        """查询商品券列表。"""
        conditions = ["tenant_id = :tid", "is_deleted = false"]
        params: dict[str, Any] = {"tid": uuid.UUID(tenant_id)}

        if coupon_type:
            conditions.append("coupon_type = :ctype")
            params["ctype"] = coupon_type

        where = " AND ".join(conditions)
        offset = (page - 1) * size

        count_result = await db.execute(
            text(f"SELECT COUNT(*) FROM coupons WHERE {where}"),
            params,
        )
        total = count_result.scalar() or 0

        rows = await db.execute(
            text(f"""
                SELECT id, name, description, coupon_type, cash_amount_fen,
                       discount_rate, min_order_fen, total_quantity, claimed_count,
                       expiry_days, start_date, end_date, is_active,
                       created_at, updated_at
                FROM coupons
                WHERE {where}
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
            """),
            {**params, "limit": size, "offset": offset},
        )

        items = []
        for row in rows.mappings():
            items.append({
                "id": str(row["id"]),
                "name": row["name"],
                "description": row["description"] or "",
                "coupon_type": row["coupon_type"],
                "cash_amount_fen": row["cash_amount_fen"] or 0,
                "discount_rate": row["discount_rate"] or 0,
                "min_order_fen": row["min_order_fen"] or 0,
                "total_quantity": row["total_quantity"] or 0,
                "claimed_count": row["claimed_count"] or 0,
                "expiry_days": row["expiry_days"],
                "start_date": row["start_date"].isoformat() if row["start_date"] else None,
                "end_date": row["end_date"].isoformat() if row["end_date"] else None,
                "is_active": row["is_active"],
            })

        return {"items": items, "total": total, "page": page, "size": size}

    async def get_coupon(self, coupon_id: str, tenant_id: str, db: AsyncSession) -> dict[str, Any] | None:
        """查询单个商品券。"""
        row = await db.execute(
            text("""
                SELECT id, name, description, coupon_type, cash_amount_fen,
                       discount_rate, min_order_fen, total_quantity, claimed_count,
                       expiry_days, start_date, end_date, is_active,
                       created_at, updated_at
                FROM coupons
                WHERE id = :id AND tenant_id = :tid AND is_deleted = false
            """),
            {"id": uuid.UUID(coupon_id), "tid": uuid.UUID(tenant_id)},
        )
        seg = row.mappings().one_or_none()
        if not seg:
            return None

        return {
            "id": str(seg["id"]),
            "name": seg["name"],
            "description": seg["description"] or "",
            "coupon_type": seg["coupon_type"],
            "cash_amount_fen": seg["cash_amount_fen"] or 0,
            "discount_rate": seg["discount_rate"] or 0,
            "min_order_fen": seg["min_order_fen"] or 0,
            "total_quantity": seg["total_quantity"] or 0,
            "claimed_count": seg["claimed_count"] or 0,
            "expiry_days": seg["expiry_days"],
            "start_date": seg["start_date"].isoformat() if seg["start_date"] else None,
            "end_date": seg["end_date"].isoformat() if seg["end_date"] else None,
            "is_active": seg["is_active"],
        }

    async def toggle_active(
        self,
        coupon_id: str,
        tenant_id: str,
        db: AsyncSession,
        is_active: bool,
    ) -> bool:
        """启用/停用商品券。"""
        result = await db.execute(
            text("""
                UPDATE coupons
                SET is_active = :active, updated_at = NOW()
                WHERE id = :id AND tenant_id = :tid AND is_deleted = false
            """),
            {"active": is_active, "id": uuid.UUID(coupon_id), "tid": uuid.UUID(tenant_id)},
        )
        return result.rowcount > 0


# Singleton
_service: ProductCouponService | None = None


def get_product_coupon_service() -> ProductCouponService:
    global _service
    if _service is None:
        _service = ProductCouponService()
    return _service
