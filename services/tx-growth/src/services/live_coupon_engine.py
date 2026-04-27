"""直播优惠券引擎 — 批次创建 + 领取 + 核销 + 统计

核心流程：
  1. 创建优惠券批次（create_coupon_batch） → 按 total_quantity 生成批量记录
  2. 顾客领取（claim_coupon） → 找到可用券，标记 claimed
  3. 核销（redeem_coupon） → 标记 redeemed，记录订单ID和营收
  4. 统计（get_coupon_stats） → 汇总批次级别的领取/核销/营收

金额单位：分(fen)
"""

import secrets
import string
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import structlog
from sqlalchemy import text

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# 内部异常
# ---------------------------------------------------------------------------


class LiveCouponError(Exception):
    """直播优惠券业务异常"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

_CODE_ALPHABET = string.ascii_uppercase + string.digits


def _generate_claim_code(length: int = 8) -> str:
    """生成领取码（8位大写字母+数字）"""
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(length))


# ---------------------------------------------------------------------------
# LiveCouponEngine
# ---------------------------------------------------------------------------


class LiveCouponEngine:
    """直播优惠券核心引擎"""

    # ------------------------------------------------------------------
    # 创建优惠券批次
    # ------------------------------------------------------------------

    async def create_coupon_batch(
        self,
        tenant_id: uuid.UUID,
        event_id: uuid.UUID,
        coupon_name: str,
        discount_desc: str,
        total_quantity: int,
        expires_at: datetime,
        db: Any,
        *,
        coupon_batch_id: Optional[uuid.UUID] = None,
    ) -> dict:
        """为直播活动创建一批优惠券

        Args:
            tenant_id: 租户ID
            event_id: 直播活动ID
            coupon_name: 券名称（如"直播专享券"）
            discount_desc: 折扣描述（如"满100减30"）
            total_quantity: 总数量
            expires_at: 过期时间
            db: AsyncSession
            coupon_batch_id: 关联优惠券系统的批次ID（可选）

        Returns:
            {batch_size, event_id, coupon_name}
        """
        if total_quantity <= 0:
            raise LiveCouponError("INVALID_QUANTITY", "优惠券数量必须大于0")
        if not coupon_name or not coupon_name.strip():
            raise LiveCouponError("EMPTY_NAME", "优惠券名称不能为空")

        now = datetime.now(timezone.utc)
        coupon_ids: list[str] = []

        for _ in range(total_quantity):
            coupon_id = uuid.uuid4()
            claim_code = _generate_claim_code()
            coupon_ids.append(str(coupon_id))

            await db.execute(
                text("""
                    INSERT INTO live_coupons (
                        id, tenant_id, live_event_id, coupon_batch_id,
                        coupon_name, discount_desc, total_quantity,
                        claim_code, status, expires_at,
                        created_at, updated_at
                    ) VALUES (
                        :id, :tenant_id, :event_id, :coupon_batch_id,
                        :coupon_name, :discount_desc, :total_quantity,
                        :claim_code, 'available', :expires_at,
                        :now, :now
                    )
                """),
                {
                    "id": str(coupon_id),
                    "tenant_id": str(tenant_id),
                    "event_id": str(event_id),
                    "coupon_batch_id": str(coupon_batch_id) if coupon_batch_id else None,
                    "coupon_name": coupon_name.strip(),
                    "discount_desc": discount_desc or "",
                    "total_quantity": total_quantity,
                    "claim_code": claim_code,
                    "expires_at": expires_at,
                    "now": now,
                },
            )

        await db.commit()

        log.info(
            "live_coupon.batch_created",
            event_id=str(event_id),
            coupon_name=coupon_name,
            batch_size=total_quantity,
            tenant_id=str(tenant_id),
        )

        return {
            "batch_size": total_quantity,
            "event_id": str(event_id),
            "coupon_name": coupon_name.strip(),
            "coupon_ids": coupon_ids,
        }

    # ------------------------------------------------------------------
    # 顾客领取优惠券
    # ------------------------------------------------------------------

    async def claim_coupon(
        self,
        tenant_id: uuid.UUID,
        event_id: uuid.UUID,
        customer_id: uuid.UUID,
        db: Any,
    ) -> dict:
        """顾客从直播间领取一张可用优惠券

        流程：
          1. 查找该直播活动下状态为 available 的一张券
          2. 标记为 claimed，记录领取人和时间

        Returns:
            {coupon_id, claim_code, coupon_name, discount_desc}
        """
        now = datetime.now(timezone.utc)

        result = await db.execute(
            text("""
                UPDATE live_coupons
                SET status = 'claimed',
                    claimed_by = :customer_id,
                    claimed_at = :now,
                    updated_at = :now
                WHERE id = (
                    SELECT id FROM live_coupons
                    WHERE live_event_id = :event_id
                      AND tenant_id = :tenant_id
                      AND status = 'available'
                      AND is_deleted = false
                      AND (expires_at IS NULL OR expires_at > :now)
                    ORDER BY created_at ASC
                    LIMIT 1
                    FOR UPDATE SKIP LOCKED
                )
                RETURNING id, claim_code, coupon_name, discount_desc
            """),
            {
                "event_id": str(event_id),
                "tenant_id": str(tenant_id),
                "customer_id": str(customer_id),
                "now": now,
            },
        )
        row = result.fetchone()
        if not row:
            raise LiveCouponError("NO_COUPON_AVAILABLE", "该直播活动已无可领取的优惠券")

        await db.commit()

        log.info(
            "live_coupon.claimed",
            coupon_id=str(row.id),
            customer_id=str(customer_id),
            event_id=str(event_id),
            tenant_id=str(tenant_id),
        )

        return {
            "coupon_id": str(row.id),
            "claim_code": row.claim_code,
            "coupon_name": row.coupon_name,
            "discount_desc": row.discount_desc,
        }

    # ------------------------------------------------------------------
    # 核销优惠券
    # ------------------------------------------------------------------

    async def redeem_coupon(
        self,
        tenant_id: uuid.UUID,
        coupon_id: uuid.UUID,
        order_id: uuid.UUID,
        revenue_fen: int,
        db: Any,
    ) -> dict:
        """核销直播优惠券

        Args:
            coupon_id: 券ID
            order_id: 关联的订单ID
            revenue_fen: 该订单带来的营收（分）

        Returns:
            {coupon_id, status, revenue_fen}
        """
        if revenue_fen < 0:
            raise LiveCouponError("INVALID_REVENUE", "营收金额不能为负数")

        now = datetime.now(timezone.utc)

        result = await db.execute(
            text("""
                UPDATE live_coupons
                SET status = 'redeemed',
                    redeemed_order_id = :order_id,
                    redeemed_at = :now,
                    revenue_fen = :revenue_fen,
                    updated_at = :now
                WHERE id = :coupon_id
                  AND tenant_id = :tenant_id
                  AND status = 'claimed'
                  AND is_deleted = false
                RETURNING id, live_event_id
            """),
            {
                "coupon_id": str(coupon_id),
                "tenant_id": str(tenant_id),
                "order_id": str(order_id),
                "revenue_fen": revenue_fen,
                "now": now,
            },
        )
        row = result.fetchone()
        if not row:
            raise LiveCouponError(
                "COUPON_NOT_FOUND",
                "优惠券不存在或当前状态不允许核销",
            )

        await db.commit()

        log.info(
            "live_coupon.redeemed",
            coupon_id=str(coupon_id),
            order_id=str(order_id),
            revenue_fen=revenue_fen,
            event_id=str(row.live_event_id),
            tenant_id=str(tenant_id),
        )

        return {
            "coupon_id": str(coupon_id),
            "status": "redeemed",
            "revenue_fen": revenue_fen,
        }

    # ------------------------------------------------------------------
    # 查询活动下的优惠券
    # ------------------------------------------------------------------

    async def get_event_coupons(
        self,
        tenant_id: uuid.UUID,
        event_id: uuid.UUID,
        db: Any,
    ) -> list[dict]:
        """查询指定直播活动下的所有优惠券

        Returns:
            [{coupon_id, claim_code, coupon_name, status, claimed_by, ...}]
        """
        result = await db.execute(
            text("""
                SELECT
                    id, coupon_name, discount_desc, claim_code,
                    status, claimed_by, claimed_at,
                    redeemed_order_id, redeemed_at, revenue_fen,
                    expires_at, created_at
                FROM live_coupons
                WHERE live_event_id = :event_id
                  AND tenant_id = :tenant_id
                  AND is_deleted = false
                ORDER BY created_at ASC
            """),
            {
                "event_id": str(event_id),
                "tenant_id": str(tenant_id),
            },
        )
        rows = result.fetchall()

        return [
            {
                "coupon_id": str(r.id),
                "coupon_name": r.coupon_name,
                "discount_desc": r.discount_desc,
                "claim_code": r.claim_code,
                "status": r.status,
                "claimed_by": str(r.claimed_by) if r.claimed_by else None,
                "claimed_at": r.claimed_at.isoformat() if r.claimed_at else None,
                "redeemed_order_id": str(r.redeemed_order_id) if r.redeemed_order_id else None,
                "redeemed_at": r.redeemed_at.isoformat() if r.redeemed_at else None,
                "revenue_fen": r.revenue_fen,
                "expires_at": r.expires_at.isoformat() if r.expires_at else None,
            }
            for r in rows
        ]

    # ------------------------------------------------------------------
    # 优惠券统计
    # ------------------------------------------------------------------

    async def get_coupon_stats(
        self,
        tenant_id: uuid.UUID,
        event_id: uuid.UUID,
        db: Any,
    ) -> dict:
        """获取直播活动的优惠券汇总统计

        Returns:
            {total, available, claimed, redeemed, expired, total_revenue_fen}
        """
        result = await db.execute(
            text("""
                SELECT
                    COUNT(*)                                                AS total,
                    COUNT(*) FILTER (WHERE status = 'available')            AS available,
                    COUNT(*) FILTER (WHERE status = 'claimed')              AS claimed,
                    COUNT(*) FILTER (WHERE status = 'redeemed')             AS redeemed,
                    COUNT(*) FILTER (WHERE status = 'expired')              AS expired,
                    COALESCE(SUM(revenue_fen) FILTER (WHERE status = 'redeemed'), 0) AS total_revenue_fen
                FROM live_coupons
                WHERE live_event_id = :event_id
                  AND tenant_id = :tenant_id
                  AND is_deleted = false
            """),
            {
                "event_id": str(event_id),
                "tenant_id": str(tenant_id),
            },
        )
        row = result.fetchone()

        return {
            "event_id": str(event_id),
            "total": row.total if row else 0,
            "available": row.available if row else 0,
            "claimed": row.claimed if row else 0,
            "redeemed": row.redeemed if row else 0,
            "expired": row.expired if row else 0,
            "total_revenue_fen": row.total_revenue_fen if row else 0,
        }
